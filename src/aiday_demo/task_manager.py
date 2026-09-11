"""Task lifecycle manager (cloud/veFaaS-safe).

One task == one video generation job identified by a unique task_id.

Design goals for elastic multi-instance + idle-recycle (veFaaS):
  * Non-blocking endpoints: submit / poll return immediately; heavy work runs
    off the request thread in a bounded pool.
  * All state persisted to TOS under tasks/<task_id>/state.json, so any
    instance can serve any task and resume it after recycle.
  * Resumable & self-healing: the pipeline is a state machine keyed only off
    persisted fields (group_id / asset_id / ark_task_id / video_url). A short
    TOS "lease" prevents two instances from driving the same task at once;
    if the lease owner dies (idle-recycle), the lease lapses and the next poll
    on any instance transparently resumes the task from where it left off.
  * Stable task_id reconnect: clients just re-GET the task; late/stale workers
    are ignored via the lease (owner + expiry), so no cross-task races and no
    path collisions between windows.

Pipeline steps (each idempotent, persisted):
  1. upload (normalized) portrait to TOS (public read)
  2. create per-project asset group (project <-> group one-to-one)
  3. register portrait as an asset, poll until Active
  4. submit seedance-2.5 generation (asset://), retry up to 3 times
  5. poll until succeeded, re-host video into our public bucket, verify readable
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Optional

from .asset_library import AssetLibraryError, asset_library
from .config import settings
from .image_utils import normalize_portrait
from .tos_store import tos_store
from .video_client import (
    DEFAULT_DURATION,
    DEFAULT_RATIO,
    DEFAULT_RESOLUTION,
    VALID_GENDERS,
    VALID_DURATIONS,
    VALID_RATIOS,
    VALID_RESOLUTIONS,
    VideoGenError,
    build_video_prompt,
    video_client,
)

logger = logging.getLogger("aiday.tasks")

TTL_SECONDS = 24 * 3600
MAX_GEN_RETRIES = 3

# Lease held by whichever instance is actively driving a task's pipeline.
LEASE_SECONDS = 180

# Bounded pool so cloud multi-instance concurrency stays predictable.
_EXECUTOR = ThreadPoolExecutor(max_workers=10, thread_name_prefix="videogen")

# Unique per process/instance; used as the lease owner id.
INSTANCE_ID = f"{os.getpid()}-{uuid.uuid4().hex[:6]}"

# Statuses
S_CREATED = "created"
S_UPLOADING = "uploading"
S_ASSET = "asset_processing"
S_GENERATING = "generating"
S_SUCCEEDED = "succeeded"
S_FAILED = "failed"
S_EXPIRED = "expired"

_TERMINAL = {S_SUCCEEDED, S_FAILED, S_EXPIRED}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _state_key(task_id: str) -> str:
    return f"tasks/{task_id}/state.json"


def new_task_id() -> str:
    ts = _now().strftime("%Y%m%d%H%M%S")
    return f"task-{ts}-{uuid.uuid4().hex[:8]}"


class TaskManager:
    def __init__(self) -> None:
        # Guards concurrent _drive calls for the same task within THIS instance.
        self._inflight: set[str] = set()
        self._inflight_guard = threading.Lock()

    # ---- state persistence -------------------------------------------------
    def load(self, task_id: str) -> Optional[dict]:
        state = tos_store.get_json(_state_key(task_id))
        if state is None:
            return None
        return self._apply_expiry(state)

    def _save(self, state: dict, if_match: str | None = None) -> None:
        state["updated_at"] = _now_iso()
        tos_store.put_json(_state_key(state["task_id"]), state, if_match=if_match)

    def _apply_expiry(self, state: dict) -> dict:
        try:
            created = datetime.fromisoformat(state["created_at"])
        except (KeyError, TypeError, ValueError):
            return state
        age = (_now() - created).total_seconds()
        if age > TTL_SECONDS and state.get("status") != S_EXPIRED:
            task_id = state["task_id"]
            try:
                tos_store.delete_prefix(
                    f"tasks/{task_id}/",
                    keep={_state_key(task_id)},
                )
            except Exception:  # noqa: BLE001 - expiry must remain observable
                logger.exception("Failed to clean expired TOS task %s", task_id)
            state = {
                "task_id": task_id,
                "status": S_EXPIRED,
                "created_at": state["created_at"],
                "expired_at": _now_iso(),
                "video_url": None,
                "error": None,
                "lease_owner": None,
                "lease_until": None,
            }
            self._save(state)
        return state

    # ---- lease helpers -----------------------------------------------------
    @staticmethod
    def _lease_alive(state: dict) -> bool:
        exp = state.get("lease_until")
        if not exp:
            return False
        try:
            return datetime.fromisoformat(exp) > _now()
        except ValueError:
            return False

    def _acquire_lease(self, task_id: str) -> Optional[dict]:
        """Re-read state and take the lease iff nobody else holds a live one.

        Returns the fresh state if acquired, else None.
        """
        loaded = tos_store.get_json_with_etag(_state_key(task_id))
        if loaded is None:
            return None
        state, etag = loaded
        state = self._apply_expiry(state)
        if state.get("status") in _TERMINAL:
            return None
        if self._lease_alive(state) and state.get("lease_owner") != INSTANCE_ID:
            return None  # another live instance owns it
        state["lease_owner"] = INSTANCE_ID
        state["lease_until"] = (_now() + timedelta(seconds=LEASE_SECONDS)).isoformat()
        try:
            self._save(state, if_match=etag)
        except Exception as exc:  # another instance won the conditional write
            if getattr(exc, "status_code", None) in (409, 412):
                return None
            raise
        return state

    def _renew_lease(self, state: dict) -> None:
        state["lease_until"] = (_now() + timedelta(seconds=LEASE_SECONDS)).isoformat()
        self._save(state)

    def _release_lease(self, task_id: str) -> None:
        state = self.load(task_id)
        if state and state.get("lease_owner") == INSTANCE_ID:
            state["lease_owner"] = None
            state["lease_until"] = None
            self._save(state)

    # ---- creation ----------------------------------------------------------
    def create(self) -> dict:
        task_id = new_task_id()
        state = {
            "task_id": task_id,
            "status": S_CREATED,
            "created_at": _now_iso(),
            "ratio": DEFAULT_RATIO,
            "duration": DEFAULT_DURATION,
            "resolution": DEFAULT_RESOLUTION,
            "gender": None,
            "prompt": None,
            "reference_image_refs": list(settings.reference_image_refs),
            "portrait_url": None,
            "portrait_key": None,
            "group_id": None,
            "asset_id": None,
            "portrait_asset_ref": None,
            "ark_task_id": None,
            "video_url": None,
            "attempts": 0,
            "error": None,
            "lease_owner": None,
            "lease_until": None,
        }
        self._save(state)
        return state

    # ---- submission (non-blocking) ----------------------------------------
    def submit(
        self,
        task_id: str,
        image_bytes: bytes,
        image_ext: str,
        ratio: str,
        duration: int,
        resolution: str,
        gender: str,
    ) -> dict:
        state = self.load(task_id)
        if state is None:
            raise ValueError(f"unknown task_id {task_id}")
        if gender not in VALID_GENDERS:
            raise ValueError(f"unsupported gender {gender!r}")
        if state.get("status") != S_CREATED:
            if state.get("gender") == gender and state.get("portrait_url"):
                return state
            raise ValueError(f"task {task_id} was already submitted")

        # Normalize the portrait so it always satisfies the asset library
        # constraints (aspect ratio 0.4-2.5, side 300-6000px), then persist it
        # to TOS so it's available for the asset library.
        try:
            norm_bytes, ext = normalize_portrait(image_bytes)
        except Exception:  # noqa: BLE001 - fall back to the raw upload
            norm_bytes = image_bytes
            ext = image_ext if image_ext.startswith(".") else f".{image_ext}"
        portrait_key = f"tasks/{task_id}/portrait{ext}"
        portrait_url = tos_store.put_bytes(portrait_key, norm_bytes)

        state.update(
            {
                "status": S_UPLOADING,
                "ratio": ratio if ratio in VALID_RATIOS else DEFAULT_RATIO,
                "duration": duration if duration in VALID_DURATIONS else DEFAULT_DURATION,
                "resolution": (
                    resolution
                    if resolution in VALID_RESOLUTIONS
                    else DEFAULT_RESOLUTION
                ),
                "gender": gender,
                "prompt": build_video_prompt(gender),
                "reference_image_refs": list(settings.reference_image_refs),
                "portrait_url": portrait_url,
                "portrait_key": portrait_key,
            }
        )
        self._save(state)

        self._schedule_drive(task_id)
        return state

    # ---- resume / self-heal (called from polls) ---------------------------
    def maybe_resume(self, state: dict) -> None:
        """From a GET poll: if the task is unfinished and unattended, drive it.

        Cheap check on the already-loaded state (no extra TOS read): only kicks
        a worker when the task is past upload, not terminal, and its lease is
        stale (owner recycled) — this is what revives tasks after idle-recycle.
        """
        if state.get("status") in _TERMINAL or state.get("status") == S_CREATED:
            return
        if state.get("portrait_url") is None:
            return
        if self._lease_alive(state):
            return
        self._schedule_drive(state["task_id"])

    def _schedule_drive(self, task_id: str) -> None:
        # Avoid piling up duplicate drivers for the same task on this instance.
        with self._inflight_guard:
            if task_id in self._inflight:
                return
            self._inflight.add(task_id)
        _EXECUTOR.submit(self._drive, task_id)

    # ---- resumable pipeline ------------------------------------------------
    def _drive(self, task_id: str) -> None:
        try:
            state = self._acquire_lease(task_id)
            if state is None:
                return  # terminal, gone, or owned by a live instance
            try:
                self._run_steps(state)
            finally:
                self._release_lease(task_id)
        except Exception as e:  # noqa: BLE001 - persist any failure
            fresh = self.load(task_id) or {"task_id": task_id}
            fresh["status"] = S_FAILED
            fresh["error"] = str(e)
            fresh["lease_owner"] = None
            fresh["lease_until"] = None
            self._save(fresh)
        finally:
            with self._inflight_guard:
                self._inflight.discard(task_id)

    def _run_steps(self, state: dict) -> None:
        task_id = state["task_id"]

        # Step 2: asset group (skip if already created)
        if not state.get("group_id"):
            state["status"] = S_ASSET
            self._save(state)
            state["group_id"] = asset_library.create_asset_group(
                name=task_id, description=f"AI video task {task_id}"
            )
            self._save(state)

        # Step 3a: register asset (skip if already registered)
        if not state.get("asset_id"):
            state["status"] = S_ASSET
            self._save(state)
            state["asset_id"] = asset_library.create_asset(
                group_id=state["group_id"],
                image_url=state["portrait_url"],
                name=task_id,
            )
            state["portrait_asset_ref"] = f"asset://{state['asset_id']}"
            self._save(state)

        # Step 3b: wait until asset Active (renew lease while waiting)
        self._wait_asset_active(state)

        # Step 4+5: generate (resume existing ark task if present)
        state["status"] = S_GENERATING
        self._save(state)
        self._generate_with_retries(state)

    def _wait_asset_active(self, state: dict, timeout: float = 300.0) -> None:
        asset_id = state["asset_id"]
        deadline = time.time() + timeout
        while time.time() < deadline:
            info = asset_library.get_asset(asset_id)
            status = info.get("Status", "Unknown")
            if status == "Active":
                return
            if status == "Failed":
                raise AssetLibraryError(f"Asset {asset_id} preprocessing Failed")
            self._renew_lease(state)
            time.sleep(5)
        raise AssetLibraryError(f"Asset {asset_id} not Active within {timeout}s")

    def _generate_with_retries(self, state: dict) -> None:
        task_id = state["task_id"]
        last_err: Optional[str] = state.get("error")

        while (state.get("attempts") or 0) < MAX_GEN_RETRIES:
            try:
                # Resume an in-flight ark task, or submit a fresh one.
                if not state.get("ark_task_id"):
                    state["attempts"] = (state.get("attempts") or 0) + 1
                    self._save(state)
                    state["ark_task_id"] = video_client.create_task(
                        asset_id=state["asset_id"],
                        gender=state.get("gender") or "male",
                        ratio=state["ratio"],
                        duration=state["duration"],
                        resolution=state.get("resolution", DEFAULT_RESOLUTION),
                        prompt=state.get("prompt"),
                        reference_image_refs=state.get("reference_image_refs"),
                    )
                    self._save(state)

                signed_url = self._poll_video(state)

                # Re-host into our public bucket. Content-Disposition:attachment
                # forces a download on mobile browsers (iOS Safari/Chrome,
                # Android) instead of opening an inline player.
                video_key = f"tasks/{task_id}/video.mp4"
                public_url = tos_store.upload_from_url(
                    video_key,
                    signed_url,
                    content_type="video/mp4",
                    content_disposition=f'attachment; filename="ai-video-{task_id}.mp4"',
                )
                if not tos_store.verify_readable(public_url):
                    raise VideoGenError("uploaded video not publicly readable")

                state["status"] = S_SUCCEEDED
                state["video_url"] = public_url
                state["source_video_url"] = signed_url
                state["error"] = None
                self._save(state)
                return
            except Exception as e:  # noqa: BLE001
                last_err = f"attempt {state.get('attempts')}/{MAX_GEN_RETRIES}: {e}"
                # Drop the failed ark task so the next attempt submits a new one.
                state["ark_task_id"] = None
                state["error"] = last_err
                self._save(state)
                time.sleep(2)

        state["status"] = S_FAILED
        state["error"] = last_err or "generation failed"
        self._save(state)

    def _poll_video(self, state: dict, timeout: float = 1800.0) -> str:
        ark_task_id = state["ark_task_id"]
        deadline = time.time() + timeout
        while time.time() < deadline:
            task = video_client.get_task(ark_task_id)
            status = getattr(task, "status", None)
            if status == "succeeded":
                url = video_client.extract_video_url(task)
                if not url:
                    raise VideoGenError(f"Task {ark_task_id} succeeded but no video_url")
                return url
            if status in ("failed", "cancelled"):
                err = getattr(task, "error", None)
                raise VideoGenError(f"Task {ark_task_id} {status}: {err}")
            self._renew_lease(state)
            time.sleep(60)
        raise VideoGenError(f"Task {ark_task_id} not done within {timeout}s")


task_manager = TaskManager()

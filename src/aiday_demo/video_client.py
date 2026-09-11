"""Seedance-2.5 video generation via ModelArk runtime SDK."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from byteplussdkarkruntime import Ark

from .config import settings

logger = logging.getLogger("aiday.video")


def _dump(obj) -> str:
    """Best-effort JSON serialization of SDK request/response objects for logs."""
    try:
        if hasattr(obj, "model_dump"):
            obj = obj.model_dump()
        elif hasattr(obj, "dict"):
            obj = obj.dict()
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001 - logging must never raise
        return repr(obj)


PROMPT_PATH = Path(__file__).with_name("prompt_cantonese.txt")
VIDEO_PROMPT = PROMPT_PATH.read_text(encoding="utf-8").strip()

VALID_RATIOS = {"21:9", "16:9", "9:16"}
DEFAULT_RATIO = "16:9"
VALID_DURATIONS = {10, 20, 30}
DEFAULT_DURATION = 30
VALID_RESOLUTIONS = {"720p", "480p"}
DEFAULT_RESOLUTION = "480p"
VALID_GENDERS = {"male": "男性", "female": "女性"}


def build_video_prompt(gender: str) -> str:
    try:
        gender_label = VALID_GENDERS[gender]
    except KeyError as exc:
        raise ValueError(f"unsupported gender {gender!r}") from exc
    return f"人物性别是 - {gender_label}。\n{VIDEO_PROMPT}"


def _asset_ref(asset_id: str) -> str:
    asset_id = asset_id.strip()
    if not asset_id:
        raise ValueError("empty asset id")
    return asset_id if asset_id.startswith("asset://") else f"asset://{asset_id}"


class VideoGenError(RuntimeError):
    pass


class VideoClient:
    def __init__(self) -> None:
        self._client = Ark(base_url=settings.LLM_BASE_URL, api_key=settings.ARK_API_KEY)
        self._model = settings.VIDEO_MODEL

    def create_task(
        self,
        asset_id: str,
        gender: str,
        ratio: str = DEFAULT_RATIO,
        duration: int = DEFAULT_DURATION,
        resolution: str = DEFAULT_RESOLUTION,
        prompt: str | None = None,
        reference_image_refs: list[str] | tuple[str, ...] | None = None,
    ) -> str:
        """Submit a generation task.

        Image 1 is the uploaded portrait. Images 2 and 3 are fixed visual
        references. Every image uses asset://<asset-id>; raw image URLs are
        never sent to the video model.
        """
        if ratio not in VALID_RATIOS:
            ratio = DEFAULT_RATIO
        if duration not in VALID_DURATIONS:
            duration = DEFAULT_DURATION
        if resolution not in VALID_RESOLUTIONS:
            resolution = DEFAULT_RESOLUTION

        effective_prompt = prompt or build_video_prompt(gender)
        fixed_image_refs = reference_image_refs or settings.reference_image_refs
        reference_images = [
            _asset_ref(asset_id),
            *[_asset_ref(image_ref) for image_ref in fixed_image_refs],
        ]
        payload = {
            "model": self._model,
            "content": [
                {"type": "text", "text": effective_prompt},
                *[
                    {
                        "type": "image_url",
                        "role": "reference_image",
                        "image_url": {"url": image_ref},
                    }
                    for image_ref in reference_images
                ],
            ],
            "generate_audio": True,
            "ratio": ratio,
            "duration": duration,
            "resolution": resolution,
            "watermark": False,
        }
        endpoint = f"{settings.LLM_BASE_URL.rstrip('/')}/contents/generations/tasks"
        # Full HTTP request (Authorization redacted).
        logger.info(
            "VIDEO MODEL HTTP REQUEST\n"
            "POST %s\n"
            "Headers: %s\n"
            "Body: %s",
            endpoint,
            _dump(
                {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer ***REDACTED***",
                }
            ),
            _dump(payload),
        )
        try:
            result = self._client.content_generation.tasks.create(**payload)
        except Exception as exc:  # noqa: BLE001 - log then re-raise
            logger.error("VIDEO MODEL HTTP RESPONSE (error): %s", repr(exc))
            raise
        logger.info("VIDEO MODEL HTTP RESPONSE\n%s", _dump(result))
        return result.id

    def get_task(self, ark_task_id: str):
        result = self._client.content_generation.tasks.get(task_id=ark_task_id)
        endpoint = (
            f"{settings.LLM_BASE_URL.rstrip('/')}"
            f"/contents/generations/tasks/{ark_task_id}"
        )
        logger.info(
            "VIDEO MODEL HTTP REQUEST\nGET %s\nVIDEO MODEL HTTP RESPONSE\n%s",
            endpoint,
            _dump(result),
        )
        return result

    @staticmethod
    def extract_video_url(task_obj) -> Optional[str]:
        """Pull the signed video URL from a succeeded task object."""
        content = getattr(task_obj, "content", None)
        if content is None:
            return None
        url = getattr(content, "video_url", None)
        if url:
            return url
        if isinstance(content, dict):
            return content.get("video_url")
        return None

    def wait_for_result(
        self,
        ark_task_id: str,
        timeout: float = 1800.0,
        interval: float = 60.0,
    ) -> str:
        """Poll until succeeded; returns signed video URL. Raises on failure/timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            task = self.get_task(ark_task_id)
            status = getattr(task, "status", None)
            if status == "succeeded":
                url = self.extract_video_url(task)
                if not url:
                    raise VideoGenError(f"Task {ark_task_id} succeeded but no video_url")
                return url
            if status in ("failed", "cancelled"):
                err = getattr(task, "error", None)
                raise VideoGenError(f"Task {ark_task_id} {status}: {err}")
            time.sleep(interval)
        raise VideoGenError(f"Task {ark_task_id} not done within {timeout}s")


video_client = VideoClient()

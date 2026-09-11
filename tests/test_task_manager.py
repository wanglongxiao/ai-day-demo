from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import aiday_demo.task_manager as task_manager_module
from aiday_demo.task_manager import S_EXPIRED, S_SUCCEEDED, TaskManager, new_task_id


class TaskManagerTest(unittest.TestCase):
    def test_task_ids_are_unique(self) -> None:
        task_ids = {new_task_id() for _ in range(1000)}
        self.assertEqual(len(task_ids), 1000)

    def test_successful_task_expires_and_tos_assets_are_cleaned(self) -> None:
        now = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
        state = {
            "task_id": "task-old",
            "status": S_SUCCEEDED,
            "created_at": (now - timedelta(hours=25)).isoformat(),
            "video_url": "https://example.test/video.mp4",
        }
        store = Mock()

        with (
            patch.object(task_manager_module, "_now", return_value=now),
            patch.object(task_manager_module, "tos_store", store),
        ):
            expired = TaskManager()._apply_expiry(state)

        self.assertEqual(expired["status"], S_EXPIRED)
        self.assertIsNone(expired["video_url"])
        store.delete_prefix.assert_called_once_with(
            "tasks/task-old/",
            keep={"tasks/task-old/state.json"},
        )
        store.put_json.assert_called_once()

    def test_lease_acquisition_uses_state_etag(self) -> None:
        now = datetime.now(timezone.utc)
        state = {
            "task_id": "task-cas",
            "status": "uploading",
            "created_at": now.isoformat(),
            "lease_owner": None,
            "lease_until": None,
        }
        store = Mock()
        store.get_json_with_etag.return_value = (state, "etag-1")

        with patch.object(task_manager_module, "tos_store", store):
            acquired = TaskManager()._acquire_lease("task-cas")

        self.assertEqual(acquired["lease_owner"], task_manager_module.INSTANCE_ID)
        store.put_json.assert_called_once()
        self.assertEqual(store.put_json.call_args.kwargs["if_match"], "etag-1")

    def test_lease_conflict_is_ignored(self) -> None:
        now = datetime.now(timezone.utc)
        state = {
            "task_id": "task-cas",
            "status": "uploading",
            "created_at": now.isoformat(),
            "lease_owner": None,
            "lease_until": None,
        }
        conflict = RuntimeError("precondition failed")
        conflict.status_code = 412
        store = Mock()
        store.get_json_with_etag.return_value = (state, "etag-1")
        store.put_json.side_effect = conflict

        with patch.object(task_manager_module, "tos_store", store):
            acquired = TaskManager()._acquire_lease("task-cas")

        self.assertIsNone(acquired)


if __name__ == "__main__":
    unittest.main()

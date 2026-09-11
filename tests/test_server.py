from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from aiday_demo.server import app, task_manager


class GenerateEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_gender_is_required(self) -> None:
        response = self.client.post(
            "/api/task/task-1/generate",
            files={"image": ("portrait.jpg", b"image", "image/jpeg")},
        )
        self.assertEqual(response.status_code, 422)

    def test_invalid_gender_is_rejected_before_upload(self) -> None:
        response = self.client.post(
            "/api/task/task-1/generate",
            data={"gender": "other"},
            files={"image": ("portrait.jpg", b"image", "image/jpeg")},
        )
        self.assertEqual(response.status_code, 400)

    def test_defaults_and_gender_are_forwarded_to_task_manager(self) -> None:
        with patch.object(
            task_manager,
            "submit",
            return_value={"task_id": "task-1", "status": "uploading"},
        ) as submit:
            response = self.client.post(
                "/api/task/task-1/generate",
                data={"gender": "female"},
                files={"image": ("portrait.jpg", b"image", "image/jpeg")},
            )

        self.assertEqual(response.status_code, 200)
        submit.assert_called_once_with(
            "task-1",
            b"image",
            ".jpg",
            "16:9",
            30,
            "480p",
            "female",
        )


if __name__ == "__main__":
    unittest.main()

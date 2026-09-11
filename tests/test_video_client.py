from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from aiday_demo.video_client import (
    DEFAULT_DURATION,
    DEFAULT_RATIO,
    DEFAULT_RESOLUTION,
    VIDEO_PROMPT,
    VideoClient,
    build_video_prompt,
)


class _CapturingTasks:
    def __init__(self) -> None:
        self.payload = None

    def create(self, **payload):
        self.payload = payload
        return SimpleNamespace(id="ark-task-1")


class VideoClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = _CapturingTasks()
        self.client = object.__new__(VideoClient)
        self.client._model = "dreamina-seedance-2-5-260628"
        self.client._client = SimpleNamespace(
            content_generation=SimpleNamespace(tasks=self.tasks)
        )

    def test_packaged_prompt_matches_docs_source(self) -> None:
        source = (
            Path(__file__).parents[1] / "docs" / "prompt_cantonese.txt"
        ).read_text(encoding="utf-8").strip()
        self.assertEqual(VIDEO_PROMPT, source)
        self.assertIn("全片没有背景音乐，只有环境音效和角色对白", VIDEO_PROMPT)
        self.assertIn("无 BGM", VIDEO_PROMPT)

    def test_create_task_uses_three_asset_images_and_defaults(self) -> None:
        task_id = self.client.create_task(
            asset_id="asset-uploaded-portrait",
            gender="female",
            reference_image_refs=("asset://asset-ref-2", "asset://asset-ref-3"),
        )

        self.assertEqual(task_id, "ark-task-1")
        payload = self.tasks.payload
        self.assertEqual(payload["ratio"], DEFAULT_RATIO)
        self.assertEqual(payload["duration"], DEFAULT_DURATION)
        self.assertEqual(payload["resolution"], DEFAULT_RESOLUTION)
        self.assertTrue(payload["generate_audio"])
        self.assertFalse(payload["watermark"])

        content = payload["content"]
        self.assertEqual(content[0]["text"], build_video_prompt("female"))
        self.assertTrue(content[0]["text"].startswith("人物性别是 - 女性。\n"))
        self.assertEqual(
            [item["image_url"]["url"] for item in content[1:]],
            [
                "asset://asset-uploaded-portrait",
                "asset://asset-ref-2",
                "asset://asset-ref-3",
            ],
        )
        self.assertTrue(all(item["type"] == "image_url" for item in content[1:]))
        self.assertFalse(any(item["type"] == "video_url" for item in content))

    def test_invalid_options_fall_back_and_gender_is_required(self) -> None:
        self.client.create_task(
            asset_id="asset://portrait",
            gender="male",
            ratio="adaptive",
            duration=-1,
            resolution="1080p",
        )
        self.assertEqual(self.tasks.payload["ratio"], "16:9")
        self.assertEqual(self.tasks.payload["duration"], 30)
        self.assertEqual(self.tasks.payload["resolution"], "480p")
        with self.assertRaises(ValueError):
            self.client.create_task(asset_id="portrait", gender="")

    def test_720p_is_forwarded(self) -> None:
        self.client.create_task(
            asset_id="portrait",
            gender="male",
            resolution="720p",
        )
        self.assertEqual(self.tasks.payload["resolution"], "720p")

    def test_persisted_prompt_and_refs_are_used_when_resuming(self) -> None:
        self.client.create_task(
            asset_id="portrait",
            gender="male",
            prompt="persisted prompt",
            reference_image_refs=["asset://persisted-2", "persisted-3"],
        )
        content = self.tasks.payload["content"]
        self.assertEqual(content[0]["text"], "persisted prompt")
        self.assertEqual(
            [item["image_url"]["url"] for item in content[1:]],
            [
                "asset://portrait",
                "asset://persisted-2",
                "asset://persisted-3",
            ],
        )

    def test_signed_video_url_is_returned_without_truncation(self) -> None:
        url = (
            "https://ark-content.example/video.mp4?"
            "X-Tos-Algorithm=TOS4-HMAC-SHA256&X-Tos-Signature=abc123"
            "&X-Tos-SignedHeaders=host"
        )
        task = SimpleNamespace(content=SimpleNamespace(video_url=url))
        self.assertEqual(VideoClient.extract_video_url(task), url)


if __name__ == "__main__":
    unittest.main()

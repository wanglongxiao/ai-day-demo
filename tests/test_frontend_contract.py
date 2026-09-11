from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class FrontendContractTest(unittest.TestCase):
    def test_gender_cards_replace_select_and_upload_starts_disabled(self) -> None:
        html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count('class="gender-option"'), 2)
        self.assertIn('data-gender="male"', html)
        self.assertIn('data-gender="female"', html)
        self.assertNotIn('id="gender-select"', html)
        self.assertEqual(html.count('class="gender-symbol-glyph"'), 2)
        self.assertIn(">♂</span>", html)
        self.assertIn(">♀</span>", html)
        self.assertIn('id="image-input" type="file" accept="image/*" disabled', html)

    def test_default_language_and_gender_submission(self) -> None:
        html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        i18n = (ROOT / "app" / "static" / "i18n.js").read_text(encoding="utf-8")
        app = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('window.DEFAULT_LANG = "zh-TW"', i18n)
        self.assertIn('window.SUPPORTED_LANGS = ["zh-TW", "en"]', i18n)
        self.assertIn('<option value="zh-TW">繁中</option>', html)
        self.assertIn('<option value="en">EN</option>', html)
        self.assertIn('data-i18n-aria-label="language_label"', html)
        self.assertIn('data-i18n-alt="demo_alt"', html)
        self.assertIn('data-i18n-alt="preview_alt"', html)
        self.assertIn('data-i18n-alt="qr_alt"', html)
        self.assertIn('data-i18n-aria-label="result_video_label"', html)
        self.assertNotIn('"zh-CN": {', i18n)
        self.assertNotIn("ja: {", i18n)
        self.assertIn('fd.append("gender", selectedGender)', app)
        self.assertNotIn('fd.append("template"', app)
        self.assertIn("setInterval(function () { pollTask(taskId); }, 60000)", app)

    def test_demo_is_responsive_tos_image(self) -> None:
        html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="demo-image"', html)
        self.assertIn(
            "https://2026-ai-day.tos-cn-hongkong.bytepluses.com/assets/demo.jpg",
            html,
        )
        self.assertNotIn('id="demo-video"', html)


if __name__ == "__main__":
    unittest.main()

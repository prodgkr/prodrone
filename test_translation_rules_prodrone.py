#!/usr/bin/env python3
"""Offline tests for the Japan/Korea translation-fidelity rules (prodrone PR:
fix/japan-korea-translation).

No network access: GeminiEngine._call_api is monkeypatched to capture the
prompt and return canned output, and requests.post is patched to fail loudly
if anything ever tries real HTTP. Run with a python that has the script's
deps (feedparser, requests, beautifulsoup4, lxml):

    python3 -m unittest -v test_translation_rules_prodrone.py

Background (2026-11-27): prodrone.kr posts rendered source 国内/国産/東京 as
국내/국산/서울 — e.g. content/posts/700m-20250423.md "국내 최초! 서울 상공
700m..." is a Tokyo (Yokota/Tachikawa) story, and 26 titles say "국산 드론"
for 国産 (made in Japan) gear. The translate prompt had no rule keeping
countries/markets/languages/place names as in the source. These tests lock
the new rule into the prompts.
"""

import json
import os
import sys
import unittest
from unittest import mock

# Dummy key so the module import does not sys.exit; never a real credential.
os.environ.setdefault("GEMINI_API_KEY", "dummy-offline-test-key")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import translate_and_post_prodrone as tpp  # noqa: E402


CANNED_JSON = json.dumps(
    {
        "title": "테스트 제목",
        "content": "## 소제목\n\n테스트 본문이다.",
        "excerpt": "테스트 요약문이다.",
        "tldr": "- 요약1이다",
    },
    ensure_ascii=False,
)


class TestTranslationFidelityRules(unittest.TestCase):
    def setUp(self):
        self.captured_prompts = []

        def fake_call_api(_self, prompt, max_tokens=8192, response_mime_type=None):
            self.captured_prompts.append(prompt)
            return CANNED_JSON

        self._api_patch = mock.patch.object(
            tpp.GeminiEngine, "_call_api", fake_call_api
        )
        self._api_patch.start()
        # Any real HTTP attempt must fail the test, not the network.
        self._http_patch = mock.patch.object(
            tpp.requests,
            "post",
            side_effect=AssertionError("offline test must not touch the network"),
        )
        self._http_patch.start()
        self.engine = tpp.GeminiEngine()

    def tearDown(self):
        self._http_patch.stop()
        self._api_patch.stop()

    def test_translate_article_prompt_keeps_japan(self):
        """Rule 5: countries/markets/languages/place names stay as in the source."""
        result = self.engine.translate_article(
            "ソラビジョン、国内初の700m上空ドローン飛行に成功",
            "東京上空で日本製ドローンが飛行し、日本語の解説を提供した。国内の観測は初めて。",
        )
        self.assertEqual(result["title"], "테스트 제목")
        self.assertEqual(len(self.captured_prompts), 1)
        prompt = self.captured_prompts[0]
        # NOTE: 国内 (CJK U+56FD U+5185) and 국산 (CJK U+56FD U+7523) look
        # identical to the Hangul words 국내/국산 but are different code
        # points — that visual identity is exactly the bug class, so the
        # assertions below spell the CJK forms out as escapes.
        for required in (
            "日本→일본",
            "日本語→일본어",
            "日本市場→일본 시장",
            "한국으로 바꾸",
            "현지화하지 말 것",
            "\u56fd\u5185(\uc77c\ubcf8 \uad6d\ub0b4\ub97c \ub73b\ud568)\u2192\"\uc77c\ubcf8 \ub0b4\" / \"\uc77c\ubcf8 \uad6d\ub0b4\"",
            '단독 "국내" 금지',
            "\u56fd\u7523\u2192\"\uc77c\ubcf8\uc0b0\"",
            "\u6771\u4eac\u2192\ub3c4\ucfc4",
        ):
            self.assertIn(required, prompt, f"missing from prompt: {required}")

    def test_translate_article_prompt_keeps_yen(self):
        """Prices stay in yen: 円→엔, no conversion to won."""
        self.engine.translate_article("タイトル", "価格は5,000円。")
        prompt = self.captured_prompts[0]
        self.assertIn("円→엔", prompt)
        self.assertIn("원화로 환산 금지", prompt)

    def test_retranslate_content_prompt_keeps_japan(self):
        """The second-pass (leftover Japanese) prompt needs the same guard."""
        out = self.engine.retranslate_content("日本語の部分が残っている。国内初の飛行。")
        self.assertEqual(out, CANNED_JSON)
        prompt = self.captured_prompts[0]
        for required in ("日本→일본", "日本語→일본어", "日本市場→일본 시장", "\u56fd\u5185\u2192\"\uc77c\ubcf8 \ub0b4\"", "円→엔", "\u56fd\u7523\u2192\"\uc77c\ubcf8\uc0b0\"", "\u6771\u4eac\u2192\ub3c4\ucfc4"):
            self.assertIn(required, prompt, f"missing from retranslate prompt: {required}")


if __name__ == "__main__":
    unittest.main()

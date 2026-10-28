"""LLMTranslator Provider 配置测试。

重点：api_key（token）为空的 Provider 也必须能加载并调用——
内网/网关类服务（如 139 云盘）常不校验 token，空 key 时请求不带
Authorization 头（`_call_api` 内置该分支）。
"""

from unittest.mock import Mock, patch

import pytest

from video_organizer.utils.llm_translator import LLMTranslator


class TestEmptyApiKeyProvider:
    def _translator_with_provider(self, api_key=""):
        cfg = {
            "name": "139",
            "api_url": "http://192.168.2.3:8082/v1/chat/completions",
            "api_key": api_key,
            "model": "qwen3.5-plus",
            "enabled": True,
        }
        return LLMTranslator(providers=[cfg])

    def test_empty_api_key_provider_loaded(self):
        """空 token 的 Provider 必须被加载（_enabled=True），否则 LLM 兜底完全失效。"""
        t = self._translator_with_provider("")
        assert t._enabled is True
        assert len(t.providers) == 1

    def test_empty_api_key_omits_authorization_header(self):
        """空 key 时请求不带 Authorization 头。"""
        t = self._translator_with_provider("")
        with patch("video_organizer.utils.llm_translator.requests.post") as mock_post:
            mock_post.return_value = Mock(
                status_code=200,
                raise_for_status=lambda: None,
                json=lambda: {
                    "choices": [{"finish_reason": "stop", "message": {"content": "x"}}]
                },
            )
            t._call_with_failover([{"role": "user", "content": "hi"}], temperature=0.3)

        sent_headers = mock_post.call_args.kwargs.get("headers", {})
        assert "Authorization" not in sent_headers

    def test_nonempty_api_key_sends_authorization_header(self):
        """有 key 时仍发 Bearer 头（防止回归）。"""
        t = self._translator_with_provider("sk-test-123")
        with patch("video_organizer.utils.llm_translator.requests.post") as mock_post:
            mock_post.return_value = Mock(
                status_code=200,
                raise_for_status=lambda: None,
                json=lambda: {
                    "choices": [{"finish_reason": "stop", "message": {"content": "x"}}]
                },
            )
            t._call_with_failover([{"role": "user", "content": "hi"}], temperature=0.3)

        sent_headers = mock_post.call_args.kwargs.get("headers", {})
        assert sent_headers.get("Authorization") == "Bearer sk-test-123"

    def test_disabled_or_missing_url_still_skipped(self):
        """enabled=False 或 api_url 为空的 Provider 仍不加载（不因放宽 key 而回归）。"""
        t = LLMTranslator(providers=[{"api_url": "", "enabled": True, "model": "m"}])
        assert t.providers == []

        t2 = LLMTranslator(
            providers=[
                {
                    "api_url": "http://x/v1/chat/completions",
                    "enabled": False,
                    "model": "m",
                }
            ]
        )
        assert t2.providers == []

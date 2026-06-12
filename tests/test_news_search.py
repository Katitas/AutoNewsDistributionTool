"""`news_search` モジュールの単体テスト。

実 API は呼ばず、`urllib.request.urlopen` を mock して挙動を検証する。
"""

import io
import json
import urllib.error
from unittest.mock import MagicMock

import pytest

from src.services import news_search
from src.services.news_search import (
    DEFAULT_PROVIDER,
    PROVIDER_DEFAULT_CAPS,
    NewsSearchError,
    SearchHit,
    resolve_provider,
    search_news,
)


def _ok_resp(payload: dict) -> MagicMock:
    """urlopen の正常応答モック（JSON ボディ）を返す。"""
    resp = MagicMock()
    resp.status = 200
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


class TestProviderDefaults:
    """プロバイダ既定値とフォールバック挙動を検証する。"""

    def test_default_provider_is_brave(self) -> None:
        """無料枠の広い Brave がデフォルト。"""
        assert DEFAULT_PROVIDER == "brave"

    def test_brave_cap_higher_than_tavily(self) -> None:
        """Brave 無料枠 (2000/月) は Tavily (1000/月) の2倍 → 上限も大きいはず。"""
        assert PROVIDER_DEFAULT_CAPS["brave"] > PROVIDER_DEFAULT_CAPS["tavily"]

    def test_resolve_provider_unset_returns_default(self, monkeypatch) -> None:
        """env 未設定時はデフォルト（brave）。"""
        monkeypatch.delenv("NEWS_SEARCH_PROVIDER", raising=False)
        assert resolve_provider() == "brave"

    def test_resolve_provider_unknown_falls_back(self, monkeypatch) -> None:
        """未知プロバイダ指定時はデフォルトにフォールバック（エラーは投げない）。"""
        monkeypatch.setenv("NEWS_SEARCH_PROVIDER", "bogus")
        assert resolve_provider() == DEFAULT_PROVIDER

    def test_resolve_provider_explicit_arg_wins(self, monkeypatch) -> None:
        """引数指定が env を上書きする。"""
        monkeypatch.setenv("NEWS_SEARCH_PROVIDER", "brave")
        assert resolve_provider("tavily") == "tavily"


class TestSearchNews:
    """`search_news` のプロバイダ分岐と正規化を検証する。"""

    def test_brave_returns_normalized_hits(self, mocker, monkeypatch) -> None:
        """Brave の応答が SearchHit に正しく正規化されること（デフォルトプロバイダ）。"""
        monkeypatch.setenv("NEWS_SEARCH_API_KEY", "bsa-test")
        monkeypatch.delenv("NEWS_SEARCH_PROVIDER", raising=False)  # default = brave

        payload = {
            "results": [
                {
                    "title": "中古住宅市況回復",
                    "url": "https://example.com/article-1",
                    "description": "Brave からの本文 snippet",
                    "age": "2 hours ago",
                }
            ]
        }
        urlopen_mock = mocker.patch.object(
            news_search.urllib.request, "urlopen", return_value=_ok_resp(payload)
        )

        hits = search_news(query="中古住宅", max_results=5)

        assert len(hits) == 1
        assert hits[0].title == "中古住宅市況回復"
        assert hits[0].url == "https://example.com/article-1"
        assert hits[0].snippet == "Brave からの本文 snippet"
        assert hits[0].published_at == "2 hours ago"

        # X-Subscription-Token ヘッダで Brave を呼んでいることを確認
        called_request = urlopen_mock.call_args.args[0]
        assert called_request.headers.get("X-subscription-token") == "bsa-test"

    def test_tavily_returns_normalized_hits(self, mocker, monkeypatch) -> None:
        """Tavily の応答が SearchHit に正しく正規化されること。"""
        monkeypatch.setenv("NEWS_SEARCH_PROVIDER", "tavily")
        monkeypatch.setenv("NEWS_SEARCH_API_KEY", "tvly-test")

        payload = {
            "results": [
                {
                    "title": "中古住宅市況回復",
                    "url": "https://example.com/article-1",
                    "content": "本文snippet",
                    "published_date": "2026-05-01T09:00:00Z",
                }
            ]
        }
        mocker.patch.object(
            news_search.urllib.request, "urlopen", return_value=_ok_resp(payload)
        )

        hits = search_news(query="中古住宅", max_results=5)

        assert len(hits) == 1
        assert hits[0].title == "中古住宅市況回復"
        assert hits[0].url == "https://example.com/article-1"
        assert hits[0].published_at == "2026-05-01T09:00:00Z"

    def test_missing_api_key_raises(self, monkeypatch) -> None:
        """API キー未設定時は NewsSearchError。"""
        monkeypatch.delenv("NEWS_SEARCH_API_KEY", raising=False)
        with pytest.raises(NewsSearchError, match="API キー未設定"):
            search_news(query="x")

    def test_http_error_propagates_as_news_search_error(self, mocker, monkeypatch) -> None:
        """HTTPError は NewsSearchError に包んで送出される（Tavily 経由で検証）。"""
        monkeypatch.setenv("NEWS_SEARCH_PROVIDER", "tavily")
        monkeypatch.setenv("NEWS_SEARCH_API_KEY", "tvly-test")

        err = urllib.error.HTTPError(
            "https://api.tavily.com/search", 500, "boom", {}, io.BytesIO(b"error body")
        )
        mocker.patch.object(news_search.urllib.request, "urlopen", side_effect=err)

        with pytest.raises(NewsSearchError, match="HTTP error"):
            search_news(query="x")


class TestSearchHit:
    """SearchHit dataclass のシリアライズを検証する。"""

    def test_to_bedrock_dict(self) -> None:
        """`to_bedrock_dict` は published_at が None の場合に空文字を返す。"""
        hit = SearchHit(title="t", url="u", snippet="s", published_at=None)
        d = hit.to_bedrock_dict()
        assert d == {"title": "t", "url": "u", "snippet": "s", "published_at": ""}

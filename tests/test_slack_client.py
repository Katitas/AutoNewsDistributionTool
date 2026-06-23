import io
import json
from unittest.mock import MagicMock

import pytest

from src.models.news import CATEGORIES, ITEMS_PER_CATEGORY, NewsDigest
from src.services import slack_client
from src.services.slack_client import (
    SlackSendError,
    _build_blocks,
    _escape_mrkdwn,
    _group_by_category,
    send_news_by_category,
)


WEBHOOK = "https://hooks.slack.com/services/T/B/X"


def _ok_response() -> MagicMock:
    """`urllib.request.urlopen` の "ok" 応答（HTTP 200, body=b"ok"）を MagicMock で再現する。"""
    resp = MagicMock()
    resp.status = 200
    resp.read.return_value = b"ok"
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


class TestEscapeMrkdwn:
    """Slack mrkdwn 特殊文字エスケープの検証。"""

    def test_escape_special_chars(self) -> None:
        assert _escape_mrkdwn("a < b > c & d") == "a &lt; b &gt; c &amp; d"


class TestGroupByCategory:
    """カテゴリ別グルーピング時の順序保持を検証する。"""

    def test_groups_preserve_order(self, sample_digest: NewsDigest) -> None:
        grouped = _group_by_category(sample_digest)
        # sample_digest は CATEGORIES 順に各カテゴリ ITEMS_PER_CATEGORY 件で構成される。
        assert list(grouped.keys()) == list(CATEGORIES)
        for category in CATEGORIES:
            assert len(grouped[category]) == ITEMS_PER_CATEGORY


class TestBuildBlocks:
    """`_build_blocks` が Block Kit 配列を正しく組み立てることを検証する。"""

    def test_first_block_is_header(self, sample_digest: NewsDigest) -> None:
        items = sample_digest.items[:2]
        blocks = _build_blocks("PropTech", list(items), "2026-05-01")
        assert blocks[0]["type"] == "header"
        assert "PropTech" in blocks[0]["text"]["text"]
        assert "2026-05-01" in blocks[0]["text"]["text"]

    def test_includes_url_and_title_link(self, sample_digest: NewsDigest) -> None:
        items = [sample_digest.items[0]]
        blocks = _build_blocks("PropTech", items, "2026-05-01")
        section_text = blocks[1]["text"]["text"]
        assert items[0].source_url in section_text
        assert "📰 原文を読む" in section_text

    def test_divider_between_items_only(self, sample_digest: NewsDigest) -> None:
        items = sample_digest.items[:2]
        blocks = _build_blocks("PropTech", list(items), "2026-05-01")
        # header + (section + context) * 2 + divider
        types = [b["type"] for b in blocks]
        assert types.count("divider") == 1


class TestSendNewsByCategory:
    """`send_news_by_category` のカテゴリ毎送信と SlackSendError 発火条件を検証する。"""

    def test_one_message_per_category(self, mocker, sample_digest: NewsDigest) -> None:
        mock_urlopen = mocker.patch.object(
            slack_client.urllib.request, "urlopen", return_value=_ok_response()
        )

        sent = send_news_by_category(webhook_url=WEBHOOK, digest=sample_digest, date="2026-05-01")

        # 全カテゴリ分（6カテゴリ）= 6メッセージ
        assert sent == len(CATEGORIES)
        assert mock_urlopen.call_count == len(CATEGORIES)

    def test_payload_is_valid_json(self, mocker, sample_digest: NewsDigest) -> None:
        captured: list[bytes] = []

        def fake_urlopen(req, timeout):  # noqa: ARG001
            captured.append(req.data)
            return _ok_response()

        mocker.patch.object(slack_client.urllib.request, "urlopen", side_effect=fake_urlopen)

        send_news_by_category(webhook_url=WEBHOOK, digest=sample_digest, date="2026-05-01")

        for body in captured:
            payload = json.loads(body.decode("utf-8"))
            assert "blocks" in payload
            assert payload["blocks"][0]["type"] == "header"

    def test_non_ok_response_raises(self, mocker, sample_digest: NewsDigest) -> None:
        bad_resp = MagicMock()
        bad_resp.status = 200
        bad_resp.read.return_value = b"invalid_token"
        bad_resp.__enter__.return_value = bad_resp
        bad_resp.__exit__.return_value = False

        mocker.patch.object(slack_client.urllib.request, "urlopen", return_value=bad_resp)

        with pytest.raises(SlackSendError, match="unexpected response"):
            send_news_by_category(webhook_url=WEBHOOK, digest=sample_digest, date="2026-05-01")

    def test_http_error_raises(self, mocker, sample_digest: NewsDigest) -> None:
        import urllib.error

        err = urllib.error.HTTPError(WEBHOOK, 500, "Server Error", {}, io.BytesIO(b"boom"))
        mocker.patch.object(slack_client.urllib.request, "urlopen", side_effect=err)

        with pytest.raises(SlackSendError, match="HTTP error"):
            send_news_by_category(webhook_url=WEBHOOK, digest=sample_digest, date="2026-05-01")

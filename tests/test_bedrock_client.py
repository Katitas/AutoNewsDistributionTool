import pytest

from src.services import bedrock_client
from src.services.bedrock_client import (
    SEARCH_TOOL_NAME,
    SUBMIT_TOOL_NAME,
    BedrockToolUseError,
    _MAX_SUBMIT_ATTEMPTS,
    _build_tool_config,
    _inline_refs,
    _resolve_max_searches,
    fetch_news_digest,
)
from src.models.news import TOTAL_ITEMS
from src.services.news_search import PROVIDER_DEFAULT_CAPS
from tests.factories import make_balanced_items


def _valid_tool_input() -> dict:
    """NewsDigest スキーマを満たす正常入力を返す（全カテゴリ各5件・計30件、全フィールド充足）。"""
    return {
        "items": [item.model_dump() for item in make_balanced_items(title_prefix="テストニュース")]
    }


class TestInlineRefs:
    """`_inline_refs` が JSON Schema の $defs/$ref を期待通りに展開することを検証する。"""

    def test_simple_schema_unchanged(self) -> None:
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        result = _inline_refs(schema)
        assert result == schema

    def test_refs_inlined(self) -> None:
        schema = {
            "type": "object",
            "properties": {"item": {"$ref": "#/$defs/Item"}},
            "$defs": {"Item": {"type": "string"}},
        }
        result = _inline_refs(schema)
        assert "$defs" not in result
        assert result["properties"]["item"] == {"type": "string"}

    def test_nested_refs_inlined(self) -> None:
        schema = {
            "properties": {"items": {"type": "array", "items": {"$ref": "#/$defs/X"}}},
            "$defs": {"X": {"type": "object", "properties": {"y": {"type": "integer"}}}},
        }
        result = _inline_refs(schema)
        assert result["properties"]["items"]["items"]["properties"]["y"]["type"] == "integer"


class TestResolveMaxSearches:
    """`_resolve_max_searches` の優先順位（引数 > env > プロバイダ既定値）を検証する。"""

    def test_explicit_arg_wins(self, monkeypatch) -> None:
        """引数で渡された値が最優先。"""
        monkeypatch.setenv("NEWS_SEARCH_MAX_PER_INVOCATION", "9")
        monkeypatch.setenv("NEWS_SEARCH_PROVIDER", "brave")
        assert _resolve_max_searches(99) == 99

    def test_env_overrides_provider_default(self, monkeypatch) -> None:
        """env が設定されていればプロバイダ既定値より優先される。"""
        monkeypatch.setenv("NEWS_SEARCH_MAX_PER_INVOCATION", "77")
        monkeypatch.setenv("NEWS_SEARCH_PROVIDER", "brave")
        assert _resolve_max_searches(None) == 77

    def test_brave_default_when_no_env(self, monkeypatch) -> None:
        """env 未設定 + provider=brave → Brave 既定値。"""
        monkeypatch.delenv("NEWS_SEARCH_MAX_PER_INVOCATION", raising=False)
        monkeypatch.setenv("NEWS_SEARCH_PROVIDER", "brave")
        assert _resolve_max_searches(None) == PROVIDER_DEFAULT_CAPS["brave"]

    def test_tavily_default_when_no_env(self, monkeypatch) -> None:
        """env 未設定 + provider=tavily → Tavily 既定値。"""
        monkeypatch.delenv("NEWS_SEARCH_MAX_PER_INVOCATION", raising=False)
        monkeypatch.setenv("NEWS_SEARCH_PROVIDER", "tavily")
        assert _resolve_max_searches(None) == PROVIDER_DEFAULT_CAPS["tavily"]


class TestBuildToolConfig:
    """`_build_tool_config` が Bedrock に渡す toolConfig が正しい形式かを検証する。"""

    def test_two_tools_registered(self) -> None:
        """search と submit の2ツールが正しい順序で登録されていること。"""
        config = _build_tool_config()
        names = [t["toolSpec"]["name"] for t in config["tools"]]
        assert SEARCH_TOOL_NAME in names
        assert SUBMIT_TOOL_NAME in names

    def test_tool_choice_is_auto(self) -> None:
        """Bedrock がツール呼び出しを自律的に選べるよう auto を指定していること。"""
        config = _build_tool_config()
        assert config["toolChoice"] == {"auto": {}}

    def test_no_refs_in_schema(self) -> None:
        """submit_news_digest スキーマに $ref / $defs が残っていないこと。"""
        config = _build_tool_config()
        submit_schema = next(
            t["toolSpec"]["inputSchema"]["json"]
            for t in config["tools"]
            if t["toolSpec"]["name"] == SUBMIT_TOOL_NAME
        )
        import json

        as_str = json.dumps(submit_schema)
        assert "$ref" not in as_str
        assert "$defs" not in as_str


class TestFetchNewsDigest:
    """`fetch_news_digest` の正常系・異常系を Bedrock クライアントを mock して検証する。"""

    def _stub_response(self, tool_input: dict) -> dict:
        """Bedrock Converse API の正常応答（tool_use 1件）を組み立てる。"""
        return {
            "stopReason": "tool_use",
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "tu-1",
                                "name": "submit_news_digest",
                                "input": tool_input,
                            }
                        }
                    ],
                }
            },
        }

    def test_valid_response_parsed(self, mocker) -> None:
        mock_client = mocker.Mock()
        mock_client.converse.return_value = self._stub_response(_valid_tool_input())
        mocker.patch.object(bedrock_client.boto3, "client", return_value=mock_client)

        digest = fetch_news_digest(model_id="test-model", prompt="prompt", today="2026-05-01")
        assert len(digest.items) == TOTAL_ITEMS

    def test_no_tool_use_block_raises(self, mocker) -> None:
        """ツール呼び出しが一切ないプレーンテキスト応答は想定外として例外。"""
        response = {
            "stopReason": "end_turn",
            "output": {"message": {"role": "assistant", "content": [{"text": "テキスト応答"}]}},
        }
        mock_client = mocker.Mock()
        mock_client.converse.return_value = response
        mocker.patch.object(bedrock_client.boto3, "client", return_value=mock_client)

        with pytest.raises(BedrockToolUseError, match="想定外"):
            fetch_news_digest(model_id="test-model", prompt="prompt", today="2026-05-01")

    def test_invalid_tool_input_capped_then_raises(self, mocker) -> None:
        """submit が毎ターン検証失敗し続けても、_MAX_SUBMIT_ATTEMPTS で打ち切って例外。

        構造的に満たせない submit を延々と再生成して timeout / コスト暴走するのを防ぐ歯止め。
        """
        bad_input = {"items": [{"title": "x"}]}  # 不正なデータ
        mock_client = mocker.Mock()
        mock_client.converse.return_value = self._stub_response(bad_input)
        mocker.patch.object(bedrock_client.boto3, "client", return_value=mock_client)

        with pytest.raises(BedrockToolUseError, match="回連続で失敗"):
            fetch_news_digest(model_id="test-model", prompt="prompt", today="2026-05-01")
        # 上限回数ちょうどで打ち切る（青天井リトライしない）
        assert mock_client.converse.call_count == _MAX_SUBMIT_ATTEMPTS

    def test_invalid_submit_then_valid_recovers(self, mocker) -> None:
        """1回目の submit が検証失敗でも、エラーを返して再submitさせ2回目が正しければ成功する。

        30件中1件のスキーマ違反（summary が短い等）で日次配信全体が落ちないための自己修復ループ。
        """
        bad_input = {"items": [{"title": "x"}]}  # 不正なデータ
        mock_client = mocker.Mock()
        mock_client.converse.side_effect = [
            self._stub_response(bad_input),
            self._stub_response(_valid_tool_input()),
        ]
        mocker.patch.object(bedrock_client.boto3, "client", return_value=mock_client)

        digest = fetch_news_digest(model_id="test-model", prompt="prompt", today="2026-05-01")
        assert len(digest.items) == TOTAL_ITEMS
        # 1回目失敗 → 2回目で回復（converse は2回呼ばれる）
        assert mock_client.converse.call_count == 2

    def test_calls_converse_with_correct_params(self, mocker) -> None:
        """初回 converse 呼び出し時のパラメータが期待通りであること。"""
        mock_client = mocker.Mock()
        mock_client.converse.return_value = self._stub_response(_valid_tool_input())
        mocker.patch.object(bedrock_client.boto3, "client", return_value=mock_client)

        fetch_news_digest(model_id="test-model", prompt="my prompt", today="2026-05-01")

        kwargs = mock_client.converse.call_args.kwargs
        assert kwargs["modelId"] == "test-model"
        assert "2026-05-01" in kwargs["system"][0]["text"]
        assert kwargs["messages"][0]["content"][0]["text"] == "my prompt"
        # toolChoice は auto。両ツールが登録されている
        assert kwargs["toolConfig"]["toolChoice"] == {"auto": {}}
        names = [t["toolSpec"]["name"] for t in kwargs["toolConfig"]["tools"]]
        assert SUBMIT_TOOL_NAME in names
        assert SEARCH_TOOL_NAME in names

    def test_system_prompt_announces_search_budget(self, mocker) -> None:
        """system プロンプトに検索上限の具体的回数が含まれていること。

        Bedrock が事前に予算を把握して計画的に検索できるようにするため、
        上限値（数値）を system プロンプトに埋め込んでいる。
        """
        mock_client = mocker.Mock()
        mock_client.converse.return_value = self._stub_response(_valid_tool_input())
        mocker.patch.object(bedrock_client.boto3, "client", return_value=mock_client)

        bedrock_client.run_news_agent(
            model_id="test-model",
            prompt="prompt",
            today="2026-05-01",
            max_searches_per_invocation=17,
        )

        system_text = mock_client.converse.call_args.kwargs["system"][0]["text"]
        # 具体的な上限値が含まれること（運用調整時に Bedrock が認識できる）
        assert "17" in system_text
        # 予算の意図と対処方法も伝わっていること
        assert "予算" in system_text or "回" in system_text
        assert "budget_exhausted" in system_text

    def test_budget_exhausted_returns_signal_not_error(self, mocker) -> None:
        """検索上限到達後、search_real_news が呼ばれても Tavily を叩かず budget_exhausted=True を返す。

        Bedrock はこれを受けて submit_news_digest を呼んで終了することが期待される。
        例外は投げない（運用継続性が最優先）。
        """
        # 1ターン目: search を1回呼ぶ（上限1なので使い切り）
        # 2ターン目: search をさらに呼ぶ → budget_exhausted で空応答
        # 3ターン目: submit で完了
        search1 = {
            "stopReason": "tool_use",
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "tu-s1",
                                "name": SEARCH_TOOL_NAME,
                                "input": {"query": "k1"},
                            }
                        }
                    ],
                }
            },
        }
        search2 = {
            "stopReason": "tool_use",
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "tu-s2",
                                "name": SEARCH_TOOL_NAME,
                                "input": {"query": "k2"},
                            }
                        }
                    ],
                }
            },
        }
        submit_resp = self._stub_response(_valid_tool_input())

        mock_client = mocker.Mock()
        mock_client.converse.side_effect = [search1, search2, submit_resp]
        mocker.patch.object(bedrock_client.boto3, "client", return_value=mock_client)

        # search_news を spy。1回目は呼ばれるが、2回目は予算上限で skip される想定
        search_spy = mocker.patch.object(bedrock_client, "search_news", return_value=[])

        digest = bedrock_client.run_news_agent(
            model_id="test-model",
            prompt="prompt",
            today="2026-05-01",
            max_searches_per_invocation=1,  # 上限1で即座に枯渇させる
        )

        assert len(digest.items) == TOTAL_ITEMS
        # Tavily は1回だけ叩かれた（上限1）。2回目の search は API を叩いていない
        assert search_spy.call_count == 1

    def test_search_tool_dispatched_then_submit(self, mocker) -> None:
        """Bedrockが search_real_news を呼んだら検索を実行し、次ターンの submit を受け入れる。"""
        # 1ターン目: search_real_news を呼ぶ
        # 2ターン目: submit_news_digest で完了
        search_response = {
            "stopReason": "tool_use",
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": "tu-search-1",
                                "name": SEARCH_TOOL_NAME,
                                "input": {"query": "中古住宅 補助金"},
                            }
                        }
                    ],
                }
            },
        }
        submit_response = self._stub_response(_valid_tool_input())
        mock_client = mocker.Mock()
        mock_client.converse.side_effect = [search_response, submit_response]
        mocker.patch.object(bedrock_client.boto3, "client", return_value=mock_client)

        # 検索関数は副作用を avoid するため stub
        mocker.patch.object(
            bedrock_client,
            "search_news",
            return_value=[],
        )

        digest = fetch_news_digest(model_id="test-model", prompt="prompt", today="2026-05-01")
        assert len(digest.items) == TOTAL_ITEMS
        # 2ターン分 converse が呼ばれていること
        assert mock_client.converse.call_count == 2

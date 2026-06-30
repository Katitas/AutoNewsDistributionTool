from src.models.news import NewsDigest
from src.services.url_normalizer import apply_url_rewrites, normalize_url
from tests.factories import make_digest


def _digest(urls: list[str]) -> NewsDigest:
    """先頭から urls を割り当てた完全な NewsDigest（計30件・全カテゴリ均衡）を作る。

    urls の不足分は書き換え対象外の example.com URL で補完される。
    """
    return make_digest(source_urls=urls)


class TestNormalizeUrl:
    """`normalize_url` のホスト書き換え挙動を検証する。"""

    def test_rewrites_housenews_host(self) -> None:
        """www 無しの housenews.jp はホストのみ書き換わり、パス・クエリは保持される。"""
        assert (
            normalize_url("https://housenews.jp/articles/123?ref=x")
            == "https://www.housenews.jp/articles/123?ref=x"
        )

    def test_rewrites_dreamnews_host(self) -> None:
        """www 無しの dreamnews.jp はホストのみ書き換わり、パス・クエリは保持される。"""
        assert (
            normalize_url("https://dreamnews.jp/press/0000123456/?x=1")
            == "https://www.dreamnews.jp/press/0000123456/?x=1"
        )

    def test_already_www_is_unchanged(self) -> None:
        """既に www 付きの正しいホストは変更されない。"""
        url = "https://www.housenews.jp/articles/123"
        assert normalize_url(url) == url

    def test_unknown_host_is_unchanged(self) -> None:
        """書き換え表にないホストは一切いじらない。"""
        url = "https://example.com/news/p1"
        assert normalize_url(url) == url

    def test_path_case_is_preserved(self) -> None:
        """パスの大文字小文字は保持する（nikkei の記事コード等を壊さない）。"""
        url = "https://www.nikkei.com/article/DGXZQOUF061RL0W6A600C2000000"
        assert normalize_url(url) == url


class TestApplyUrlRewrites:
    """`apply_url_rewrites` の digest 単位の書き換えを検証する。"""

    def test_rewrites_only_matching_item(self) -> None:
        """対象ホストの item のみ source_url が書き換わり、他は不変。"""
        digest = _digest(
            [
                "https://housenews.jp/a/1",
                "https://example.com/news/p2",
            ]
        )
        result = apply_url_rewrites(digest)

        # 先頭（housenews）のみ www 補正。2件目以降は書き換え対象外なので不変。
        assert result.items[0].source_url == "https://www.housenews.jp/a/1"
        assert result.items[1].source_url == "https://example.com/news/p2"
        assert all(
            "housenews.jp" not in item.source_url or item.source_url.startswith("https://www.")
            for item in result.items
        )

    def test_no_change_returns_same_instance(self) -> None:
        """書き換え対象が無ければ同一インスタンスをそのまま返す。"""
        # source_urls 未指定 → 全件 example.com（書き換え対象なし）。
        digest = _digest([])
        assert apply_url_rewrites(digest) is digest

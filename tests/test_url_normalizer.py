from src.models.news import NewsDigest, NewsItem
from src.services.url_normalizer import apply_url_rewrites, normalize_url


def _item(source_url: str, *, title: str = "テスト見出し") -> NewsItem:
    """検証用の最小 NewsItem（各フィールドの min_length 制約を満たす）。"""
    return NewsItem(
        title=title,
        summary="あ" * 250,
        category="PropTech",
        katitas_relevance="カチタス業務に役立つ可能性があるテスト用コメント本文。" * 2,
        source_url=source_url,
    )


def _digest(urls: list[str]) -> NewsDigest:
    """URL を差し替えた 5 件の NewsDigest を作る（min/max=5 制約のため必ず 5 件）。"""
    return NewsDigest(items=[_item(u, title=f"ニュース {i}") for i, u in enumerate(urls)])


class TestNormalizeUrl:
    """`normalize_url` のホスト書き換え挙動を検証する。"""

    def test_rewrites_housenews_host(self) -> None:
        """www 無しの housenews.jp はホストのみ書き換わり、パス・クエリは保持される。"""
        assert (
            normalize_url("https://housenews.jp/articles/123?ref=x")
            == "https://www.housenews.jp/articles/123?ref=x"
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
                "https://example.com/news/l1",
                "https://example.com/news/l2",
                "https://example.com/news/m1",
            ]
        )
        result = apply_url_rewrites(digest)

        assert result.items[0].source_url == "https://www.housenews.jp/a/1"
        assert [i.source_url for i in result.items[1:]] == [
            "https://example.com/news/p2",
            "https://example.com/news/l1",
            "https://example.com/news/l2",
            "https://example.com/news/m1",
        ]

    def test_no_change_returns_same_instance(self) -> None:
        """書き換え対象が無ければ同一インスタンスをそのまま返す。"""
        digest = _digest([f"https://example.com/news/{i}" for i in range(5)])
        assert apply_url_rewrites(digest) is digest

import pytest
from pydantic import ValidationError

from src.models.news import (
    CATEGORIES,
    ITEMS_PER_CATEGORY,
    MAX_PER_CATEGORY,
    TARGET_TOTAL_ITEMS,
    NewsDigest,
    NewsItem,
    build_coverage_notice,
    normalize_digest,
)
from tests.factories import make_balanced_items, make_items


def _valid_item_kwargs() -> dict:
    return {
        "title": "テストニュース",
        "summary": "あ" * 90,
        "category": "PropTech",
        "katitas_relevance": "業務に役立つ示唆。" * 5,
        "source_url": "https://example.com/article/1",
    }


class TestNewsItem:
    def test_valid(self) -> None:
        item = NewsItem(**_valid_item_kwargs())
        assert item.category == "PropTech"

    def test_summary_too_short_rejected(self) -> None:
        kwargs = _valid_item_kwargs()
        kwargs["summary"] = "短い要約"
        with pytest.raises(ValidationError):
            NewsItem(**kwargs)

    def test_summary_too_long_rejected(self) -> None:
        kwargs = _valid_item_kwargs()
        kwargs["summary"] = "あ" * 121
        with pytest.raises(ValidationError):
            NewsItem(**kwargs)

    def test_invalid_category_rejected(self) -> None:
        kwargs = _valid_item_kwargs()
        kwargs["category"] = "スポーツ"  # 旧カテゴリ
        with pytest.raises(ValidationError):
            NewsItem(**kwargs)

    def test_source_url_required(self) -> None:
        kwargs = _valid_item_kwargs()
        del kwargs["source_url"]
        with pytest.raises(ValidationError):
            NewsItem(**kwargs)

    def test_katitas_relevance_required(self) -> None:
        kwargs = _valid_item_kwargs()
        kwargs["katitas_relevance"] = "短い"
        with pytest.raises(ValidationError):
            NewsItem(**kwargs)


class TestNewsDigest:
    def test_balanced_digest_accepted(self) -> None:
        """全カテゴリ各5件・計30件は受理される。"""
        digest = NewsDigest(items=make_balanced_items())
        assert len(digest.items) == ITEMS_PER_CATEGORY * len(CATEGORIES)

    def test_fewer_than_target_accepted(self) -> None:
        """計30件未満でも受理される（関連ニュース不足を許容）。"""
        items = make_items({"PropTech": 3, "企業動向": 2})
        digest = NewsDigest(items=items)
        assert len(digest.items) == 5

    def test_unbalanced_accepted(self) -> None:
        """カテゴリ偏りでも受理される（截断は normalize_digest の責務）。"""
        items = make_items({"PropTech": 7})
        digest = NewsDigest(items=items)
        assert len(digest.items) == 7

    def test_empty_rejected(self) -> None:
        """0件（空配信）は min_length=1 で拒否される。"""
        with pytest.raises(ValidationError):
            NewsDigest(items=[])


class TestNormalizeDigest:
    def test_caps_per_category(self) -> None:
        """1カテゴリ9件は MAX_PER_CATEGORY(8) 件に截断される。"""
        digest = NewsDigest(items=make_items({"PropTech": 9}))
        result = normalize_digest(digest)
        assert len(result.items) == MAX_PER_CATEGORY

    def test_caps_total(self) -> None:
        """各≤8でも合計が TARGET_TOTAL_ITEMS を超える場合は総数で截断される。"""
        # 6カテゴリ各8件=48件 → 30件に截断
        digest = NewsDigest(items=make_items({c: 8 for c in CATEGORIES}))
        result = normalize_digest(digest)
        assert len(result.items) == TARGET_TOTAL_ITEMS

    def test_keeps_within_limits_unchanged(self) -> None:
        """上限内（各5件・計30件）はそのまま保持される。"""
        digest = NewsDigest(items=make_balanced_items())
        result = normalize_digest(digest)
        assert len(result.items) == TARGET_TOTAL_ITEMS


class TestBuildCoverageNotice:
    def test_full_coverage_returns_none(self) -> None:
        """全カテゴリ5件以上なら通知なし（None）。"""
        assert build_coverage_notice(NewsDigest(items=make_balanced_items())) is None

    def test_redistributed_notice_when_total_met(self) -> None:
        """計30件だが一部カテゴリ<5 → 補填文面。不足カテゴリ名と件数を含む。"""
        # PropTech 8, 企業動向 8, 法規制・政策 8, マーケット・価格動向 3, 海外不動産 3 = 30件
        counts = {
            "PropTech": 8, "企業動向": 8, "法規制・政策": 8,
            "マーケット・価格動向": 3, "海外不動産": 3,
        }
        notice = build_coverage_notice(NewsDigest(items=make_items(counts)))
        assert notice is not None
        assert "補填" in notice
        assert "マーケット・価格動向(3件)" in notice
        assert "海外不動産(3件)" in notice

    def test_shortfall_notice_when_total_unmet(self) -> None:
        """計30件未満 → 不足文面。総件数と不足カテゴリを含む。"""
        counts = {"PropTech": 3, "企業動向": 2}
        notice = build_coverage_notice(NewsDigest(items=make_items(counts)))
        assert notice is not None
        assert "満たせませんでした" in notice
        assert "計5件" in notice
        assert "PropTech(3件)" in notice

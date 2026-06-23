from src.models.news import TOTAL_ITEMS, NewsDigest
from src.services.html_renderer import (
    CATEGORY_COLORS,
    CATEGORY_TEXT_COLORS,
    render_news_email,
)


class TestRenderNewsEmail:
    def test_contains_date_and_count(self, sample_digest: NewsDigest) -> None:
        html = render_news_email(digest=sample_digest, date="2026-05-01")
        assert "2026-05-01" in html
        assert str(TOTAL_ITEMS) in html  # items count（計30件）

    def test_contains_all_titles(self, sample_digest: NewsDigest) -> None:
        html = render_news_email(digest=sample_digest, date="2026-05-01")
        for item in sample_digest.items:
            assert item.title in html

    def test_contains_all_source_urls(self, sample_digest: NewsDigest) -> None:
        html = render_news_email(digest=sample_digest, date="2026-05-01")
        for item in sample_digest.items:
            assert item.source_url in html

    def test_contains_all_katitas_relevance(self, sample_digest: NewsDigest) -> None:
        html = render_news_email(digest=sample_digest, date="2026-05-01")
        for item in sample_digest.items:
            assert item.katitas_relevance in html

    def test_uses_category_colors(self, sample_digest: NewsDigest) -> None:
        html = render_news_email(digest=sample_digest, date="2026-05-01")
        # サンプルにある全カテゴリの色が使われる
        for category in {item.category for item in sample_digest.items}:
            assert CATEGORY_COLORS[category] in html
            assert CATEGORY_TEXT_COLORS[category] in html

    def test_html_escapes_dangerous_input(self) -> None:
        from tests.factories import make_digest

        # 全件のタイトルに XSS ペイロードを仕込んだ完全な digest（計30件・全カテゴリ均衡）。
        digest = make_digest(title="<script>alert(1)</script>")
        html = render_news_email(digest=digest, date="2026-05-01")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

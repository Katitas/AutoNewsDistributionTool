from src.models.news import NewsDigest
from src.services.html_renderer import (
    CATEGORY_COLORS,
    CATEGORY_TEXT_COLORS,
    render_news_email,
)


class TestRenderNewsEmail:
    def test_contains_date_and_count(self, sample_digest: NewsDigest) -> None:
        html = render_news_email(digest=sample_digest, date="2026-05-01")
        assert "2026-05-01" in html
        assert "5" in html  # items count

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
        from src.models.news import NewsDigest, NewsItem

        items = [
            NewsItem(
                title="<script>alert(1)</script>",
                summary="あ" * 250,
                category="PropTech",
                katitas_relevance="業務に役立つ。" * 6,
                source_url="https://example.com/x",
            )
            for _ in range(5)
        ]
        digest = NewsDigest(items=items)
        html = render_news_email(digest=digest, date="2026-05-01")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

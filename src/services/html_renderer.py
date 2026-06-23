from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.models.news import NewsDigest

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_TEMPLATE_FILE = "news_email.html"

CATEGORY_COLORS: dict[str, str] = {
    "PropTech": "#e3eef9",
    "企業動向": "#e1f3e9",
    "法規制・政策": "#ede4f5",
    "マーケット・価格動向": "#fdebd9",
    "海外不動産": "#d9eff0",
    "リフォーム関連": "#fbe5e0",
}

CATEGORY_TEXT_COLORS: dict[str, str] = {
    "PropTech": "#1a4d80",
    "企業動向": "#1d6a3a",
    "法規制・政策": "#5e3a85",
    "マーケット・価格動向": "#9a5a1a",
    "海外不動産": "#1d6f70",
    "リフォーム関連": "#a04030",
}


def _build_env() -> Environment:
    """Jinja2 環境を構築する。

    autoescape を有効にしてXSS対策とする。Bedrock 出力はバリデーション済みだが、
    summary や title に意図せず HTML/JSが混入した場合にも安全に表示できるよう保険として有効化。
    """
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=False,
        lstrip_blocks=False,
    )


def render_news_email(*, digest: NewsDigest, date: str) -> str:
    """Jinja2 で HTML メール本文をレンダリングする。

    Args:
        digest: NewsDigest（全6カテゴリ各5件・計30件のニュース）。
        date: 配信対象日（YYYY-MM-DD）。HTML タイトルとヘッダに表示。

    Returns:
        HTML文字列（SES の Body.Html.Data へそのまま渡せる形式）。
    """
    env = _build_env()
    template = env.get_template(_TEMPLATE_FILE)
    return template.render(
        date=date,
        items=digest.items,
        category_colors=CATEGORY_COLORS,
        category_text_colors=CATEGORY_TEXT_COLORS,
    )

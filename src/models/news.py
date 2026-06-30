from collections import Counter
from typing import Literal, get_args

from pydantic import BaseModel, Field


NewsCategory = Literal[
    "PropTech",
    "企業動向",
    "法規制・政策",
    "マーケット・価格動向",
    "海外不動産",
    "リフォーム関連",
]

# 1カテゴリあたりの配信件数。全カテゴリ均等に ITEMS_PER_CATEGORY 件ずつ選ぶ。
ITEMS_PER_CATEGORY = 5
# 1カテゴリの配信上限。補填時の偏りを防ぐためのハード上限（normalize_digest が截断）。
MAX_PER_CATEGORY = 8
# 対象カテゴリ一覧（NewsCategory Literal から動的取得。分類の増減はここに追従する）。
CATEGORIES: tuple[str, ...] = get_args(NewsCategory)
# 1日あたりの目標総件数 = カテゴリ数 × 各カテゴリ目標件数（現状 6 × 5 = 30）。
# ハード上限ではなく目標値。実際の截断は後続タスクの normalize_digest が行う。
TARGET_TOTAL_ITEMS = ITEMS_PER_CATEGORY * len(CATEGORIES)


class NewsItem(BaseModel):
    title: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="ニュース見出し。事実を端的に伝える。煽り表現は避ける。",
    )
    summary: str = Field(
        ...,
        min_length=40,
        max_length=120,
        description=(
            "ニュースの簡潔な要約。2〜3文・40〜120字程度で、何が起きたか・関与する主体・"
            "核心となる影響だけを端的にまとめる。Slack/メールで2〜3行に収めるための制約であり、"
            "冗長な背景説明や経緯の列挙は避け、続きは原文リンクに委ねる。"
        ),
    )
    category: NewsCategory = Field(
        ...,
        description="ニュースのカテゴリ。",
    )
    katitas_relevance: str = Field(
        ...,
        min_length=40,
        max_length=300,
        description="カチタスの業務プロセス（中古住宅再生事業、実需向け戸建て）に役立つかのコメント・サジェスチョン。",
    )
    source_url: str = Field(
        ...,
        min_length=8,
        max_length=2000,
        description=(
            "ニュースの原文記事のURL。http:// または https:// で始まる絶対URL。"
            "**そのニュースを報じている個別記事ページのURLでなければならない。**"
            "トップページ・カテゴリ一覧ページ・タグページ・検索結果ページ・"
            "組織のコーポレートサイトなど、当該ニュースを直接報じていないページのURLは禁止。"
            "URL は捏造してはならない。記事URLを特定できないニュースはそもそも選ばないこと。"
        ),
    )


class NewsDigest(BaseModel):
    items: list[NewsItem] = Field(
        ...,
        min_length=1,
        description=(
            "本日の不動産ニュース。実需中古住宅事業に内容的に関連するもののみ。"
            f"目標は全{len(CATEGORIES)}カテゴリ各{ITEMS_PER_CATEGORY}件・計{TARGET_TOTAL_ITEMS}件だが、"
            "関連ニュースが不足するカテゴリは少なくてよい（0件も可）。"
            "マンション・投資用は除外。"
        ),
    )


def normalize_digest(digest: NewsDigest) -> NewsDigest:
    """配信前の件数規整。各カテゴリを最大 MAX_PER_CATEGORY 件、
    総件数を最大 TARGET_TOTAL_ITEMS 件に截断する。

    元の items 出現順を保ちつつ1パスで走査し、カテゴリ別カウントが上限未満かつ
    総数が上限未満の item のみ採用する。モデルが上限を超えて submit しても
    未配信にせず決定的に整形する兜底処理。
    """
    counts: dict[str, int] = {category: 0 for category in CATEGORIES}
    result: list[NewsItem] = []
    for item in digest.items:
        if len(result) >= TARGET_TOTAL_ITEMS:
            break
        if counts.get(item.category, 0) < MAX_PER_CATEGORY:
            result.append(item)
            counts[item.category] = counts.get(item.category, 0) + 1
    return NewsDigest(items=result)


def build_coverage_notice(digest: NewsDigest) -> str | None:
    """規整後の digest を受け取り、ITEMS_PER_CATEGORY 件未満のカテゴリを集計して
    不足通知文を返す。全カテゴリが目標件数を満たす場合は None。

    総件数が TARGET_TOTAL_ITEMS 以上なら「補填したが偏りあり」、
    未満なら「全体で不足」の文面を返す。配信する実際の件数と一致させるため、
    必ず normalize_digest 適用後の digest に対して呼ぶこと。
    """
    counts = Counter(item.category for item in digest.items)
    short = [
        (category, counts.get(category, 0))
        for category in CATEGORIES
        if counts.get(category, 0) < ITEMS_PER_CATEGORY
    ]
    if not short:
        return None
    detail = " / ".join(f"{category}({n}件)" for category, n in short)
    total = len(digest.items)
    if total >= TARGET_TOTAL_ITEMS:
        return (
            f"本日は一部カテゴリで関連ニュースが規定の{ITEMS_PER_CATEGORY}件に届かず、"
            f"他カテゴリで補填しています。不足カテゴリ: {detail}"
        )
    return (
        f"本日は関連ニュースが計{total}件にとどまり、"
        f"各カテゴリ{ITEMS_PER_CATEGORY}件（計{TARGET_TOTAL_ITEMS}件）を満たせませんでした。"
        f"不足カテゴリ: {detail}"
    )

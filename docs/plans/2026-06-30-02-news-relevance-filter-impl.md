# ニュース関連性フィルタ＋補填＋不足通知 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** キーワード取得後のニュースに内容ベースの関連性フィルタを掛け、カテゴリ不足時は他カテゴリで補填（各≤8・計≤30）し、不足カテゴリをメール・Slackで通知する。

**Architecture:** 関連性判定はプロンプト（モデル駆動）。件数の上限規整 `normalize_digest` と不足通知 `build_coverage_notice` はコード駆動で決定的に行う。Pydantic 検証は「自動修復不可な制約（フィールド形式・非空）」だけに縮小し、件数上限はコード截断に委ねて未配信を防ぐ。

**Tech Stack:** Python 3.13 / Pydantic v2 / Jinja2 / pytest / pytest-mock / boto3(Bedrock Converse)

**設計書:** `docs/plans/2026-06-30-01-news-relevance-filter.md`

## Global Constraints

- 会話は中国語、**コード/ファイル/コメント/ドキュメントは日本語**で記述する。
- master ブランチに直接コミットする（単独運用。ブランチ不要）。
- 依存パッケージのバージョンは追加しない（本変更は新規依存なし）。
- 検証コマンドは `pytest`（リポジトリルートで実行）。
- カテゴリ定数: `CATEGORIES`（6カテゴリ）/ `ITEMS_PER_CATEGORY = 5`（目標・通知閾値）/ `MAX_PER_CATEGORY = 8`（上限）/ `TARGET_TOTAL_ITEMS = 30`（目標総数・截断上限）。
- 旧定数 `TOTAL_ITEMS` は `TARGET_TOTAL_ITEMS` に改名し、別名は残さない。

---

### Task 1: 定数 `TOTAL_ITEMS` → `TARGET_TOTAL_ITEMS` 改名（純機械・挙動不変）

**Files:**
- Modify: `src/models/news.py`
- Modify: `src/services/bedrock_client.py`
- Modify: `tests/factories.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_bedrock_client.py`
- Modify: `tests/test_html_renderer.py`

**Interfaces:**
- Produces: 定数 `TARGET_TOTAL_ITEMS: int = 30`（旧 `TOTAL_ITEMS` の置換）。値・挙動は不変。

- [ ] **Step 1: 全参照を一括改名**

`src/models/news.py` の定義行と全ファイルの参照を `TOTAL_ITEMS` → `TARGET_TOTAL_ITEMS` に置換する。対象は上記6ファイル。`news.py` の定義は:

```python
# 1日あたりの目標総件数 = カテゴリ数 × 各カテゴリ目標件数（現状 6 × 5 = 30）。
# ハード上限ではなく目標値。実際の截断は normalize_digest（Task 3）が行う。
TARGET_TOTAL_ITEMS = ITEMS_PER_CATEGORY * len(CATEGORIES)
```

`tests/test_bedrock_client.py` の `from src.models.news import TOTAL_ITEMS` と4箇所の `== TOTAL_ITEMS`、`tests/test_html_renderer.py` の `import` と `str(TOTAL_ITEMS)`、`tests/factories.py` の import/利用、`tests/test_models.py` の import/利用、`src/services/bedrock_client.py` の import と全 f-string 参照を漏れなく置換する。

- [ ] **Step 2: 全テストが緑のままを確認**

Run: `pytest -q`
Expected: PASS（改名のみで挙動不変。全テスト緑）

- [ ] **Step 3: Commit**

```bash
git add src/models/news.py src/services/bedrock_client.py tests/
git commit -m "refactor(*): rename TOTAL_ITEMS to TARGET_TOTAL_ITEMS"
```

---

### Task 2: モデル制約の緩和（計30未満・カテゴリ偏りを受理、空のみ拒否）

**Files:**
- Modify: `src/models/news.py`
- Modify: `tests/test_models.py`

**Interfaces:**
- Consumes: `TARGET_TOTAL_ITEMS`（Task 1）
- Produces: `MAX_PER_CATEGORY: int = 8`。`NewsDigest`（`items` は `min_length=1` のみ、上限制約・均衡検証なし）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_models.py` の `class TestNewsDigest` を以下へ差し替える（旧 `test_fewer_than_total_rejected` / `test_more_than_total_rejected` / `test_unbalanced_category_rejected` を削除し、下記を追加）。`make_balanced_items` の import は維持、`make_items` を追加 import する。

```python
from tests.factories import make_balanced_items, make_items


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
```

- [ ] **Step 2: テストが失敗するのを確認**

Run: `pytest tests/test_models.py::TestNewsDigest -v`
Expected: FAIL（`test_fewer_than_target_accepted` 等が現行 `min_length=TARGET_TOTAL_ITEMS` と均衡検証で弾かれる。`make_items` 未定義で ImportError も発生しうる → Task 内 Step 3/4 で解消）

- [ ] **Step 3: `factories.py` に `make_items` を追加**

`tests/factories.py` に追加:

```python
def make_items(counts: dict[str, int]) -> list[NewsItem]:
    """カテゴリ→件数の指定で任意構成の NewsItem 群を生成する（不足・偏り・超過テスト用）。"""
    items: list[NewsItem] = []
    for category, n in counts.items():
        for i in range(n):
            items.append(
                make_item(category=category, source_url=f"https://example.com/{category}/{i}")
            )
    return items
```

- [ ] **Step 4: モデルを緩和する**

`src/models/news.py` を編集:

1. 定数に追加（`ITEMS_PER_CATEGORY` の直後）:
```python
# 1カテゴリの配信上限。補填時の偏りを防ぐためのハード上限（normalize_digest が截断）。
MAX_PER_CATEGORY = 8
```

2. `NewsDigest.items` の `Field` を変更（`max_length` 削除、`min_length=1`）:
```python
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
```

3. `_validate_per_category_balance` メソッド（`@model_validator(mode="after")` ごと）を**削除**する。

- [ ] **Step 5: テストが通るのを確認**

Run: `pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 6: 全テスト緑を確認**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/models/news.py tests/test_models.py tests/factories.py
git commit -m "feat(*): relax NewsDigest to allow fewer items and category imbalance"
```

---

### Task 3: `normalize_digest`（各≤8・計≤30 のコード截断）

**Files:**
- Modify: `src/models/news.py`
- Modify: `tests/test_models.py`

**Interfaces:**
- Consumes: `MAX_PER_CATEGORY`, `TARGET_TOTAL_ITEMS`, `CATEGORIES`（Task 1/2）
- Produces: `normalize_digest(digest: NewsDigest) -> NewsDigest`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_models.py` に追加（import に `normalize_digest`, `MAX_PER_CATEGORY`, `TARGET_TOTAL_ITEMS` を加える）:

```python
from src.models.news import MAX_PER_CATEGORY, TARGET_TOTAL_ITEMS, normalize_digest


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
```

- [ ] **Step 2: テストが失敗するのを確認**

Run: `pytest tests/test_models.py::TestNormalizeDigest -v`
Expected: FAIL（`normalize_digest` 未定義で ImportError）

- [ ] **Step 3: `normalize_digest` を実装**

`src/models/news.py` の末尾に追加:

```python
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
```

- [ ] **Step 4: テストが通るのを確認**

Run: `pytest tests/test_models.py::TestNormalizeDigest -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/models/news.py tests/test_models.py
git commit -m "feat(*): add normalize_digest to cap per-category and total items"
```

---

### Task 4: `build_coverage_notice`（不足カテゴリ通知文の生成）

**Files:**
- Modify: `src/models/news.py`
- Modify: `tests/test_models.py`

**Interfaces:**
- Consumes: `ITEMS_PER_CATEGORY`, `TARGET_TOTAL_ITEMS`, `CATEGORIES`
- Produces: `build_coverage_notice(digest: NewsDigest) -> str | None`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_models.py` に追加（import に `build_coverage_notice` を加える）:

```python
from src.models.news import build_coverage_notice


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
```

- [ ] **Step 2: テストが失敗するのを確認**

Run: `pytest tests/test_models.py::TestBuildCoverageNotice -v`
Expected: FAIL（`build_coverage_notice` 未定義で ImportError）

- [ ] **Step 3: `build_coverage_notice` を実装**

`src/models/news.py` の末尾に追加（`Counter` は既に import 済み）:

```python
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
```

- [ ] **Step 4: テストが通るのを確認**

Run: `pytest tests/test_models.py::TestBuildCoverageNotice -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/models/news.py tests/test_models.py
git commit -m "feat(*): add build_coverage_notice for shortfall categories"
```

---

### Task 5: HTML メールに不足通知バナーを表示

**Files:**
- Modify: `src/services/html_renderer.py`
- Modify: `src/templates/news_email.html`
- Modify: `tests/test_html_renderer.py`

**Interfaces:**
- Consumes: `build_coverage_notice` の戻り値（`str | None`）
- Produces: `render_news_email(*, digest: NewsDigest, date: str, notice: str | None = None) -> str`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_html_renderer.py` の `class TestRenderNewsEmail` に追加:

```python
    def test_notice_rendered_when_present(self, sample_digest: NewsDigest) -> None:
        notice = "本日は関連ニュースが計10件にとどまり…不足カテゴリ: 海外不動産(0件)"
        html = render_news_email(digest=sample_digest, date="2026-05-01", notice=notice)
        assert "海外不動産(0件)" in html

    def test_notice_absent_when_none(self, sample_digest: NewsDigest) -> None:
        html = render_news_email(digest=sample_digest, date="2026-05-01", notice=None)
        assert "不足カテゴリ" not in html
```

- [ ] **Step 2: テストが失敗するのを確認**

Run: `pytest tests/test_html_renderer.py -v`
Expected: FAIL（`render_news_email` が `notice` 引数を受け取らず TypeError）

- [ ] **Step 3: `render_news_email` に `notice` 引数を追加**

`src/services/html_renderer.py` の `render_news_email` を変更:

```python
def render_news_email(*, digest: NewsDigest, date: str, notice: str | None = None) -> str:
    """Jinja2 で HTML メール本文をレンダリングする。

    Args:
        digest: NewsDigest（関連ニュース。件数は可変）。
        date: 配信対象日（YYYY-MM-DD）。
        notice: 不足通知文（build_coverage_notice の戻り値）。None なら非表示。

    Returns:
        HTML文字列。
    """
    env = _build_env()
    template = env.get_template(_TEMPLATE_FILE)
    return template.render(
        date=date,
        items=digest.items,
        notice=notice,
        category_colors=CATEGORY_COLORS,
        category_text_colors=CATEGORY_TEXT_COLORS,
    )
```

- [ ] **Step 4: テンプレートに通知バナーを追加**

`src/templates/news_email.html` の `<!-- ===== Header ===== -->` の `</tr>`（ヘッダ行の閉じ、`<!-- ===== News Items ===== -->` の直前）に挿入:

```html
                    <!-- ===== Coverage notice banner ===== -->
                    {% if notice %}
                    <tr>
                        <td class="px-mobile" style="padding: 20px 40px 0 40px;">
                            <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color:#fdf0d5; border-left:4px solid #d4a04a; border-radius:6px;">
                                <tr>
                                    <td style="padding:14px 18px;">
                                        <p style="margin:0; font-size:13px; color:#9a5a1a; line-height:1.65;">
                                            ⚠️ {{ notice }}
                                        </p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    {% endif %}
```

- [ ] **Step 5: テストが通るのを確認**

Run: `pytest tests/test_html_renderer.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/services/html_renderer.py src/templates/news_email.html tests/test_html_renderer.py
git commit -m "feat(*): show shortfall notice banner in HTML email"
```

---

### Task 6: Slack に不足通知メッセージを先頭投稿

**Files:**
- Modify: `src/services/slack_client.py`
- Modify: `tests/test_slack_client.py`

**Interfaces:**
- Consumes: `build_coverage_notice` の戻り値（`str | None`）
- Produces: `send_news_by_category(*, webhook_url: str, digest: NewsDigest, date: str, notice: str | None = None) -> int`（戻り値は送信メッセージ数。notice ありなら +1）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_slack_client.py` の `class TestSendNewsByCategory` に追加:

```python
    def test_notice_prepends_message(self, mocker, sample_digest: NewsDigest) -> None:
        mock_urlopen = mocker.patch.object(
            slack_client.urllib.request, "urlopen", return_value=_ok_response()
        )
        sent = send_news_by_category(
            webhook_url=WEBHOOK, digest=sample_digest, date="2026-05-01",
            notice="不足カテゴリ: 海外不動産(0件)",
        )
        # 先頭の通知メッセージ + カテゴリ別6メッセージ = 7
        assert sent == len(CATEGORIES) + 1
        assert mock_urlopen.call_count == len(CATEGORIES) + 1

    def test_no_notice_no_extra_message(self, mocker, sample_digest: NewsDigest) -> None:
        mocker.patch.object(
            slack_client.urllib.request, "urlopen", return_value=_ok_response()
        )
        sent = send_news_by_category(
            webhook_url=WEBHOOK, digest=sample_digest, date="2026-05-01", notice=None
        )
        assert sent == len(CATEGORIES)
```

- [ ] **Step 2: テストが失敗するのを確認**

Run: `pytest tests/test_slack_client.py::TestSendNewsByCategory -v`
Expected: FAIL（`notice` 引数未対応で TypeError）

- [ ] **Step 3: `send_news_by_category` に `notice` を追加**

`src/services/slack_client.py` の `send_news_by_category` を変更（シグネチャに `notice` 追加、本体冒頭に通知投稿を追加）:

```python
def send_news_by_category(
    *, webhook_url: str, digest: NewsDigest, date: str, notice: str | None = None
) -> int:
    """ニュースをカテゴリ別に各1メッセージとして Slack に送信する。

    notice が与えられた場合、カテゴリ別送信の前に不足通知を1メッセージ投稿する。

    Returns:
        送信したメッセージ数（notice ありなら +1）。

    Raises:
        SlackSendError: いずれかの送信が失敗した時点で即座に投げる。
    """
    sent_count = 0
    if notice:
        notice_payload = {
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"⚠️ {_escape_mrkdwn(notice)}"},
                }
            ],
            "text": notice,
        }
        _post(webhook_url, notice_payload, category=None)
        sent_count += 1
        logger.info("slack notice sent")

    grouped = _group_by_category(digest)
    for category, items in grouped.items():
        payload = {
            "blocks": _build_blocks(category, items, date),
            "text": f"{category} - {date} の不動産ニュース {len(items)}件",
        }
        _post(webhook_url, payload, category=category)
        sent_count += 1
        logger.info("slack send: category=%s, items=%d", category, len(items))
    logger.info("slack send total: messages=%d, categories=%d", sent_count, len(grouped))
    return sent_count
```

- [ ] **Step 4: テストが通るのを確認**

Run: `pytest tests/test_slack_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/services/slack_client.py tests/test_slack_client.py
git commit -m "feat(*): prepend shortfall notice message to Slack delivery"
```

---

### Task 7: handler に normalize + notice 配信を統合

**Files:**
- Modify: `src/handlers/distribute_news.py`
- Modify: `tests/test_distribute_news.py`

**Interfaces:**
- Consumes: `normalize_digest`, `build_coverage_notice`（Task 3/4）、`render_news_email(..., notice=)`（Task 5）、`send_news_by_category(..., notice=)`（Task 6）
- Produces: 配信フローに `normalize_digest` → `build_coverage_notice` を組み込み、両配信に notice を渡す。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_distribute_news.py` に追加（`make_items` を import）。handler が部分 digest でも正常配信し、notice を Slack に渡すことを検証:

```python
    def test_partial_digest_passes_notice_to_slack(self, mocker) -> None:
        from tests.factories import make_items

        partial = NewsDigest(items=make_items({"PropTech": 3, "企業動向": 2}))
        mocker.patch.object(distribute_news, "load_config", return_value=_make_config(email=False))
        mocker.patch.object(distribute_news, "run_news_agent", return_value=partial)
        send_slack = mocker.patch.object(distribute_news, "send_news_by_category", return_value=2)

        result = distribute_news.lambda_handler({}, None)

        assert result["statusCode"] == 200
        # notice（不足あり）が Slack 送信に渡されている
        notice_arg = send_slack.call_args.kwargs["notice"]
        assert notice_arg is not None
        assert "PropTech(3件)" in notice_arg
```

> 注: `NewsDigest` を test 冒頭で import 済みであること（既存 import を確認。無ければ `from src.models.news import NewsDigest` を追加）。

- [ ] **Step 2: テストが失敗するのを確認**

Run: `pytest tests/test_distribute_news.py::TestLambdaHandler::test_partial_digest_passes_notice_to_slack -v`
Expected: FAIL（handler が `notice` を渡さず KeyError、または normalize 未統合）

> クラス名 `TestLambdaHandler` は既存ファイルの定義に合わせる（異なる場合は実際のクラス名を使う）。

- [ ] **Step 3: handler を更新**

`src/handlers/distribute_news.py` を編集:

1. import 変更:
```python
from src.models.news import NewsDigest, build_coverage_notice, normalize_digest
```

2. `_send_email` に `notice` 引数を追加し `render_news_email` へ渡す:
```python
def _send_email(config: AppConfig, digest: NewsDigest, today: str, notice: str | None) -> str:
    html_body = render_news_email(digest=digest, date=today, notice=notice)
    subject = f"[カチタス Daily News] {today} 本日の不動産ニュース"
    return send_html_email(
        sender=config.sender_email,
        recipients=config.recipient_emails,
        subject=subject,
        html_body=html_body,
        region_name=AWS_REGION,
    )
```

3. `lambda_handler` のニュース取得直後に規整と通知生成を追加:
```python
    digest = apply_url_rewrites(digest)
    digest = normalize_digest(digest)
    coverage_notice = build_coverage_notice(digest)
    logger.info(
        "digest fetched: items=%d, shortfall=%s", len(digest.items), bool(coverage_notice)
    )
```

4. email 送信を `notice` 付きに:
```python
        result["sesMessageId"] = _send_email(config, digest, today, coverage_notice)
```

5. Slack 送信を `notice` 付きに:
```python
            slack_total += send_news_by_category(
                webhook_url=webhook_url,
                digest=digest,
                date=today,
                notice=coverage_notice,
            )
```

- [ ] **Step 4: テストが通るのを確認**

Run: `pytest tests/test_distribute_news.py -v`
Expected: PASS（既存テストは sample_digest=完全30件で notice=None のため挙動不変）

- [ ] **Step 5: 全テスト緑を確認**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/handlers/distribute_news.py tests/test_distribute_news.py
git commit -m "feat(*): integrate normalize_digest and shortfall notice into handler"
```

---

### Task 8: プロンプト改訂（関連性フィルタ・補填ルール）＋ bedrock_client 文言＋ドキュメント

**Files:**
- Modify: `docs/design/prompt.txt`
- Modify: `src/services/bedrock_client.py`
- Modify: `.claude/rules/project-structure.md`
- Modify: `docs/INTEGRITY_CHECK.md`
- Modify: `tests/test_bedrock_client.py`

**Interfaces:**
- Consumes: なし（文言・ドキュメント）
- Produces: モデルへの指示文（関連性フィルタ＋補填）。挙動は変えず文言整合のみ。

- [ ] **Step 1: `prompt.txt` を改訂**

`docs/design/prompt.txt` に以下を反映する。

1. 冒頭1行目「各カテゴリ5本ずつ・計30本」を「**目標** 各カテゴリ5本・計30本（関連ニュースが不足する場合は少なくてよい）」へ。

2. 「## 必須の作業手順」の手順3を、関連性フィルタと補填ルールに差し替え:
```
3. **関連性フィルタ（最重要）**: 検索で得た記事のうち、**ニュース内容が不動産・住宅・カチタス事業（実需向け中古戸建の再生・買取再販）と関係しないものは選ばない**。
   - 重点ウォッチ企業の記事でも、内容が事業と無関係なもの（家具・家電・食品など。例:「ニトリ 大型ホットプレート発売」）は**除外**する。企業名の一致ではなく、ニュース内容で判定すること。
   - **件数より関連性を優先**: 無関係なニュースで件数を埋めるのは厳禁。
4. **補填と件数**: 目標は各カテゴリ5本・計30本。あるカテゴリで関連記事が5本揃わなければ、そのカテゴリは少なくてよい（0本も可）。関連記事が豊富なカテゴリで**最大8本まで**増やし、計30本に近づける。全体で関連記事が30本に満たない場合は、揃う分だけ選べばよい（少ない件数でも正常）。
5. **submit_news_digest で最終結果を送信**: 選定が終わったら必ず1回だけ呼んで終了する。
```
（以降の番号がずれるため、元の手順4 submit は上記5に統合済み。元手順内の「各カテゴリちょうど5本に揃える／満たないと検証エラー」の記述は削除する。）

3. 「## カテゴリ（各5本ずつ・計30本）」見出しを「## カテゴリ（目標 各5本・計30本／不足時は少なくてよい）」へ。

- [ ] **Step 2: `bedrock_client.py` の文言を更新**

`src/services/bedrock_client.py` の以下を変更（挙動に影響しない文言のみ。`maxTokens` 等の数値ロジックは触らない）:

1. `SUBMIT_TOOL_DESCRIPTION`: 「全{len(CATEGORIES)}カテゴリ各{ITEMS_PER_CATEGORY}件・計{TARGET_TOTAL_ITEMS}件」→「不動産事業に関連するニュースを、目標 全{len(CATEGORIES)}カテゴリ各{ITEMS_PER_CATEGORY}件・計{TARGET_TOTAL_ITEMS}件（不足時は少なくてよい）」。

2. `SEARCH_TOOL_DESCRIPTION`: 「計{TARGET_TOTAL_ITEMS}件（各カテゴリ{ITEMS_PER_CATEGORY}件）を選ぶ前に」→「目標 計{TARGET_TOTAL_ITEMS}件（各カテゴリ{ITEMS_PER_CATEGORY}件）を選ぶ前に」。

3. `system_prompt` の作業フロー部分:
   - 「以下 {len(CATEGORIES)} カテゴリ各 {ITEMS_PER_CATEGORY} 件・計 {TARGET_TOTAL_ITEMS} 件を選定」→「目標 各 {ITEMS_PER_CATEGORY} 件・計 {TARGET_TOTAL_ITEMS} 件を選定（内容が不動産・住宅と無関係なニュースは除外。関連が不足するカテゴリは少なくてよく、豊富なカテゴリは最大 {MAX_PER_CATEGORY} 件まで）」。`MAX_PER_CATEGORY` を import に追加。
   - 「※ 各カテゴリちょうど {ITEMS_PER_CATEGORY} 件でないと検証エラーになり再提出が必要。」の行を**削除**。
   - 末尾「budget_exhausted ... 各カテゴリ {ITEMS_PER_CATEGORY} 件（計 {TARGET_TOTAL_ITEMS} 件）を選び」→「budget_exhausted ... その時点までの関連記事を各カテゴリ最大 {MAX_PER_CATEGORY} 件・計 {TARGET_TOTAL_ITEMS} 件を上限に選び」。

4. submit 検証失敗時の `hint`（`tool_results` の `json.hint`）から件数に関する記述を削除し、フィールド形式制約のみ案内:
```python
"hint": (
    "各フィールドの文字数制約（summary 40〜120字、title 1〜120字、"
    "katitas_relevance 40〜300字）と source_url の形式を満たすよう修正し、"
    "再度 submit_news_digest を呼び出してください。"
),
```

- [ ] **Step 3: bedrock テストで挙動不変を確認**

Run: `pytest tests/test_bedrock_client.py -v`
Expected: PASS（文言変更のみ。ロジック不変）

- [ ] **Step 4: ドキュメントを更新**

1. `.claude/rules/project-structure.md` の「主要ファイル」表に追記:
```
| `src/models/news.py` | NewsModel 定義・normalize_digest（件数截断）・build_coverage_notice（不足通知） |
```
「ソースコードと設計書の対応表」に行を追加:
```
| src/models/news.py の関連性フィルタ・補填・通知 | docs/plans/2026-06-30-01-news-relevance-filter.md | 関連性フィルタ＋補填＋不足通知 |
```

2. `docs/INTEGRITY_CHECK.md` に本変更の行を追加（ステータス ✅）。既存フォーマットに合わせて「ニュース関連性フィルタ／補填／不足通知」を実装済みとして記載。

- [ ] **Step 5: 全テスト緑を確認**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add docs/design/prompt.txt src/services/bedrock_client.py .claude/rules/project-structure.md docs/INTEGRITY_CHECK.md tests/test_bedrock_client.py
git commit -m "docs(*): add relevance filter and redistribution rules to prompt and docs"
```

---

## 自己レビュー結果

- **Spec coverage:** 関連性フィルタ(Task 8)/補填・各≤8(Task 8 プロンプト + Task 3 截断)/総数30維持(Task 3,8)/不足通知メール(Task 5)・Slack(Task 6)/截断で未配信防止(Task 3,7)/制約緩和(Task 2)/空配信拒否(Task 2)/定数改名(Task 1)/ドキュメント(Task 8) — 全要件にタスク対応あり。
- **Placeholder scan:** プレースホルダなし。各コードステップに実コードを記載。
- **Type consistency:** `normalize_digest(NewsDigest)->NewsDigest`、`build_coverage_notice(NewsDigest)->str|None`、`render_news_email(...,notice:str|None=None)`、`send_news_by_category(...,notice:str|None=None)->int` がタスク間で一貫。定数 `MAX_PER_CATEGORY`/`TARGET_TOTAL_ITEMS`/`ITEMS_PER_CATEGORY` は Task 1/2 で定義し以降で参照。

## 留意点（実装時に確認）

- `tests/test_distribute_news.py` の handler テストクラス名・`NewsDigest` import 有無は実ファイルで確認してから合わせる。
- `docs/INTEGRITY_CHECK.md` は現行フォーマットを読んでから行を追加する。
- `src/templates/news_email_sample.html`（サンプル）は配信に未使用のため本計画では変更しない。

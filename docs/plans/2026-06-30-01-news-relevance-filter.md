# ニュース関連性フィルタ＋カテゴリ間補填＋不足通知 設計書

- **作成日**: 2026-06-30
- **対象機能**: キーワード取得後のニュース関連性フィルタリングと配信件数の柔軟化
- **ステータス**: 設計（実装前）

---

## 1. 背景・目的（WHY）

プロンプトに重点キーワード／重点ウォッチ企業を追加した結果、有用なニュースを拾えるようになった一方で、**不動産・カチタス事業と内容的に無関係なニュースが混入**するようになった。

代表例: 「ニトリ、餃子60個を焼ける大型ホットプレートを発売」。ニトリホールディングスは重点ウォッチ企業リストに含まれるが、このニュース内容は不動産・住宅と無関係であり、配信すべきではない。

**目的**: キーワードで取得したニュースに対し関連性フィルタを掛け、無関係なものを除外する。その結果カテゴリごとの件数が不足する場合は他カテゴリで補填し、全体でも不足する場合は「関連するニュースのみ」を配信したうえで、どのカテゴリが規定件数に届かなかったかを受信者に通知する。

---

## 2. 現状の問題（WHAT）

現行の `src/models/news.py` の `NewsDigest` は「各カテゴリ**ちょうど** `ITEMS_PER_CATEGORY`(=5) 件・計 `TOTAL_ITEMS`(=30) 件」をハード制約として強制する。

```
ITEMS_PER_CATEGORY = 5   # ハード制約 兼 目標値（二役）
TOTAL_ITEMS = 30
```

この硬直制約が以下を招いている:

1. 関連ニュースが5件揃わないカテゴリで、**数合わせのために無関係ニュースを混入**せざるを得ない（混入の根本原因）。
2. 制約違反時は `submit_news_digest` の検証が失敗し、モデルが最大 `_MAX_SUBMIT_ATTEMPTS`(=3) 回再提出。3回失敗すると `BedrockToolUseError` が `lambda_handler` まで伝播し、**当日のニュースが一切配信されない**（DLQ→アラート）。

---

## 3. 要件（ユーザー確定事項）

| 項目 | 決定 |
|------|------|
| 補填・総数方針 | **総数30を維持**。不足分は関連ニュースが豊富なカテゴリで補填。ただし偏り防止のため **1カテゴリ最大8件** の上限を設ける |
| 関連性の判定基準 | **ニュース内容で判定**。ウォッチ対象企業でも、内容が不動産/住宅/カチタス事業と無関係なら除外（例: ニトリのホットプレート発売） |
| 不足通知の表示先 | **メール・Slack 両方**の先頭に表示 |
| 上限超過時の挙動 | **コード側で自動截断（絶対に未配信にしない）**。1カテゴリ>8件・総数>30件はコードが規整して送信。検証失敗による全件未配信を起こさない |

---

## 4. 設計方針（HOW）

### 4.1 役割分担の原則

- **関連性フィルタはモデル駆動**: 「不動産/住宅と内容的に関係するか」は意味的判断であり、キーワード一致のコード判定では解けない（そもそも今回の混入原因がキーワード一致）。よってプロンプトでモデルに判断させる。
- **件数の整形と不足通知はコード駆動**: 「各カテゴリ≤8・計≤30」の上限規整と「どのカテゴリが5件未満か」の集計は、決定的・テスト可能な処理としてコード側に置く。モデルの自己申告に依存しない。

### 4.2 校验层职责的再划分

`NewsDigest` の Pydantic 検証は **「自動修復できない制約」だけ** を担う:

| 制約 | 担い手 | 理由 |
|------|--------|------|
| 各 NewsItem の title/summary/url/katitas_relevance/category 形式 | Pydantic（検証失敗→モデル再提出） | フィールド単位の不正は機械修復不可。モデルに直させる |
| 総件数 ≥ 1（空配信防止） | Pydantic（min_length=1） | 完全な空は障害。アラートすべき |
| 各カテゴリ ≤ 8 件 | **コード（normalize で截断）** | 機械的に規整可能。検証失敗で未配信にしない |
| 総件数 ≤ 30 件 | **コード（normalize で截断）** | 同上 |

旧 `_validate_per_category_balance`（ちょうど5件強制）は **削除**。`max_length=TOTAL_ITEMS` も `NewsDigest.items` から **削除**（上限はコード截断に委譲）。

---

## 5. レイヤ別詳細設計

### 5.1 モデル層 `src/models/news.py`

**定数**
```python
ITEMS_PER_CATEGORY = 5      # 各カテゴリの目標件数（不足通知の閾値）
MAX_PER_CATEGORY = 8        # 1カテゴリの配信上限（補填時の偏り防止）
TARGET_TOTAL_ITEMS = 30     # 目標総件数（= 截断上限）
# 旧 TOTAL_ITEMS は TARGET_TOTAL_ITEMS に名称変更（"必達" のニュアンスを排除）。
# 別名は残さず、参照する全ファイル（bedrock_client / tests / factories 等）を改名に追従させる。
```

**`NewsItem`**: 変更なし（フィールド形式制約は維持）。

**`NewsDigest`**:
- `items`: `min_length=1` のみ（`max_length` 削除）。description を「関連する不動産ニュース。目標は全カテゴリ各5件・計30件だが、関連ニュースが不足する場合は少なくてよい」に更新。
- `_validate_per_category_balance` を削除。

**新規関数（同モジュール内）**
```python
def normalize_digest(digest: NewsDigest) -> NewsDigest:
    """配信前の件数規整。各カテゴリを最大 MAX_PER_CATEGORY 件、
    総件数を最大 TARGET_TOTAL_ITEMS 件に截断する。
    截断順序:
      1. CATEGORIES 出現順を保ちつつ、各カテゴリ先頭 MAX_PER_CATEGORY 件まで採用
      2. 採用順（元の items 順）で総数 TARGET_TOTAL_ITEMS 件に到達したら打ち止め
    モデルが上限を超えて submit しても未配信にせず、決定的に整形する兜底。"""

def build_coverage_notice(digest: NewsDigest) -> str | None:
    """規整後の digest を受け取り、ITEMS_PER_CATEGORY(5) 件未満のカテゴリを集計。
    全カテゴリが5件以上なら None。
    1件以上不足カテゴリがあれば通知文を返す:
      - 総件数 >= TARGET_TOTAL_ITEMS の場合（補填で総数は確保できたが偏った）:
        「本日は一部カテゴリで関連ニュースが規定の5件に届かず、他カテゴリで補填しています。
          不足カテゴリ: 海外不動産(3件) / 法規制・政策(4件)」
      - 総件数 < TARGET_TOTAL_ITEMS の場合（全体でも不足）:
        「本日は関連ニュースが計N件にとどまり、各カテゴリ5件（計30件）を満たせませんでした。
          不足カテゴリ: 海外不動産(3件) / ...」
    """
```

> `build_coverage_notice` は **`normalize_digest` 適用後** の digest に対して呼ぶ（実際に配信する件数と通知を一致させるため）。

### 5.2 プロンプト/エージェント層

**`docs/design/prompt.txt`** に以下を反映:
1. **関連性フィルタの明文化**: 「`search_real_news` で取得した記事のうち、**ニュース内容が不動産・住宅・カチタス事業（実需向け中古戸建の再生・買取再販）と関係しないものは選ばない**。重点ウォッチ企業の記事であっても、内容が不動産・住宅と無関係なもの（例: 家具・家電・食品など事業外のプレスリリース。具体例: 「ニトリ 大型ホットプレート発売」）は除外する」。
2. **補填ルール**: 「目標は計30件・各カテゴリ5件。あるカテゴリで関連記事が5件揃わなければ、そのカテゴリは**少なくてよい（0件も可）**。関連記事が豊富なカテゴリで**最大8件まで**増やし、計30件に近づける」。
3. **件数より関連性を優先**: 「無関係なニュースで件数を埋めることは厳禁。全体で関連記事が30件に満たない場合は、**揃う分だけ** submit してよい（少ない件数での submit は正常で、検証エラーにならない）」。
4. カテゴリ見出しの「各5本ずつ・計30本」を「目標 各5本・計30本（不足時は少なくてよい）」へ修正。

**`src/services/bedrock_client.py`** の文言更新（実装上の挙動に影響する箇所）:
- `system_prompt` 内「各カテゴリちょうど5件でないと検証エラー」→「目標は各5件・計30件。関連記事が不足するカテゴリは少なくてよい（0件可）。豊富なカテゴリは最大8件まで。無関係ニュースでの数合わせは禁止」。
- `SUBMIT_TOOL_DESCRIPTION` / `SEARCH_TOOL_DESCRIPTION`: 「各5件・計30件」→「目標 各5件・計30件（不足可）」。
- 検証失敗時の `hint`（`tool_results` の error 文面）: 「各カテゴリちょうど5件」の記述を削除し、フィールド形式制約のみを案内（件数はコード截断するためモデルに件数修正を促す必要がない）。

### 5.3 配信層

**`src/handlers/distribute_news.py`**
```python
digest = run_news_agent(...)
digest = apply_url_rewrites(digest)
digest = normalize_digest(digest)            # 追加: 件数兜底規整
coverage_notice = build_coverage_notice(digest)  # 追加: 不足通知文（無ければ None）
logger.info("digest fetched: items=%d, notice=%s", len(digest.items), bool(coverage_notice))
...
# email: _send_email(config, digest, today, notice=coverage_notice)
# slack: send_news_by_category(..., notice=coverage_notice)
```

**`src/services/html_renderer.py`**
- `render_news_email(*, digest, date, notice: str | None = None)` に引数追加。
- テンプレートへ `notice=notice` を渡す。

**`src/templates/news_email.html`**
- ヘッダ（`<!-- ===== Header ===== -->`）直下に通知バナーを追加。`{% if notice %}` で囲み、警告色（例: `#fdf0d5` 背景 + `#9a5a1a` テキスト）の枠で `{{ notice }}` を表示。

**`src/services/slack_client.py`**
- `send_news_by_category(*, webhook_url, digest, date, notice: str | None = None)` に引数追加。
- `notice` があればカテゴリ別送信の**前に**先頭メッセージを1本 `_post`（`section` ブロックに ⚠️ 付きで `notice` を表示）。送信メッセージ数のカウントに含める。

### 5.4 テスト/ドキュメント（実装と同時更新）

**`tests/factories.py`**
- `make_balanced_items` は維持（各カテゴリ5件・計30件）。
- 追加: `make_items(counts: dict[str, int])` — カテゴリ→件数を指定して任意構成の items を生成（不足・補填・超過のテスト用）。

**`tests/test_models.py`**（差し替え）
- `test_balanced_digest_accepted`: 維持。
- 旧 `test_fewer_than_total_rejected` / `test_more_than_total_rejected` / `test_unbalanced_category_rejected` を削除または書き換え:
  - 計30件未満でも受理されること。
  - 単一カテゴリ偏りでも（≤上限なら）受理されること。
  - 空（0件）は `min_length=1` で拒否されること。
- 追加 `test_normalize_digest`: 9件のカテゴリ→8件に截断 / 合計40件→30件に截断。
- 追加 `test_build_coverage_notice`: 全カテゴリ5件→None / 一部<5かつ計30→補填文面 / 計<30→不足文面、不足カテゴリ名と件数が含まれること。

**`tests/test_bedrock_client.py`**
- `== TOTAL_ITEMS` のアサート（4箇所）を、定数改名に追従（`TARGET_TOTAL_ITEMS` か別名）。少数件の submit を受理する正常系を1つ追加。

**`tests/test_html_renderer.py`**
- `notice` 引数ありで通知文がHTMLに含まれること、`notice=None` で含まれないことを検証。

**`tests/test_slack_client.py`**
- `notice` ありで先頭メッセージが1本増えること、`ITEMS_PER_CATEGORY` 固定アサートを件数可変前提に修正。

**`tests/test_distribute_news.py`**
- `slackMessageCount` のアサートを `notice` 有無で調整。

**ドキュメント**
- `docs/design/prompt.txt`: 上記プロンプト改訂（本変更の中心成果物）。
- `.claude/rules/project-structure.md`: `normalize_digest` / `build_coverage_notice` を主要関数に追記。対応表に本設計書を追加。
- `docs/INTEGRITY_CHECK.md`: 該当行を更新（実装完了時）。
- 旧 `TOTAL_ITEMS` を参照している全箇所を改名に追従。

---

## 6. エッジケース

| ケース | 挙動 |
|--------|------|
| 全カテゴリ5件以上 | 通知なし。通常配信 |
| 一部カテゴリ<5・補填で計30達成 | 通知あり（補填文面）。不足カテゴリ名＋件数を明示 |
| 全体で<30件しか関連なし | 通知あり（不足文面）。揃う分のみ配信 |
| モデルが1カテゴリ9件以上 submit | `normalize_digest` が8件に截断。未配信にはしない |
| モデルが計31件以上 submit | `normalize_digest` が30件に截断 |
| 関連ニュース0件 | `NewsDigest` の `min_length=1` で検証失敗→モデル再提出→最終的に失敗時はアラート（空配信防止） |

---

## 7. 完了条件

- [ ] `NewsDigest` が計30件未満・カテゴリ偏りを受理する（空のみ拒否）
- [ ] `normalize_digest` が 各≤8・計≤30 に截断する（単体テスト緑）
- [ ] `build_coverage_notice` が不足カテゴリと件数を含む文面を返す（補填/不足の2文面・単体テスト緑）
- [ ] メール・Slack 双方の先頭に不足通知が表示される
- [ ] プロンプトに関連性フィルタ（内容ベース・ニトリ反例）と補填ルールが明文化されている
- [ ] `pytest` 全緑
- [ ] `docs/design/prompt.txt` / `project-structure.md` / `INTEGRITY_CHECK.md` 更新済み

---

## 8. 影響ファイル一覧

| 区分 | ファイル |
|------|----------|
| 修正 | `src/models/news.py`（制約緩和・normalize・notice 追加） |
| 修正 | `src/services/bedrock_client.py`（文言・定数追従） |
| 修正 | `src/handlers/distribute_news.py`（normalize/notice 呼び出し） |
| 修正 | `src/services/html_renderer.py`（notice 引数） |
| 修正 | `src/templates/news_email.html`（通知バナー） |
| 修正 | `src/services/slack_client.py`（notice 先頭メッセージ） |
| 修正 | `docs/design/prompt.txt`（関連性フィルタ・補填ルール） |
| 修正 | `tests/factories.py` ほかテスト各種 |
| 修正 | `.claude/rules/project-structure.md` / `docs/INTEGRITY_CHECK.md` |

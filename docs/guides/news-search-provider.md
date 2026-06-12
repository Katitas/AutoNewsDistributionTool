# ニュース検索プロバイダ選定ガイド

Bedrock の `search_real_news` ツールが内部で呼び出す Web Search API は **Brave Search API**（デフォルト）と **Tavily Search API** をサポートする。

---

## 結論（TL;DR）

- **デフォルト**: Brave Search API（無料 2000 query/月、上限 50/起動）
- **代替**: Tavily Search API（無料 1000 query/月、上限 25/起動）

無料枠の広さで Brave が優勢。LLM 特化の要約品質が必要なら Tavily に切り替え可能。

---

## プロバイダ比較

| 観点 | Brave Search（デフォルト） | Tavily Search |
|------|---------------------------|---------------|
| 無料枠 | **2000 query/月** | 1000 query/月 |
| 1起動あたり推奨上限 | **50** | 25 |
| ニュース特化エンドポイント | ◎（`/news/search`） | ◯（`topic="news"`） |
| 日本語品質 | ○ | ◎ |
| LLM最適化済みコンテンツ | △（生 description） | ◎（要約済み） |
| 申請容易性 | クレカ登録 | サインアップのみ |
| 公式ドキュメント | https://brave.com/search/api/ | https://tavily.com/ |

### 上限値の根拠

無料枠 ÷ 30日 × 0.75（25%バッファ）で計算:

- Brave : 2000 ÷ 30 × 0.75 = 50/起動 → 月1500 query 消費（無料枠の75%）
- Tavily: 1000 ÷ 30 × 0.75 = 25/起動 → 月750 query 消費（無料枠の75%）

これらは `src/services/news_search.py:PROVIDER_DEFAULT_CAPS` で集中管理されており、
プロバイダ切替時に自動的に反映される。

---

## API キー取得手順

### Brave Search API（デフォルト）

1. https://brave.com/search/api/ にアクセス → "Get Started"
2. アカウント作成 → クレカ登録（無料プランでも要求される）
3. ダッシュボードで API キー（`BSA-...`）を作成

### Tavily

1. https://tavily.com にアクセス → Sign up
2. Dashboard で API キー（`tvly-...`）をコピー

---

## Parameter Store 投入

```bash
ENV=stg

# プロバイダ（任意。未設定時はデフォルト brave）
aws ssm put-parameter \
  --name /kati/auto_news_distribute/${ENV}/news-search-provider \
  --value "brave" \
  --type String --overwrite \
  --region ap-northeast-1

# API キー（必須、SecureString）
aws ssm put-parameter \
  --name /kati/auto_news_distribute/${ENV}/news-search-api-key \
  --value "BSA-XXXXXXXX" \
  --type SecureString --overwrite \
  --region ap-northeast-1

# (任意) 1起動あたりの検索上限を上書き。未設定なら provider 既定値（brave=50, tavily=25）
# aws ssm put-parameter \
#   --name /kati/auto_news_distribute/${ENV}/news-search-max-per-invocation \
#   --value "50" \
#   --type String --overwrite \
#   --region ap-northeast-1
```

---

## プロバイダの切替方法

`/kati/auto_news_distribute/{env}/news-search-provider` を `brave` / `tavily` のいずれかに変更し、
対応する API キーを `news-search-api-key` に投入するだけ。

**重要**: 上限値も provider に応じて自動調整される（Brave→50, Tavily→25）。
`news-search-max-per-invocation` を明示設定している場合のみ、その値が優先される。

---

## 上限の引き上げ方法（有料化時）

優先順位（高い順に上書き）:

| レイヤ | 設定箇所 | 用途 |
|--------|----------|------|
| 関数引数 | `run_news_agent(max_searches_per_invocation=N)` | テスト・特殊実行 |
| Parameter Store | `/kati/auto_news_distribute/{env}/news-search-max-per-invocation` | 環境別の運用調整 |
| 環境変数 | `NEWS_SEARCH_MAX_PER_INVOCATION` | Lambda config から |
| プロバイダ既定値 | `news_search.PROVIDER_DEFAULT_CAPS` | 無料枠運用 |

**例: Brave Pro（$5/月で20000 query）に切り替える場合**

```bash
aws ssm put-parameter \
  --name /kati/auto_news_distribute/prod/news-search-max-per-invocation \
  --value "200" \
  --type String --overwrite \
  --region ap-northeast-1
```

それだけで Lambda 再デプロイなく上限を引き上げ可能。

---

## 予算保護の仕組み

`bedrock_client.py:run_news_agent()` 内で1起動あたりの呼び出し回数をカウント。
上限到達時は実 API を叩かず、Bedrock に `budget_exhausted: true` を返す。

```
Lambda 起動
  └─ run_news_agent
       │  searches_max = provider 既定値 or Parameter Store override
       ├─ system_prompt に「最大 N 回まで」を明示（Bedrock が事前計画できる）
       │
       ├─ Bedrock が search_real_news を呼ぶたびに:
       │    if searches_used >= searches_max:
       │      → 実 API を叩かず budget_exhausted=true を返却
       │    else:
       │      → search_news() 実行、searches_used +=1
       │      → toolResult に searches_remaining を含める（Bedrock が残量を追跡可能）
       │
       └─ Bedrock は budget_exhausted を見て submit_news_digest を呼んで終了
            （例外は一切投げない）
```

---

## なぜ Bedrock 単体でなく外部 API が必要か

Amazon Bedrock の Claude 単体には Web 検索機能がない。Bedrock Knowledge Bases 経由で接続することは可能だが、リアルタイム性のあるニュースを扱うには:
- Web 検索 API を Lambda 内で呼ぶ（本ツール）
- AWS が提供する Bedrock Agents の Action Group + Lambda で検索ツールを実装

の2択になる。本ツールは前者を採用（インフラがシンプル、Bedrock Agents の運用コスト回避）。

---

## 関連

- [bedrock-model-selection.md](./bedrock-model-selection.md) — Bedrock モデルの選定
- [.claude/rules/deploy-workflow.md](../../.claude/rules/deploy-workflow.md) — デプロイ手順

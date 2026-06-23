# 自動ニュース配信システム 実装計画

**作成日**: 2026-05-01
**ステータス**: 要件確定済み（2026-05-01）

---

## 1. 目的（WHY）

毎日朝8時に、Amazon Bedrock（Opus 4.7）から**カチタスの実需中古住宅事業に関連する不動産ニュース**を5件取得し、各ニュースに「業務プロセスへの示唆」を付加した形で **HTMLメール（SES）と Slack の両チャネル**で社内配信する。

**対象カテゴリ**: PropTech / 企業動向 / 法規制・政策 / マーケット・価格動向 / 海外不動産 / リフォーム関連
**対象外**: マンション、投資用不動産

**配信チャネル仕様（2026-05-01 要件追加）**:
- メール: `recipient-emails` が空でなければHTML一通で全受信者にBCC送信。空ならスキップ。
- Slack: `slack-webhook-url` が空でなければ、ニュースを**カテゴリ別にグルーピングして1カテゴリ1メッセージ**を Block Kit形式で送信。空ならスキップ。
- 両方が空の場合は起動時エラー（無駄なBedrock呼び出しを避ける）。

## 2. 全体アーキテクチャ

```
[EventBridge Rule]                          [SNS Topic]
  cron(0 23 * * ? *)                          ↑ アラーム通知
    ↓ JST 08:00                               │
[Lambda: NewsDistribution]  ─── failure ──→ [CloudWatch Alarm]
    ├→ [Parameter Store] (送信先メール等取得)
    ├→ [Bedrock: Opus 4.7] (固定フォーマットJSON取得)
    ├→ HTMLテンプレート埋め込み
    ├→ [SES] (HTMLメール送信)
    └→ [CloudWatch Logs] (実行ログ)
```

## 3. コンポーネント詳細

### 3.1 EventBridge Rule

| 項目 | 値 |
|------|-----|
| スケジュール | `cron(0 23 * * ? *)`（UTC、JST 08:00） |
| ターゲット | NewsDistribution Lambda |
| State | ENABLED（STG では DISABLED で開始） |

### 3.2 Lambda 関数

| 項目 | 値 |
|------|-----|
| ランタイム | Python 3.13 |
| メモリ | 512 MB（要調整） |
| タイムアウト | 5分（Bedrock呼び出し時間考慮） |
| ハンドラー | `src/handlers/distribute_news.lambda_handler` |

**処理フロー:**
1. Parameter Store から設定一括取得（プロンプト含む）
2. Bedrock API 呼び出し（Tool Use で固定フォーマット強制）
3. レスポンスをPydanticでバリデーション
4. email有効時: Jinja2でHTMLレンダリング → SESで送信
5. Slack有効時: カテゴリ別グルーピング → Webhook送信
6. 失敗時は例外を再送出（EventBridge Schedulerでリトライ → DLQ → CloudWatch Alarm）

### 3.3 Parameter Store

| パラメータ名 | 型 | 必須 | 用途 |
|-------------|-----|------|------|
| `/kati/auto_news_distribute/{env}/bedrock-model-id` | String | **必須** | Bedrockモデル ID（Opus 4.7 inference profile） |
| `/kati/auto_news_distribute/{env}/prompt` | String | **必須** | Bedrockに送るプロンプト本文（4KB上限。`docs/design/prompt.txt` から反映） |
| `/kati/auto_news_distribute/{env}/recipient-emails` | StringList / String | 任意 | 送信先メールアドレス（カンマ区切り、空ならメール送信スキップ） |
| `/kati/auto_news_distribute/{env}/sender-email` | String | recipient-emails 設定時のみ必須 | SES送信元（要SES検証済み） |
| `/kati/auto_news_distribute/{env}/slack-webhook-url` | SecureString | 任意 | Slack Incoming Webhook URL。複数チャネルはカンマ/セミコロン区切りで列挙可。空ならSlack送信スキップ |

**バリデーション**: `recipient-emails` と `slack-webhook-url` の両方が空の場合は起動エラー。

### 3.4 Bedrock 固定フォーマット保証

**【要決定】** 以下から選択：

| 方式 | メリット | デメリット |
|------|----------|------------|
| **A. Tool Use API**（推奨） | スキーマ強制、最も確実 | プロンプト書き方の制約あり |
| **B. JSON-in-prompt + Pydanticパース** | プロンプトが自由 | LLMが時々フォーマット崩す |
| **C. Structured Outputs**（未対応） | - | Bedrockは未サポート |

### 3.5 HTML テンプレート

| 項目 | 値 |
|------|-----|
| エンジン | Jinja2 |
| 配置場所 | `src/templates/news_email.html` |
| デザイン | 【要確認】レスポンシブ対応の有無、ブランディング |

### 3.6 CloudWatch Alarm + SNS

| 項目 | 値 |
|------|-----|
| メトリクス | Lambda Errors |
| しきい値 | 1 (即座にアラート) |
| 評価期間 | 5分 |
| アクション | SNS Topic にPublish |
| SNS購読 | 【要確認】管理者メールアドレス |

## 4. ディレクトリ構造

```
AutoNewsDistributionTool/
├── src/
│   ├── handlers/
│   │   └── distribute_news.py    # Lambdaハンドラー
│   ├── services/
│   │   ├── bedrock_client.py     # Bedrock呼び出し（Tool Use）
│   │   ├── ses_client.py         # SES送信
│   │   └── parameter_store.py    # Parameter Store取得
│   ├── models/
│   │   └── news.py               # Pydanticモデル（ニュース構造）
│   └── templates/
│       └── news_email.html       # Jinja2 HTMLテンプレート
├── tests/
│   ├── test_distribute_news.py
│   ├── test_bedrock_client.py
│   └── test_ses_client.py
├── infra/
│   └── template.yaml             # CloudFormation
├── docs/
│   └── design/
│       └── prompt.txt            # Bedrockに送るプロンプト
└── requirements.txt
```

## 5. タスク分解（Phase別）

### Phase 1: 設計・準備
- [x] **1.1** Bedrock出力スキーマ確定（`src/models/news.py`）— カチタス用カテゴリ + `katitas_relevance` 付き
- [x] **1.2** `docs/design/prompt.txt` 確認（ユーザーが事前用意済み）
- [x] **1.3** HTMLテンプレート（`src/templates/news_email.html`）— モバイル対応・業務ヒント強調デザイン

### Phase 2: コア実装
- [x] **2.1** Pydantic モデル作成（`src/models/news.py`）
- [x] **2.2** Parameter Store クライアント作成（`src/services/parameter_store.py` Slack URL対応・email任意化）
- [x] **2.3** Bedrock クライアント作成（`src/services/bedrock_client.py` Tool Use強制呼び出し + $ref インライン展開）
- [x] **2.4** SES クライアント作成（`src/services/ses_client.py` BCC運用）
- [x] **2.5** HTMLレンダリング処理（`src/services/html_renderer.py` Jinja2 + 自動エスケープ + カテゴリ色マップ）
- [x] **2.6** Lambda ハンドラー組み立て（`src/handlers/distribute_news.py` マルチチャネル対応）
- [x] **2.7** Slack クライアント作成（`src/services/slack_client.py` カテゴリ別Block Kit送信）

### Phase 3: テスト
- [x] **3.1** テストフィクスチャ（`tests/conftest.py`）
- [x] **3.2** モデルテスト（`tests/test_models.py`）
- [x] **3.3** Parameter Store テスト（`tests/test_parameter_store.py` moto使用）
- [x] **3.4** Bedrock テスト（`tests/test_bedrock_client.py` mock + $refインライン展開検証）
- [x] **3.5** SES テスト（`tests/test_ses_client.py` moto使用）
- [x] **3.6** Slack テスト（`tests/test_slack_client.py` urllib mock）
- [x] **3.7** HTML レンダラーテスト（`tests/test_html_renderer.py` XSSエスケープ含む）
- [x] **3.8** ハンドラー統合テスト（`tests/test_distribute_news.py` マルチチャネル分岐検証）

### Phase 4: インフラ
- [x] **4.1** CloudFormation/SAM テンプレート作成（`infra/template.yaml` Transform 適用）
- [x] **4.2** Lambda IAM Policies（Parameter Store / Bedrock / SES / KMS Decrypt 最小権限。SAMがロール自動生成）
- [x] **4.3** EventBridge Scheduler（`Events.ScheduleV2` 内包、cron + RetryPolicy 5回 + DLQ）
- [x] **4.4** SNS Topic + CloudWatch Alarm（Lambda Errors + DLQ ApproximateNumberOfMessagesVisible）
- [x] **4.5** Parameter Store 投入手順は `deploy-workflow.md` に記載
- [x] **4.6** SAM ベースのパッケージング手順（`docs/guides/lambda-packaging.md`）
- [x] **4.7** `samconfig.toml` で env別パラメータ管理、`infra/events/` にローカルinvoke用ペイロード配置

### Phase 5: デプロイ・検証
- [ ] **5.1** STG環境デプロイ
- [ ] **5.2** 手動トリガーで動作確認
- [ ] **5.3** アラート発火テスト
- [ ] **5.4** 本番環境デプロイ

## 6. 確定事項（2026-05-01）

| # | 項目 | 決定 |
|---|------|------|
| Q1 | Bedrock出力フォーマット保証 | **A. Tool Use API**（Converse APIの`toolConfig`） |
| Q2 | ニュース構造 | `NewsItem(title, summary, category) × 5件` |
| Q3 | 送信先 | 複数（Parameter Store StringList） |
| Q4 | アラート通知先 | 管理者メールアドレス（SNS購読） |
| Q5 | HTMLテンプレート | 自動生成（モバイル対応・読みやすさ優先） |
| Q6 | リトライ戦略 | **EventBridge Scheduler の RetryPolicy で最大5回**、5回失敗で SNS → 管理者メール通知 |
| Q7 | Bedrock モデル | リージョン: **ap-northeast-1（東京）**、Opus 4.7 cross-region inference profile（Parameter Storeで設定） |

## 6.1 リトライ戦略の詳細

```
EventBridge Scheduler (cron: 毎朝8時 JST)
  ├─ RetryPolicy:
  │   MaximumRetryAttempts: 5
  │   MaximumEventAgeInSeconds: 21600 (6時間)
  ├─ Target: Lambda (NewsDistribution)
  └─ DeadLetterConfig:
      Arn: SQS DLQ
              ↓ メッセージ到達
      [CloudWatch Alarm] (DLQメッセージ数 ≥ 1)
              ↓
      [SNS Topic] → 管理者メール
```

**Lambda 内部でのリトライ**: boto3 標準リトライ（適応的バックオフ、3回まで）を使用。Lambda関数全体の失敗時はEventBridge Schedulerが5回までリトライする。

## 7. 関連ドキュメント

- `docs/design/prompt.txt` - Bedrock プロンプト（Phase 1.2 で作成）
- `.claude/rules/deploy-workflow.md` - デプロイ手順
- `.claude/rules/infra-environment.md` - リソース情報（デプロイ後更新）

## 8. 変更履歴

| 日付 | 変更内容 |
|------|----------|
| 2026-05-01 | 初版作成（ドラフト） |
| 2026-05-01 | 要件確定（Q1〜Q7） |
| 2026-05-01 | Phase 1 完了（HTMLテンプレート / Pydanticモデル / sample HTML） |
| 2026-05-01 | Phase 2 完了（5サービス + ハンドラー実装） |
| 2026-05-01 | 要件追加: Slack配信機能（カテゴリ別 1メッセージ）。email送信は recipient-emails 空時にスキップ |
| 2026-05-01 | 要件追加: プロンプトを Parameter Store 管理に変更（ファイル読込廃止）。`docs/guides/prompt-management.md` 追加 |
| 2026-05-01 | 要件追加: summary 詳細化（200-800文字）、source_url フィールド追加、HTMLは CSS line-clamp で6行省略表示、Slackはタイトルをリンク化 |
| 2026-05-01 | source_url 要件厳格化: 個別記事URL必須・トップページ等は禁止。`prompt.txt` にも詳細要約と厳格URL条件を明記 |
| 2026-05-01 | Phase 3 完了: 7テストファイル（モデル/Parameter Store/Bedrock/SES/Slack/HTML/ハンドラー） |
| 2026-05-01 | Phase 4 完了: CloudFormation（Lambda + Scheduler + SQS DLQ + SNS + 2 Alarm）、デプロイガイド整備 |
| 2026-05-01 | デプロイ方式を SAM 化: `Transform: AWS::Serverless-2016-10-31` 化、`Events.ScheduleV2` で Scheduler を Function に内包、`samconfig.toml` で env別管理、events/ にテストペイロード配置、`resolve_s3=true` で S3 自動管理 |

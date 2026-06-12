# AutoNewsDistributionTool

毎朝 8:00 JST に Amazon Bedrock で生成した不動産ニュースを **メール（SES）と Slack** にマルチチャネル配信する、サーバーレス自動ニュース配信ツール。

---

## 目次

1. [これは何？（30秒概要）](#これは何30秒概要)
2. [アーキテクチャ](#アーキテクチャ)
3. [5分でセットアップ（ローカル開発）](#5分でセットアップローカル開発)
4. [ディレクトリ構造](#ディレクトリ構造)
5. [開発フロー](#開発フロー)
6. [テスト](#テスト)
7. [デプロイ](#デプロイ)
8. [運用・デバッグ](#運用デバッグ)
9. [設計上のポイント（読み飛ばし注意）](#設計上のポイント読み飛ばし注意)
10. [ドキュメント案内](#ドキュメント案内)

---

## これは何？（30秒概要）

| 項目 | 内容 |
|------|------|
| **目的** | 毎朝 8:00 JST にカチタスの実需中古住宅事業に関連する不動産ニュース 5 件を社内配信 |
| **ターゲットカテゴリ** | PropTech / 企業動向 / 法規制・政策 / マーケット・価格動向 / 海外不動産 / リフォーム関連 |
| **対象外** | マンション、投資用不動産 |
| **配信先** | HTML メール（SES, BCC 一斉送信）と Slack（カテゴリ別 1 メッセージ／Block Kit） |
| **AI** | Amazon Bedrock（Claude Opus 4.7 inference profile）+ Tool Use で構造化 JSON を強制 |
| **構成** | 完全サーバーレス（フロントエンド・DB なし） |

---

## アーキテクチャ

```
[EventBridge Scheduler]                              [SNS Topic]
   cron(0 23 * * ? *) UTC = JST 08:00                   ↑ アラート
        ↓                                                │
   ├─ retry x5 / DLQ ──────────────► [SQS DLQ] ─► [CloudWatch Alarm]
        ↓
[Lambda: auto-news-distribute-{env}]  (Python 3.12 / arm64 / 512MB / 300s)
   │
   ├─► [Parameter Store] /kati/auto_news_distribute/{env}/* で設定一括取得
   ├─► [Bedrock Converse API] Tool Use で NewsDigest スキーマ強制 → 5 件取得
   ├─► [SES v2] Jinja2 で HTML 生成 → BCC で受信者に一斉送信（任意）
   └─► [Slack Webhook] カテゴリ別 1 メッセージで Block Kit 送信（任意）
```

メール／Slack の片方が空なら自動でスキップ。**両方空なら起動時エラー**で無駄な Bedrock 呼び出しを防ぐ（`src/services/parameter_store.py:75`）。

---

## 5分でセットアップ（ローカル開発）

### 前提

| 必要なもの | バージョン目安 |
|-----------|-------------|
| Python | 3.12 (Lambda ランタイムと一致させる) |
| AWS SAM CLI | 1.130 以降（`ScheduleV2` 対応） |
| AWS CLI | 認証済み（profile か環境変数） |
| Docker Desktop | `sam local invoke` を使う場合のみ |

### 手順

```powershell
# 1. リポジトリ取得
cd C:\Users\<you>\Documents\repo\AutoNewsDistributionTool

# 2. Python 仮想環境
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip

# 3. 依存インストール（dev は本体含む）
pip install -r requirements-dev.txt

# 4. テストが通ることを確認（環境構築の最低限の動作確認）
pytest
```

> `pyproject.toml` に `pythonpath = ["."]` が設定されているので、**プロジェクトルートから `pytest` を起動**してください。`tests/` ディレクトリ内から起動すると import が解決できません。

---

## ディレクトリ構造

```
AutoNewsDistributionTool/
├── src/
│   ├── handlers/
│   │   └── distribute_news.py      # Lambda エントリポイント
│   ├── services/
│   │   ├── bedrock_client.py       # Bedrock Converse + Tool Use
│   │   ├── parameter_store.py      # SSM Parameter Store ローダ
│   │   ├── ses_client.py           # SES v2 BCC 送信
│   │   ├── slack_client.py         # Slack Webhook（urllib のみ）
│   │   └── html_renderer.py        # Jinja2 でメール HTML 生成
│   ├── models/
│   │   └── news.py                 # Pydantic: NewsItem / NewsDigest
│   └── templates/
│       ├── news_email.html         # Jinja2 テンプレート
│       └── news_email_sample.html  # ダミーデータでレンダリングしたサンプル
├── tests/                          # pytest（moto / mock）
├── infra/
│   ├── template.yaml               # SAM (Transform: Serverless-2016-10-31)
│   ├── samconfig.toml              # stg / prod 別パラメータ
│   └── events/                     # ローカル invoke 用ペイロード
├── docs/
│   ├── design/prompt.txt           # Bedrock に投げるプロンプト本文（正本）
│   ├── plans/                      # 実装計画
│   ├── guides/                     # 手順書（packaging / prompt 管理）
│   ├── issues/                     # P0–P3 × カテゴリで Issue 管理
│   └── INTEGRITY_CHECK.md          # 設計と実装の整合性
├── .claude/rules/                  # Claude Code 用ガバナンスルール
├── requirements.txt                # 本番 deps（バージョン完全固定）
├── requirements-dev.txt            # +pytest / moto
├── pyproject.toml                  # pytest 設定
└── CLAUDE.md                       # Claude Code 用プロジェクトガイド
```

### 命名規則

| 種別 | パターン | 例 |
|------|----------|-----|
| Lambda ハンドラー | `{動詞}_{対象}.py` | `distribute_news.py` |
| テストファイル | `test_{対象}.py` | `test_distribute_news.py` |
| CFn / SAM テンプレート | `template.yaml` | — |
| 設計書 | `NN_{トピック}.md` | `01_アーキテクチャ.md` |

---

## 開発フロー

### 新機能を追加するとき

1. **計画書を書く** — `docs/plans/YYYY-MM-DD-NN-{topic}.md`（小さな差分なら省略可）
2. **既存パターンを確認** — `src/services/` の他クライアントを参考に。`boto3.client(..., config=Config(retries={"max_attempts": 3, "mode": "standard"}))` で統一
3. **実装** — 1 ファイル 1 責務
4. **テスト追加** — `tests/test_*.py`。AWS は `moto` で、HTTP は `urllib.request` の monkeypatch でモック
5. **`pytest` がグリーン**を確認してコミット
6. **ドキュメント同時更新** — `CLAUDE.md` のドキュメント整合性ルール参照

### コードを読むときの起点

- まず `src/handlers/distribute_news.py` を読む（30 行程度。全体の流れがここに集約）
- 詳細は `src/services/*` を辿る
- スキーマは `src/models/news.py`（Pydantic）が単一情報源。ここを変えると Bedrock のレスポンス検証も自動更新される

---

## テスト

```powershell
# 全テスト
pytest

# 特定ファイルのみ
pytest tests/test_distribute_news.py

# 特定テスト関数
pytest tests/test_bedrock_client.py::test_inline_refs_expands_defs
```

`pyproject.toml` で `addopts = "-v --tb=short"` が指定済み。冗長出力＋短いトレースバックがデフォルト。

### モックの使い分け

| モック対象 | ライブラリ | 例 |
|-----------|----------|-----|
| AWS サービス（SSM/SES/Bedrock） | `moto` | `tests/test_parameter_store.py` |
| Bedrock のレスポンス | `unittest.mock` で `boto3.client` を差し替え | `tests/test_bedrock_client.py` |
| Slack Webhook | `urllib.request.urlopen` を monkeypatch | `tests/test_slack_client.py` |

---

## デプロイ

> ⚠️ **鉄則: STG で検証してから本番。** 詳細手順は **`.claude/rules/deploy-workflow.md`** を読むこと（このファイルに完全な手順が書かれている）。

### 最短コマンド

```powershell
cd infra

# テンプレート検証
sam validate --lint

# ビルド（arm64 wheel を自動取得）
sam build

# STG デプロイ
sam deploy --config-env stg

# 本番デプロイ（変更セット目視確認 → y）
sam deploy --config-env prod
```

### 初回デプロイ時に必ずやること

1. **SES の送信元アドレスを verify**（AWS コンソールから手動）
2. **CFn デプロイ後、`AlertEmailAddress` 宛に届く確認メールで購読を承認**（しないとアラートが来ない）
3. **Parameter Store に値を投入**（環境ごと）
   ```powershell
   $ENV="stg"
   aws ssm put-parameter --name /kati/auto_news_distribute/$ENV/bedrock-model-id --value "apac.anthropic.claude-opus-4-7-..." --type String --overwrite --region ap-northeast-1
   aws ssm put-parameter --name /kati/auto_news_distribute/$ENV/prompt --value (Get-Content docs/design/prompt.txt -Raw) --type String --overwrite --region ap-northeast-1
   aws ssm put-parameter --name /kati/auto_news_distribute/$ENV/recipient-emails --value "user1@katitas.jp,user2@katitas.jp" --type StringList --overwrite --region ap-northeast-1
   aws ssm put-parameter --name /kati/auto_news_distribute/$ENV/sender-email --value "news@katitas.jp" --type String --overwrite --region ap-northeast-1
   aws ssm put-parameter --name /kati/auto_news_distribute/$ENV/slack-webhook-url --value "https://hooks.slack.com/services/..." --type SecureString --overwrite --region ap-northeast-1
   ```
4. **動作確認** — `aws lambda invoke --function-name auto-news-distribute-stg --payload '{}' --cli-binary-format raw-in-base64-out response.json`

### 環境構成

| 環境 | スタック名 | 配信先 | 用途 |
|------|-----------|-------|------|
| 開発 | — | — | `pytest` / `sam local invoke` |
| STG | `auto-news-stg` | テスト受信者 | 統合テスト |
| 本番 | `auto-news-prod` | 本番受信者 | プロダクション配信 |

---

## 運用・デバッグ

### ローカルで Lambda を動かす（実 AWS を呼ぶ）

```powershell
cd infra
sam local invoke DistributeNewsFunction --event events/scheduled.json --parameter-overrides Environment=stg
```

⚠️ ローカルでも **実 Bedrock / SES / Slack を呼び出す**。STG リソースに対して実行すること。

### 本番ログを追う

```powershell
sam logs --stack-name auto-news-prod --tail
```

### よくあるトラブル

| 症状 | 原因 | 対処 |
|------|------|------|
| `ImportError: pydantic_core` | x86_64 wheel が混入 | `infra/.aws-sam/` を削除 → `sam build --use-container` |
| `Task timed out after 300s` | Bedrock 応答遅い | `template.yaml` の `Globals.Function.Timeout` を延長（最大 900s） |
| `AccessDeniedException` (Bedrock) | モデル ARN が IAM ポリシーと不一致 | `BedrockModelArn` パラメータ確認 |
| `MessageRejected` (SES) | 送信元未検証 | SES コンソールで identity verify |
| Slack `invalid_token` | Webhook URL が無効 | Slack 側で再生成 → Parameter Store 更新 |
| `recipient-emails と slack-webhook-url の両方が空` | 設定漏れ | どちらか片方は必ず設定 |
| `必須パラメータ prompt が未設定` | Parameter Store に投入してない | デプロイ手順 3. を実施 |

### ロールバック

```powershell
# コードを戻す
git checkout <過去の commit>
cd infra
sam build
sam deploy --config-env prod

# 緊急時: スケジュール無効化（Lambda は残すが起動を止める）
aws scheduler update-schedule --name auto-news-daily-prod --state DISABLED --region ap-northeast-1
```

---

## 設計上のポイント（読み飛ばし注意）

新メンバーが「なぜこうなっている？」と詰まりやすい設計判断を残す。

### 1. Bedrock からの構造化 JSON 取得は **Tool Use 一択**

`src/services/bedrock_client.py` は Converse API の `toolConfig` で `submit_news_digest` ツールを 1 つだけ定義し、`toolChoice` で強制呼び出ししている。**プレーンテキスト返答はあり得ない**前提で実装している。

理由: JSON-in-prompt 方式は LLM が形式を崩したときに復旧不可能。Tool Use ならスキーマで弾ける。

### 2. Pydantic の `$defs/$ref` は **手動でインライン展開**

`_inline_refs()` 関数で `model_json_schema()` の出力を再帰展開している。Bedrock の `inputSchema` は `$ref` を解釈できないため。

### 3. SES は **BCC 運用** で送信元自身を `To` に置く

`src/services/ses_client.py:28-37`。プライバシー保護のため、受信者同士のメールアドレスを開示しない設計。

### 4. Slack はカテゴリ別に **1 メッセージ／カテゴリ**

`src/services/slack_client.py:_group_by_category`。Block Kit の制限と読みやすさのバランス。**部分失敗時のリトライで重複送信が起こりうる**（冪等性は未保証）— 現状要件では許容範囲。

### 5. プロンプトは **コードに含めず Parameter Store**

`docs/design/prompt.txt` が Git 管理の正本。デプロイは `aws ssm put-parameter` で別途投入。**プロンプト変更にコードデプロイ不要**にするための設計。詳細: `docs/guides/prompt-management.md`。

### 6. 失敗通知は **2 段構え**

- Lambda 内のエラー → CloudWatch Alarm（Lambda Errors ≥ 1）→ SNS → 管理者メール
- EventBridge Scheduler が 5 回リトライしても失敗 → DLQ（SQS）→ Alarm → SNS → 管理者メール

両方が SNS に集約されるので **アラートメールが来たらまず CloudWatch Logs を見る**。

---

## ドキュメント案内

| 知りたいこと | 見るファイル |
|-------------|-------------|
| プロジェクトの背景・要件 | `docs/plans/2026-05-01-01-news-distribution-implementation.md` |
| デプロイ手順（完全版） | `.claude/rules/deploy-workflow.md` |
| パッケージング・ローカル開発 | `docs/guides/lambda-packaging.md` |
| プロンプト変更手順 | `docs/guides/prompt-management.md` |
| インフラリソース台帳 | `.claude/rules/infra-environment.md` |
| インフラ変更ガバナンス | `.claude/rules/infra-governance.md` |
| ドキュメント運用ルール | `.claude/rules/doc-governance.md` |
| 設計と実装の整合性 | `docs/INTEGRITY_CHECK.md` |
| 既知の課題 | `docs/issues/` 配下 |
| Claude Code 用ガイド | `CLAUDE.md` |

---

## ライセンス・運用ルール

- master への直接プッシュ禁止、PR ベース開発必須
- 依存パッケージのバージョンは **完全固定**（`^` や `~` 禁止）
- インフラを変更したら **`.claude/rules/infra-environment.md` を必ず更新**
- 実装と同時にドキュメント更新（「あとで」は禁止）

詳細は `CLAUDE.md` および `.claude/rules/` 配下を参照。

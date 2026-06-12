# デプロイワークフロー

AWS SAM CLI を使ったデプロイ手順と必須ルール。

---

## 鉄則

1. **STG/開発環境で検証してから本番** — 本番デプロイはSTG検証完了後のみ
2. **依存パッケージのバージョンは完全固定** — `"1.0.0"` であり `"^1.0.0"` ではない
3. **デプロイ後は必ず `infra-environment.md` を更新** — リソース情報の陳腐化を防ぐ
4. **arm64 アーキテクチャ対応の wheel をパッケージ** — `sam build` が自動処理。問題時は `--use-container`

---

## 環境構成

| 環境 | 用途 | デプロイコマンド |
|------|------|-------------|
| 開発 | ローカル単体テスト | `pytest` / `sam local invoke` |
| STG | 統合テスト・動作確認 | `sam deploy --config-env stg` |
| 本番 | プロダクション配信 | `sam deploy --config-env prod` |

`samconfig.toml` で環境別パラメータ管理。スタック名・パラメータは samconfig.toml 内に集約。

---

## AWS アカウント / リージョンの指定方法

**事故防止の原則: 「どの AWS アカウントに対して操作しているか」を毎コマンド明示する**

本番とSTGで同一アカウントを使う運用でも、全社共有のSandboxを誤って指定する事故を防ぐため、デフォルトプロファイルへの依存を避けて毎回指定する。

### A. AWS Profile 方式（推奨）

`~/.aws/config` と `~/.aws/credentials` に環境別プロファイルを切り、コマンド実行時に明示する。

`~/.aws/config` 例:

```ini
[profile katitas-stg]
region = ap-northeast-1
sso_session = katitas
sso_account_id = 111111111111
sso_role_name = DeveloperPowerUser

[profile katitas-prod]
region = ap-northeast-1
sso_session = katitas
sso_account_id = 222222222222
sso_role_name = DeployRole
```

**SSO ログイン:**

```powershell
aws sso login --profile katitas-stg
```

**SAM 実行（PowerShell）:**

```powershell
$env:AWS_PROFILE = "katitas-stg"
sam deploy --config-env stg
```

**または1コマンドで:**

```powershell
sam deploy --config-env stg --profile katitas-stg
aws ssm put-parameter ... --profile katitas-stg
```

### B. アクセスキー直指定（CI/CD のみ）

```powershell
$env:AWS_ACCESS_KEY_ID = "AKIA..."
$env:AWS_SECRET_ACCESS_KEY = "..."
$env:AWS_DEFAULT_REGION = "ap-northeast-1"
sam deploy --config-env stg
```

> ローカル運用では避ける（鍵漏洩リスク）。GitHub Actions 等の OIDC 連携が望ましい。

### 操作対象アカウントの確認

**毎回コマンド実行前に必ず確認:**

```powershell
aws sts get-caller-identity --profile katitas-stg
# Account / Arn / UserId が想定通りか目視
```

### よくある事故パターン

| 症状 | 原因 | 対策 |
|------|------|------|
| Prod に STG 値が乗る | `AWS_PROFILE` が古いまま | デプロイ前に `aws sts get-caller-identity` を必ず実行 |
| `Could not connect to the endpoint URL` | リージョン未指定 | `--region` 明示 or プロファイルに `region` 設定 |
| `ExpiredToken` | SSO セッション切れ | `aws sso login --profile xxx` で再認証 |

---

## 初回デプロイ手順

### 0. 前提準備

- AWS CLI 認証済み（**プロファイル別に SSO ログイン済み**）
- SAM CLI インストール済み（`sam --version` で 1.130 以降）
- Docker Desktop（`sam local invoke` で使う場合）
- SES の送信元アドレスが verify 済み（CloudFormation の `SenderEmailIdentity` で IaC 化済み。後述）
- Slack Webhook URL を取得済み（任意）
- **対象アカウント確認**: `aws sts get-caller-identity --profile {target}` で表示される Account ID が想定通りであること

### 1. テンプレート検証 + ビルド

```bash
cd infra
sam validate --lint
sam build
```

`sam build` が依存解決と arm64 wheel パッケージングを自動実行。
S3 バケットも `resolve_s3 = true` 設定で SAM が自動管理（手動作成不要）。

### 2. ローカル動作確認（オプション）

```bash
# 実本番と同じ空ペイロードで実行
sam local invoke DistributeNewsFunction --event events/scheduled.json --parameter-overrides Environment=stg
```

⚠️ Bedrock/SES/Slack は実環境を呼ぶため、STG リソースに対して検証する。

### 3. CloudFormation デプロイ（STG）

```bash
sam deploy --config-env stg
```

初回デプロイ時、SAM が自動で `aws-sam-cli-managed-default-samclisourcebucket-*` バケットを作成。

### 4. SNS サブスクリプション確認

CFn デプロイ後、`AlertEmailAddress` 宛に AWS から確認メールが届く。
**メール内のリンクをクリックして購読を承認**しないとアラートが届かない。

### 5. Parameter Store に値を投入

```bash
ENV=stg

aws ssm put-parameter --name /kati/auto_news_distribute/${ENV}/bedrock-model-id \
  --value "apac.anthropic.claude-opus-4-7-..." \
  --type String --overwrite --region ap-northeast-1

aws ssm put-parameter --name /kati/auto_news_distribute/${ENV}/prompt \
  --value "$(cat docs/design/prompt.txt)" \
  --type String --overwrite --region ap-northeast-1

aws ssm put-parameter --name /kati/auto_news_distribute/${ENV}/recipient-emails \
  --value "user1@katitas.jp,user2@katitas.jp" \
  --type StringList --overwrite --region ap-northeast-1

aws ssm put-parameter --name /kati/auto_news_distribute/${ENV}/sender-email \
  --value "news@katitas.jp" \
  --type String --overwrite --region ap-northeast-1

aws ssm put-parameter --name /kati/auto_news_distribute/${ENV}/slack-webhook-url \
  --value "https://hooks.slack.com/services/..." \
  --type SecureString --overwrite --region ap-northeast-1

# Web 検索 API（agentic loop 用）
# プロバイダ（任意。未設定時はデフォルト brave）
aws ssm put-parameter --name /kati/auto_news_distribute/${ENV}/news-search-provider \
  --value "brave" \
  --type String --overwrite --region ap-northeast-1

# API キー（必須）。Brave なら BSA-..., Tavily なら tvly-...
aws ssm put-parameter --name /kati/auto_news_distribute/${ENV}/news-search-api-key \
  --value "BSA-..." \
  --type SecureString --overwrite --region ap-northeast-1

# (任意) 1起動あたりの検索上限を上書き。未設定なら provider 既定値（brave=50, tavily=25）。
# 有料プラン移行時にここを引き上げるだけで本番反映可能。
# aws ssm put-parameter --name /kati/auto_news_distribute/${ENV}/news-search-max-per-invocation \
#   --value "50" \
#   --type String --overwrite --region ap-northeast-1
```

> Brave / Tavily の API キー取得手順と予算保護の仕組みは [docs/guides/news-search-provider.md](../docs/guides/news-search-provider.md) を参照。

### 6. 動作確認

```bash
# 手動でLambdaを起動
aws lambda invoke \
  --function-name auto-news-distribute-stg \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/response.json

# ログ確認
sam logs --stack-name auto-news-stg --tail
```

### 7. アラート発火テスト

意図的に失敗させて SNS アラートが届くことを確認：

```bash
# Bedrockモデルを一時的に無効値に変更
aws ssm put-parameter --name /kati/auto_news_distribute/stg/bedrock-model-id \
  --value "invalid-model" --type String --overwrite

# Lambda 起動 → 失敗 → アラート受信
aws lambda invoke --function-name auto-news-distribute-stg --payload '{}' \
  --cli-binary-format raw-in-base64-out /tmp/r.json

# 検証後、元に戻す
aws ssm put-parameter --name /kati/auto_news_distribute/stg/bedrock-model-id \
  --value "{元の値}" --type String --overwrite
```

---

## 本番デプロイ手順

**前提: STG検証が完了していること**

```bash
cd infra
sam build
sam deploy --config-env prod
```

`samconfig.toml` の `[prod.deploy.parameters]` で `confirm_changeset = true` を指定済み。
変更セット内容を**必ず目視確認**してから `y` で承認。

**Parameter Store** は環境ごとに別々のパスなので、本番用に再投入が必要（手順 5 を `ENV=prod` で実行）。

---

## ロールバック手順

### Lambda コードのロールバック

```bash
# 過去のバージョンに戻す（CloudFormation の差分デプロイ）
git checkout {過去のcommit}
cd infra
sam build
sam deploy --config-env prod
```

### 緊急時: スケジュール無効化

```bash
aws scheduler update-schedule \
  --name auto-news-daily-prod \
  --state DISABLED \
  --region ap-northeast-1
```

---

## デプロイ後の必須アクション

| 変更内容 | 必須アクション |
|----------|---------------|
| IaCデプロイ | `infra-environment.md` のスタック最終更新日を更新 |
| 手動CLI操作 | コマンドと理由を `infra-environment.md` 手動変更履歴に記録 |
| 新規リソース作成 | `infra-environment.md` に追記 |
| 問題発見 | `docs/issues/` にIssue作成 |
| プロンプト変更 | `docs/guides/prompt-management.md` の手順で Parameter Store 更新 |

---

## 禁止事項

1. **STG未検証での本番デプロイ**
2. **依存パッケージのバージョンrange指定**（`^` や `~` 禁止）
3. **記録なしの手動変更** — 必ずコマンドと理由を記録
4. **ドキュメント更新なしのデプロイ** — 最終更新日は必ず更新
5. **`samconfig.toml` の認証情報埋め込み** — Webhook URLなどは Parameter Store のみで管理

---

## インシデント履歴

<!-- デプロイ起因の障害が発生したら、ここに原因・影響・対策を記録する -->

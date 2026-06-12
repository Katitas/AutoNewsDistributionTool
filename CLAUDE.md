# CLAUDE.md

このファイルはClaude Codeがこのリポジトリで作業する際のガイダンスを提供する。
応答は日本語で行う。

## セキュリティ

以下のファイルはClaude Codeからアクセスできない：
- `.env.local` - APIキー、シークレットを含む
- `*credentials*`, `*.pem`, `*.key` - 認証情報

## プロジェクト概要（WHY）

**ビジネス目的**: 毎日早朝にAmazon Bedrockから最新ニュースを取得・要約し、Amazon SESでユーザーにメール配信する自動ニュース配信システム

**ユーザー**: システム管理者（配信設定・管理）とエンドユーザー（ニュースメール受信者）

## アーキテクチャ（WHAT + WHY）

EventBridgeスケジューラーが毎朝Lambda（Python）をトリガーし、BedrockでAIによるニュース収集・要約を行い、SESでメール送信する。インフラ全体はCloudFormationで管理。フロントエンドなし、DBなしのサーバーレス構成。

## 技術スタック（WHAT）

| 領域 | 技術 |
|------|------|
| バックエンド | Python (AWS Lambda) |
| IaC | AWS CloudFormation |
| イベントトリガー | Amazon EventBridge |
| AI/ML | Amazon Bedrock |
| メール配信 | Amazon SES |
| インフラ | AWS |

## 検証コマンド（HOW）

| 対象 | コマンド |
|------|---------|
| テスト | `pytest` |

## ドキュメント参照

| 用途 | パス |
|------|------|
| 設計書 | `docs/design/` |
| 実装計画 | `docs/plans/` |
| 手順書 | `docs/guides/` |
| Issue管理 | `docs/issues/`（P0-P3 x カテゴリ） |
| 整合性チェック | `docs/INTEGRITY_CHECK.md` |

## 自動読み込みルール（.claude/rules/）

- `project-structure.md` — コード構造マップ・設計書対応表
- `doc-governance.md` — ドキュメント配置・命名・CLAUDE.md肥大化防止
- `output-format.md` — ピラミッド構造（結論→理由→詳細）
- `execution-checklist.md` — 実装フェーズのチェックリスト
- `implementation-readiness.md` — 実装前の必須確認
- `plan-to-execution.md` — 計画→タスク分解→実行フロー
- `session-management.md` — コンテキスト管理・失敗パターン回避
- `infra-environment.md` — AWSリソース一覧・環境情報
- `infra-governance.md` — インフラ変更時のガバナンスルール
- `deploy-workflow.md` — CloudFormationデプロイ手順

## コンパクション指示

`/compact` 時に保持: 変更ファイルリスト、テスト結果、未解決TODO

## Git運用

- masterへの直接プッシュ禁止、PRベース開発必須

## デプロイ

デプロイ前に `.claude/rules/deploy-workflow.md` を参照。鉄則: STG検証後に本番デプロイ。

## ドキュメント整合性（必須）

- 設計書にない変更 → 該当ドキュメントに追記
- 実装フェーズ開始時: `INTEGRITY_CHECK.md` の現在値を確認
- 実装フェーズ完了時: `INTEGRITY_CHECK.md` の該当行を更新
- **ドキュメント更新は実装と同時**（「あとで」は禁止）

## Issue管理（必須）

課題発見 → 即座に `docs/issues/{priority}/` にMD作成。暫定対応 → Issue記録。詳細: `doc-governance.md`

# 发现的问题

## 新发现的问题
- slack_webhook_url是复数的，用分号或者逗号分割
- parameter store取全量数据是否有必要，只获取/kati/auto_news_distribute开头的就够了
- 没有stg环境，直接部署在prd，所以需要一个参数来控制是否执行代码

## ✅ 已解决（2026-05-06）

- [x] **#1** 实际调用的获取新闻的tool function(submit_news_digest)没有定义和编写
  - 解决: `submit_news_digest` 是终端工具（Bedrock 输出 → Pydantic 验证 → 返回），新增了 `search_real_news` 实搜索工具，由 `bedrock_client.py:run_news_agent()` 内部 dispatch 处理
  - 影响文件: `src/services/bedrock_client.py`, `src/services/news_search.py`
- [x] **#2** bedrock_client.py中BedrockToolUseError没有实装
  - 解决: 添加 `stop_reason` / `content_blocks` / `validation_errors` 字段保存调试信息
  - 影响文件: `src/services/bedrock_client.py`
- [x] **#3** slack_client.py中SlackSendError没有实装
  - 解决: 添加 `category` / `status_code` / `response_body` 字段
  - 影响文件: `src/services/slack_client.py`
- [x] **#4** 实际代码和测试代码的function没有写注释
  - 解决: 主要 service 函数和测试类全部添加 Google Style docstring
  - 影响文件: `src/services/*.py`, `src/handlers/*.py`, `tests/*.py`
- [x] **#5** 需求变更: bedrock 自主决定关键词调用 search 工具，结果分发为 SES 用 HTML JSON 和 Slack 用 Block Kit JSON
  - 解决: 实现 Agentic Tool Use Loop（多轮 search → submit），SES/Slack 格式分发已通过既存的 `html_renderer.py` / `slack_client.py` 实现
  - Tavily 1000/月无料枠保护: 1 invocation 上限 25 次（30日 = 750 次/月，25% 缓冲）
  - 影响文件: `src/services/bedrock_client.py`, `src/services/news_search.py`, `docs/design/prompt.txt`
- [x] **#6** bedrock_model_id能填什么没有指引
  - 解决: 创建 `docs/guides/bedrock-model-selection.md`，列出 APAC inference profile ID 和 CLI 查询命令
- [x] **#7** 部署时怎么指定aws环境没有指引
  - 解决: `.claude/rules/deploy-workflow.md` 增加「AWS アカウント / リージョンの指定方法」章节，覆盖 SSO / Profile / 防呆检查
- [x] **#8** 这个项目使用aws服务所有的成本都需要通过赋予一个tag来在aws上进行统计和查看
  - 解决: `template.yaml` 增加 `ProjectTag` / `CostCenterTag` 参数，`samconfig.toml` 通过 `tags = ...` 让 CFn 自动传播到所有支持 Tag 的资源；LogGroup / SQS / SNS 显式 Tags 标注
  - ⚠️ 待用户确认: 标签命名是否符合 katitas 组织标准（默认 Project / CostCenter / Environment / ManagedBy）
- [x] **#9** template.yaml中没有关于SESIdentity之类的设置
  - 解决: 新增 `AWS::SES::EmailIdentity` 资源 + `SenderEmailAddress` 参数，IAM 的 SES Resource 收紧到该 identity ARN（`ses:FromAddress` Condition）
  - 影响文件: `infra/template.yaml`

---

## 🔧 残课题（部署/运维侧）

- [ ] Tavily API 密钥获取 → Parameter Store 投入（`/kati/auto_news_distribute/{env}/news-search-api-key`）
- [ ] 标签命名（`samconfig.toml` 的 `tags = ...`）调整为 katitas 组织标准
- [ ] STG 部署后手动 invoke 验证 agentic loop 实际行为
- [ ] SES Email Identity 验证邮件点击确认（部署后 AWS 自动发送）

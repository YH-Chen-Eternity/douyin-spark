# 贡献指南

感谢你愿意参与「抖音火花助手」的建设！请在提交代码前阅读本文。

## 一、参与方式

- 提交 Bug：使用 [Bug Report](.github/ISSUE_TEMPLATE/bug_report.md) 模板。
- 提交新功能建议：使用 [Feature Request](.github/ISSUE_TEMPLATE/feature_request.md) 模板。
- 提交代码：Fork 仓库 → 新建分支 → 修改 → 提交 Pull Request。

## 二、分支规范

从 `main` 切出分支，分支名建议使用以下前缀：

| 前缀 | 用途 | 示例 |
| --- | --- | --- |
| `feat/` | 新功能 | `feat/chat-selector` |
| `fix/` | Bug 修复 | `fix/login-timeout` |
| `docs/` | 文档更新 | `docs/readme-faq` |
| `refactor/` | 重构（不改变行为） | `refactor/driver` |
| `chore/` | 构建、依赖、杂项 | `chore/bump-flask` |

## 三、提交信息规范

采用 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/)：

```
<type>(<scope>): <简短描述>

<可选正文>
```

常用 type：`feat`、`fix`、`docs`、`refactor`、`test`、`chore`。

示例：

```
fix(driver): 修复新版 /chat 页面会话列表匹配失败
docs(readme): 补充 OTP 配置说明
```

## 四、代码要求

- Python 代码遵循 PEP 8，建议使用 4 空格缩进，保持与现有风格一致。
- 页面选择器优先放入 `app/drivers/selectors.py` 的 `DEFAULTS`，并支持外部覆盖，避免硬编码。
- 新增依赖请同步更新 `requirements.txt`，并说明用途。
- 涉及浏览器操作的改动，请在本地用 `SPARK_DRIVER=mock` 或试运行模式验证。
- 不要引入与功能无关的大规模格式化改动，便于 Review。

## 五、Pull Request 要求

1. 描述清楚改动目的、实现方式与验证步骤。
2. 关联相关 Issue（如有），例如 `Closes #12`。
3. 确认没有提交任何敏感信息：
   - 不要提交 `data/`、`.env`、Cookie、Token、密码、手机号、真实内网地址；
   - 代码与文档中的配置一律使用占位符。
4. 如有界面改动，建议附上截图。
5. 保持单个 PR 聚焦，一个 PR 只做一件事。

## 六、安全与合规

- 请勿提交用于绕过平台风控、抓取用户隐私数据的代码。
- 请勿在 Issue / PR 中粘贴真实 Cookie、登录态或账号信息。
- 发现安全问题时，请按 [SECURITY.md](SECURITY.md) 私下报告，不要公开 Issue。

## 七、许可证

本项目采用 [Apache License 2.0](LICENSE) 许可证。
你提交的贡献将以相同的许可证授权，提交 PR 即表示你同意这一点。

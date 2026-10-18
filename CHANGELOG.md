# Changelog

本文件格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.1.1] - 2026-10-18

安全修复版本。

### Security

- 修复 OTP 二次验证可被绕过的问题：会话 Cookie 使用固定的默认 `SECRET_KEY`，任何人都能伪造「OTP 已通过」的会话。现在启用 OTP 时必须显式设置 `SECRET_KEY`，否则拒绝启动；未启用 OTP 时生成随机临时密钥。
- `docker-compose.yml` 改为强制从 `.env` 读取 `SECRET_KEY`（缺失时明确报错），`.env.example` 给出生成方式。
- 增加基础安全响应头：`X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`。
- 升级 Flask 到 3.1.3，修复 CVE-2026-27205（部分会话访问路径缺少 `Vary: Cookie`，在有缓存代理时可能泄露用户相关响应）。

### Changed

- 部署提示中补充端口暴露风险说明，建议只绑定内网地址并避免公网暴露。

## [0.1.0] - 2026-10-17

首个开源版本。将内部使用的抖音续火花工具整理为规范的开源项目。

### Added

- 完整的 Web 管理界面：账号状态、扫码/短信/Cookie 三种登录方式、好友勾选、定时任务、消息池、运行日志。
- 双账号托管，账号之间数据库与浏览器 Profile 完全隔离。
- APScheduler 每日定时任务，支持多个时间点、随机抖动、试运行模式。
- 基于 Playwright 的真实浏览器驱动，支持扫码登录与私信发送。
- 新版抖音网页版私信页（`/chat`）适配：会话列表、聊天输入框与发送按钮的选择器。
- 内置 TOTP（RFC 6238）二次验证，保护管理界面。
- 页面选择器支持通过 `/data/selectors.json` 外部覆盖，改版时无需改代码。
- Dockerfile 与 docker-compose 部署方案，支持 NAS 运行（Xvfb + 有头浏览器）。
- 开源配套文件：Apache License 2.0 `LICENSE`、`NOTICE`、`README`、`CONTRIBUTING`、`SECURITY`、`CODE_OF_CONDUCT`、GitHub Issue/PR 模板与基础 CI。

### Changed

- 私信链路迁移到新版 `/chat` 页面，移除了已下线的 `im-entry` / `im-dialog` 选择器与 im 模块注入逻辑。
- 定时任务开始前增加登录态预检，失效时立即中止并给出明确提示，不再长时间空跑。
- 扫码登录改为等待二维码图片真正渲染完成后再截图，避免偶发「二维码截图失败」。

### Fixed

- 修复私信页面加载超时、未找到会话等在新版页面下的失效问题。
- 修复发送前可能残留上一次草稿、导致内容拼接的问题。
- 修复日志时间与容器时区不一致的问题。

### Security

- 移除源码与配置中的真实密钥、密码等敏感信息，统一改为环境变量与占位符。
- 增加 `.gitignore`，排除 `data/`、`.env`、运行时日志、浏览器 Profile 等敏感文件。

[Unreleased]: https://github.com/YH-Chen-Eternity/douyin-spark/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/YH-Chen-Eternity/douyin-spark/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/YH-Chen-Eternity/douyin-spark/releases/tag/v0.1.0

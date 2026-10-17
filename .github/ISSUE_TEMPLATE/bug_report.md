name: Bug Report
description: 提交一个 Bug，帮助我们复现并修复问题
title: "[Bug] "
labels: ["bug"]
body:
  - type: markdown
    attributes:
      value: |
        感谢反馈！提交前请先搜索是否已有相同 Issue。

        ⚠️ **安全提醒**：请勿粘贴真实 Cookie、`sessionid`、TOTP 密钥、手机号、密码或完整内网地址。
        涉及登录态的内容请打码或确认已失效。

  - type: textarea
    id: what-happened
    attributes:
      label: 问题描述
      description: 发生了什么？期望的行为是什么？
      placeholder: 简要描述问题现象与期望结果
    validations:
      required: true

  - type: textarea
    id: steps
    attributes:
      label: 复现步骤
      description: 请尽量给出最小复现步骤
      placeholder: |
        1. 部署方式（Docker / 本地）
        2. 操作步骤
        3. 出现问题的位置
    validations:
      required: true

  - type: textarea
    id: logs
    attributes:
      label: 相关日志
      description: 请粘贴**已脱敏**的日志（删除 Cookie、Token、手机号、内网地址等）
      render: shell

  - type: input
    id: version
    attributes:
      label: 版本 / 提交
      placeholder: 例如 v0.1.0 或 commit hash

  - type: dropdown
    id: deploy
    attributes:
      label: 部署方式
      options:
        - Docker / docker compose
        - 本地 Python 运行
        - 其他（请在问题描述中说明）

  - type: textarea
    id: env
    attributes:
      label: 运行环境
      placeholder: |
        操作系统：
        Python 版本：
        Docker 版本：
        是否使用 NAS：
        驱动模式（playwright / mock）：

name: Feature Request
description: 提出新功能或改进建议
title: "[Feature] "
labels: ["enhancement"]
body:
  - type: markdown
    attributes:
      value: |
        感谢建议！请描述清楚使用场景与期望效果。

        ⚠️ 请勿在 Issue 中粘贴真实账号、Cookie、Token 等敏感信息。

  - type: textarea
    id: background
    attributes:
      label: 使用场景
      description: 你在什么场景下需要这个功能？
      placeholder: 例如：希望支持更多账号、按星期配置任务等
    validations:
      required: true

  - type: textarea
    id: solution
    attributes:
      label: 期望的解决方案
      description: 你希望项目如何实现它？
    validations:
      required: true

  - type: textarea
    id: alternatives
    attributes:
      label: 考虑过的替代方案
      description: 是否有其他实现方式或临时规避手段？

  - type: checkboxes
    id: checks
    attributes:
      label: 确认事项
      options:
        - label: 我已搜索过现有 Issue，确认没有重复建议
          required: true
        - label: 我理解本项目仅用于学习交流，且不保证功能长期可用
          required: true

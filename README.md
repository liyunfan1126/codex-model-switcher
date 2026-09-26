# codex-model-switcher

一个用于切换 Codex 第三方模型配置的小工具。

主要用于简化 Codex 在不同 API 服务、模型和配置之间的切换过程，减少手动修改配置文件的操作。

工具数据存储在本地。

当前版本：**v1.6**

---

## 功能介绍

- 快速切换 Codex 使用的模型
- 支持配置第三方 API 服务
- 支持自定义 API Base URL
- 支持填写和管理模型名称
- 减少手动修改 Codex 配置文件的操作
- 适合需要在多个模型或 API 服务之间频繁切换的场景

---

## 使用场景

例如你同时使用多个兼容 OpenAI API 格式的模型服务：

```text
Provider A
├── model-a
├── model-b
└── model-c

Provider B
├── model-x
└── model-y

# Cursor + SubAPI 排障与方案演变

## 方案对比（便于回看）

| 方案 | Base URL | API Key | 上游 | 计费 |
|------|----------|---------|------|------|
| **当前（记录）** | `https://subapi.aigcfast.com/cursor/v1` | SubAPI `sk-...` | 8327 → New API :3000 | SubAPI 日志/quota |
| 方案1（历史） | `/cursor/v1` | CPA `tjw` | Nginx → :8317 CPA | 不走 SubAPI 令牌 |
| 普通 SubAPI | `https://subapi.aigcfast.com/v1` | `sk-...` | New API | SubAPI；Cursor 易 `messages` 错误 |
| CPA 直连 | `https://api.aigcfast.com/v1` | `tjw` | CPA | CPA 侧 |

用户选择：**SubAPI 分发 + Cursor 兼容**，即上表第一行。

## ERROR_BAD_USER_API_KEY

特征：

- Cursor 堆栈里 `ERROR_BAD_USER_API_KEY`、`Unauthorized User Openai API key`
- 同一时间 VPS：`journalctl -u subapi-cursor-compat` **无**对应请求；`access.log` **无** `/cursor/v1`

结论：请求未到达 SubAPI，多为 Cursor 配置/校验阶段失败。

处理：

1. 删除并重新粘贴 `sk-...`
2. 确认 Override URL 为 `/cursor/v1`
3. 避免同时启用官方 OpenAI 路径覆盖自定义 Base

## field messages is required

- 请求到了 New API 的 `/v1/chat/completions`，body 无 `messages`
- Cursor 用了 **`/v1` 而非 `/cursor/v1`**

## Agent 不写文件 / 无限调技能

- 兼容层必须把 Responses 的 `function_call`、`function_call_output` 转成 Chat 的 `tool_calls` 与 `role: tool`
- 若曾把 Cursor 流量转到 `/v1/responses` 且只做文本 SSE 转换，会出现「说要建文件但没建」

## reasoning_effort（gpt-5.5 xhigh）

链路：Cursor → `/cursor/v1` → New API → CPA。CPA `config.yaml` 可能对 `gpt-5.5` 固定 `reasoning.effort: medium`，会覆盖客户端 `xhigh`。需在 CPA 改配置或单独模型别名，与 Cursor Base URL 无关。

## 生图

- `gpt-image-2` 在 SubAPI：**仅** `POST /v1/images/generations`
- Cursor 选 `gpt-image-2` 走对话 → 503，**不是** Cursor 兼容层能自动转（除非另做 image sidecar，未采用）
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

## call_id string too long（max 64）

上游/New API Responses 校验：

```text
Invalid 'input[N].call_id': string too long. Expected maximum length 64, but got 83
```

- **原因**：Cursor Agent 多轮 tool 时 `input[]` 里 `function_call` / `function_call_output` 的 `call_id` 可能超过 64 字符；8327 若原样转发会 400。
- **修复**（8327 `subapi-cursor-compat`）：`normalize_call_id` + `normalize_responses_input`，对所有 POST JSON 的 `input` 数组在转发前截断为稳定 `call_<sha256>`（≤64）。
- **处理**：`systemctl restart subapi-cursor-compat`；新开 Agent 会话再试。

## Context Usage 0% / 被重置

- Cursor Context Usage 面板不等价于服务端 `raw_len`。服务端可能看到 174KB～1.1MB，面板仍显示 0%。
- 本地反编译确认 UI 主要由 `conversationState.tokenDetails.usedTokens/maxTokens` → `contextUsagePercent/contextTokensUsed/contextTokenLimit` 驱动。
- OpenAI-compatible usage 仍会影响递增统计，但必须按标准流式格式输出：**只在最后一条 `choices: []` chunk 带 `usage`**。
- **不要**在 finish chunk 和 final chunk 双写 usage；双写会导致 Cursor 重新刷新/覆盖，用户观察到会重置。

正确形态：

```text
data: {"choices":[{"delta":{},"finish_reason":"stop"}]}
data: {"choices":[],"usage":{"prompt_tokens":...,"completion_tokens":...,"total_tokens":...}}
data: [DONE]
```

验证日志：

```text
resp-audit ... usage_seen=True usage_out=True usage_fallback=False
```

详见：`references/cursor-context-usage-openai-usage-chunk-20260701.md`。

## Agent 不写文件 / 无限调技能

- 兼容层必须把 Responses 的 `function_call`、`function_call_output` 转成 Chat 的 `tool_calls` 与 `role: tool`
- 若曾把 Cursor 流量转到 `/v1/responses` 且只做文本 SSE 转换，会出现「说要建文件但没建」

## reasoning_effort（gpt-5.5 xhigh）

链路：Cursor → `/cursor/v1` → New API → CPA。CPA `config.yaml` 可能对 `gpt-5.5` 固定 `reasoning.effort: medium`，会覆盖客户端 `xhigh`。需在 CPA 改配置或单独模型别名，与 Cursor Base URL 无关。

## 生图

- `gpt-image-2` 在 SubAPI：**仅** `POST /v1/images/generations`
- Cursor 选 `gpt-image-2` 走对话 → 503，**不是** Cursor 兼容层能自动转（除非另做 image sidecar，未采用）

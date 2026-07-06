---
name: cursor-subapi-compat
description: 本机 Cursor IDE 通过 SubAPI 域名接入的现网做法：Override Base URL、SubAPI sk、/cursor/v1 兼容层与排障；含与 CPA 直连、生图 Images API 的区分。
---

# Cursor + SubAPI 现网配置（回看用）

记录 **用户当前采用的 Cursor 接 SubAPI 方案**（VPS1 `45.143.233.108`，域名 `subapi.aigcfast.com`）。以后改配置前先对照本文。

## 一句话

Cursor 不要填普通 `https://subapi.aigcfast.com/v1`，要填 **`https://subapi.aigcfast.com/cursor/v1`**，API Key 用 **SubAPI 面板 `sk-...`**；网关把 Cursor 的 Responses 形态转成 New API 能吃的 Chat，**计费/日志仍走 SubAPI**。

## Cursor 客户端填写（当前做法）

| 项 | 值 |
|----|-----|
| **Override OpenAI Base URL** | `https://subapi.aigcfast.com/cursor/v1` |
| **OpenAI API Key** | SubAPI 令牌，完整 **`sk-...`**（如 pro 分组），不要缺 `sk-` 前缀 |
| **不要填** | 纯 key 片段、JSON 连接串、OpenAI 官方 key、CPA 的 `tjw`（除非刻意走 CPA 直连） |
| **模型** | 在 SubAPI `/v1/models` 里可见的聊天模型，如 `gpt-5.5`、`grok-composer-2.5-fast`、`gpt-5.3-codex-spark` 等 |
| **拼写** | 必须是 **`cursor`**，不是 `cusor` |

改完 Base URL / Key 后：**新开 Agent/Chat 会话**，必要时重载 Cursor 窗口。

## 为什么需要 `/cursor/v1`

Cursor 的 Override 会把 **Responses API 形态的 body**（`input`、`store`、`previous_response_id` 等）发到 **`/v1/chat/completions`**。New API 严格要求 `messages`，否则：

```text
field messages is required
```

直连 CPA（`api.aigcfast.com/v1`）有时能过，是因为 CPA 更宽容；**走 SubAPI 计费必须用兼容入口**。

## 服务端链路（现网 2026-06）

```text
Cursor
  → https://subapi.aigcfast.com/cursor/v1/...
  → OpenResty（1Panel OpenResty）
       location ^~ /cursor/v1/  →  rewrite → 127.0.0.1:8327
  → subapi-cursor-compat（systemd: subapi-cursor-compat.service）
       /root/subapi-cursor-compat/server.py
       UPSTREAM = http://127.0.0.1:3000   # New API，不是 CPA 8317
  → New API（docker new-api :3000）
  → 渠道 #1 等 → 上游（含 CPA :8317 等）
```

与 **早期「方案1：/cursor/v1 → 8317 + tjw」** 不同：当前是 **SubAPI 原生、保留 Authorization 的 key-preserving 兼容层**。

### 关键文件（VPS1）

| 路径 | 作用 |
|------|------|
| `/opt/1panel/www/conf.d/subapi.aigcfast.com.conf` | `location ^~ /cursor/v1/` → `:8327` |
| `/etc/systemd/system/subapi-cursor-compat.service` | 兼容进程 |
| `/root/subapi-cursor-compat/server.py` | `input` → `messages`，转发 New API |

### 响应头（便于确认走了兼容层）

```text
X-SubAPI-Cursor-Compat: ...
X-SubAPI-Cursor-Transform: responses-native  （或类似）
```

## 与「两条 SubAPI 地址」的关系

对外仍是一个域名，**路径不同**：

| 用途 | Base / 路径 | Key |
|------|-------------|-----|
| **Cursor（本 skill）** | `https://subapi.aigcfast.com/cursor/v1` | SubAPI `sk-...` |
| **OpenAI 兼容客户端（curl/SDK/Postman）** | `https://subapi.aigcfast.com/v1` | SubAPI `sk-...` |
| **生图 gpt-image-2** | `POST .../v1/images/generations` | 同上 sk，**不要**当聊天模型 |

## 快速验证（可多行 curl，可 Import Postman）

```bash
curl --request POST \
  --url "https://subapi.aigcfast.com/cursor/v1/chat/completions" \
  --header "Authorization: Bearer sk-你的SubAPI令牌" \
  --header "Content-Type: application/json" \
  --data '{
  "model": "gpt-5.5",
  "stream": false,
  "input": "只回复 OK",
  "max_output_tokens": 20
}'
```

期望：**HTTP 200**，正文含 `OK` 或等价；New API 日志有对应 `token_id` 扣费。

列模型：

```bash
curl --request GET \
  --url "https://subapi.aigcfast.com/cursor/v1/models" \
  --header "Authorization: Bearer sk-你的SubAPI令牌"
```

## 常见错误对照

| 现象 | 含义 | 处理 |
|------|------|------|
| `field messages is required` | 走了 `/v1` 没走 `/cursor/v1` | 改 Base URL |
| `ERROR_BAD_USER_API_KEY` / Unauthorized User Openai API key，且 **VPS 无对应 access/8327 日志** | Cursor **本地校验**未发出请求 | 检查 sk 格式、删旧 key 重填、确认 Override 生效 |
| `Invalid token`（New API JSON） | 请求已到 SubAPI，sk 无效 | 面板换令牌 |
| 立刻断开、8327 无日志 | Base 写成 `/v1`、`/cusor/v1` 或缓存旧配置 | 改 URL + 新会话 |
| Agent 无限调 tool | 兼容层未保留 `function_call` / `tool_result` 历史 | 查 `server.py` 的 `input_to_messages`，见 `references/cursor-pitfalls.md` |
| `gpt-image-2` 503 | 用 chat/responses 调了生图模型 | 生图改 `POST /v1/images/generations`（同一 sk，**不必**走 `/cursor/v1`） |
| `/cursor/v1` xhigh 超长等待，但 Codex CLI 更大上下文正常 | Cursor 自定义 OpenAI 请求缺 `prompt_cache_key`，New API 无 `channel_affinity`，provider cache 不稳定 | 在 `chat_to_responses_payload()` 保留/合成 `prompt_cache_key`；验证 `logs.other.admin_info.channel_affinity.key_path=prompt_cache_key` |

## 刻意不走 SubAPI 分发时（对照，非 Cursor 默认）

若只要 CPA、不要 New API 计费：

| Base | Key |
|------|-----|
| `https://api.aigcfast.com/v1` 或历史 `/cursor/v1`→8317 方案 | CPA `api-keys`（如 `tjw`） |

**本 skill 记录的是：Cursor 用 SubAPI sk + `/cursor/v1` → 8327 → New API。**

## 运维命令（VPS1）

```bash
systemctl status subapi-cursor-compat
journalctl -u subapi-cursor-compat -n 50 --no-pager
ss -ltnp | grep 8327
docker logs new-api --since 30m 2>&1 | grep -E 'relay |cursor|chat/completions' | tail -30
tail -100 /www/sites/subapi.aigcfast.com/log/access.log | grep cursor/v1
```

## 相关 reference

- `references/cursor-settings-checklist.md` — 逐步核对清单
- `references/cursor-pitfalls.md` — 排障与历史方案对比
- `references/cursor-reasoning-model-alias-and-body-capture.md` — Cursor `/cursor/v1` 不显式传 `reasoning_effort` / MAX / 1M 字段时的全量 body 捕获分析；Codex `/v1` 会显式走 Responses reasoning；当前映射 `gpt-5.5→high`、`gpt-5.5-extra→xhigh`。
- `references/cursor-cpa-createplan-repeat-20260628.md` — `api.aigcfast.com/cursor/v1` 重复执行排障记录：Responses→Chat SSE 结束条件、message item 文本识别、function_call arguments 去重、CreatePlan 循环分析。
- `references/cursor-cpa-solution-summary-20260628.md` — Cursor 调 CPA `/cursor/v1` 的最终问题总结、正确处理流程、分析方法与流式验证。

## 关联 Hermes 本地 skill

更细的 New API 面板、Codex 模型名、429/503 见本地 profile：`new-api-admin-ops` → `references/subapi-cursor-compat.md`（可与本仓库内容同步，但以 **本文件为「Cursor 怎么填」权威**）。
# gpt-image-2 做法全记录（SubAPI 单域名）

## 背景

- 对外只有一个 Base：`https://subapi.aigcfast.com/v1`。
- `gpt-image-2` 在 New API/上游 **仅支持** `POST /v1/images/generations`（及 edits），打到 `/v1/responses` 或 `/v1/chat/completions` 会 **503** 或流式 **`stream closed before response.completed`**。
- 目标：在 **不改客户端第二个域名** 的前提下，用 **Nginx + 侧车** 把错协议请求转成 Images，并返回客户端能用的 JSON/SSE。

## 方案选型

| 方案 | 结论 |
|------|------|
| 纯 Nginx rewrite | ❌ 请求体仍是 Responses/Chat，上游不认 |
| 只文档让用户换 `/images/generations` | ✅ 标准做法，但部分客户端改不了路径 |
| **Nginx → 8328 Python 侧车** | ✅ 与现有 `/cursor/v1` → 8327 同架构 |

## 实现要点（8328 `subapi-image-compat`）

1. **Nginx**（`subapi.aigcfast.com.conf`）  
   - `location = /v1/responses` → `127.0.0.1:8328`  
   - `location = /v1/chat/completions` → `127.0.0.1:8328`  
   - `location ^~ /subapi-image-artifacts/` → `127.0.0.1:8328`（GET PNG）

2. **侧车逻辑**  
   - `model` 匹配 `^gpt-image`：从 `input` / `messages` / `prompt` 抽 prompt → `POST 127.0.0.1:3000/v1/images/generations`（Authorization 原样 SubAPI sk）。  
   - 其他 model：**透传** New API `:3000`。  
   - **不拼接**侧车说明文案（曾有的 `Image generated for prompt` / `Image:` 已删除）。  
   - 官方返回多为 `data[0].b64_json` → 落盘 `artifacts/<uuid>.png` → 公网 `https://subapi.aigcfast.com/subapi-image-artifacts/<uuid>.png`。  
   - **Responses 流式**：发 `response.created` → `output_item.*` → **`response.completed`** → `[DONE]`。  
   - **Responses 非流式**：`output` 仅 `image_generation_call`，`result` 为 URL。

3. **不变路径**  
   - `/v1/images/generations` → 直连 `:3000`  
   - `/cursor/v1/` → `:8327` cursor-compat  

## 官方 Images API 返回（实测 SubAPI）

- **无**聊天式说明文字。  
- JSON：`created`、`data[]`（`b64_json` 或 `url`）、`size`、`quality`、`usage` 等。  
- 要原始 b64：客户端直接调 `/v1/images/generations`。

## 流量与排障

- `one-api.db`：`gpt-image` **type=2** 成功 → `request_path` 应为 `/v1/images/generations`。  
- **type=5** 历史多为错路径 `/v1/responses`。  
- 侧车：`journalctl -u subapi-image-compat`。

## 部署与回滚

- 本 skill `scripts/`：`server.py`、`deploy.sh`、`subapi-image-compat.service`、`nginx-snippet.conf`。  
- VPS：`/root/subapi-image-compat/` + `systemctl enable --now subapi-image-compat`。  
- 回滚：恢复 `subapi.aigcfast.com.conf.bak-image-compat`，停服务，删 image 相关 location。

## 技能库

私有仓库 **TangGV/hermes-self-iteration-skill** → `skills/devops/subapi-gpt-image2-compat/`。
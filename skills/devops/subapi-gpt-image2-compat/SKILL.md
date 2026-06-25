---
name: subapi-gpt-image2-compat
description: SubAPI 现网 gpt-image-2：Nginx 将 /v1/responses 与 /v1/chat/completions 转到 8328 侧车，错协议转 Images API；含 Responses 流式 response.completed、公网 artifacts 与流量分析排障。
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [subapi, gpt-image-2, nginx, openresty, new-api]
    related_skills: [cursor-subapi-compat, new-api-admin-ops]
---

# SubAPI gpt-image-2 Nginx 转图兼容层（8328）

对外仍是一个 Base：`https://subapi.aigcfast.com/v1`。客户端若把 **`gpt-image-2`** 打到 **`/v1/responses`** 或 **`/v1/chat/completions`**（错协议），由 **8328** 侧车抽 prompt → 调 **`/v1/images/generations`** → 拼回 JSON 或 **Responses SSE（含 `response.completed`）**，并可选落盘 PNG 公网 URL。

## 目标

- 同一域名下「错路径」也能 **200 + 可用图**（非仅文档建议直连 Images）。
- 修复 **`stream disconnected before completion: stream closed before response.completed`**（流式必须发完整 Responses 事件链）。
- 日志对齐：`gpt-image` **成功**应出现 `request_path=/v1/images/generations`（type=2）；历史 **失败**多为 `/v1/responses`（type=5）。

## 现网链路（VPS1 `45.143.233.108`）

```text
https://subapi.aigcfast.com
  location = /v1/responses          → 127.0.0.1:8328
  location = /v1/chat/completions   → 127.0.0.1:8328
  location ^~ /subapi-image-artifacts/ → 127.0.0.1:8328（读 PNG）

8328 subapi-image-compat
  model 匹配 ^gpt-image → call_images → New API :3000 /v1/images/generations
  其他 model → 透传 :3000

/v1/images/generations  → 仍直连 :3000（标准生图，不变）
/cursor/v1/             → 仍 :8327 cursor-compat（不变）
```

| 组件 | 路径 |
|------|------|
| 代码 | `/root/subapi-image-compat/server.py` |
| 产物 | `/root/subapi-image-compat/artifacts/*.png` |
| 服务 | `subapi-image-compat.service` |
| Nginx | `/opt/1panel/www/conf.d/subapi.aigcfast.com.conf` |
| 本机备份 | `C:\Users\t\AppData\Local\hermes\scripts\subapi-image-compat\` |

## 行为摘要

| 请求 | model | 行为 |
|------|-------|------|
| `/v1/responses` | `gpt-image-*` | 生图；`stream:true` 或 `Accept: text/event-stream` → **responses-sse** |
| `/v1/responses` | 其他 | 透传 New API |
| `/v1/chat/completions` | `gpt-image-*` | 生图；流式 → chat-sse；非流式 → chat-json |
| `/v1/images/generations` | — | **不经过 8328**（Nginx 未拦截） |

- **不拼接**侧车文案（无 `Image generated for prompt`、`Image:` 等）；仅把官方 **`/v1/images/generations`** 的 `data[0].url` 或 `b64_json`（托管为公网 URL）映射为 Responses **`image_generation_call.result`**。
- Chat 形态无官方 image 对象时，`message.content` **仅为官方 URL 字符串**（无 markdown 说明）。

响应头：`X-SubAPI-Image-Compat` = `responses-sse` | `responses-json` | `chat-sse` | `chat-json`。

## Postman / curl（默认多行，Import → Raw text）

**流式 Responses（与易报错场景一致）：**

```bash
curl --request POST \
  --url "https://subapi.aigcfast.com/v1/responses" \
  --header "Authorization: Bearer sk-你的SubAPI令牌" \
  --header "Content-Type: application/json" \
  --header "Accept: text/event-stream" \
  --data '{
  "model": "gpt-image-2",
  "input": "一只简笔画刺猬，白底",
  "stream": true
}'
```

**验收：** 响应含 `"type":"response.completed"`、`data: [DONE]`，以及  
`https://subapi.aigcfast.com/subapi-image-artifacts/<hex>.png`（浏览器可开图）。超时建议 **≥120s**。

**非流式：**

```bash
curl --request POST \
  --url "https://subapi.aigcfast.com/v1/responses" \
  --header "Authorization: Bearer sk-你的SubAPI令牌" \
  --header "Content-Type: application/json" \
  --data '{
  "model": "gpt-image-2",
  "input": "red circle on white",
  "stream": false
}'
```

**要原始 b64_json：** 仍用 `POST /v1/images/generations`。

## 流量分析（one-api.db）

```bash
ssh root@45.143.233.108 'python3 -c "
import sqlite3, json
c=sqlite3.connect(\"/root/new-api/data/one-api.db\")
for row in c.execute(\"SELECT id, type, model_name, substr(other,1,120) FROM logs WHERE model_name LIKE \\\"gpt-image%\\\" ORDER BY id DESC LIMIT 15\"):
    print(row)
"'
```

- **type=2**：成功；`other` 里常见 `request_path` 为 **`/v1/images/generations`**（经侧车转图后亦然）。
- **type=5**：失败；常见 `request_path` **`/v1/responses`** / **`/v1/chat/completions`** 且上游报 image 模型仅支持 images 端点（8328 上线后新流量应减少）。

## 运维

```bash
systemctl status subapi-image-compat
journalctl -u subapi-image-compat -n 50 --no-pager
# 更新代码后
systemctl restart subapi-image-compat
# OpenResty reload（1Panel 容器名以现场为准）
docker ps --format '{{.Names}}' | grep -i openresty | head -1 | xargs -I{} docker exec {} openresty -s reload
```

**回滚：** 恢复 `subapi.aigcfast.com.conf.bak-image-compat`；删除 `/v1/responses`、`/v1/chat/completions` 的 image location；`systemctl stop subapi-image-compat`。

## 相关文档

- `references/traffic-analysis.md` — 错路径与 `response.completed` 根因
- `references/nginx-and-deploy.md` — Nginx 片段与部署步骤
- `scripts/server.py` — 侧车源码副本（与 VPS 同步时以 VPS 为准）

## 与 cursor-subapi-compat 区分

| 入口 | 端口 | 用途 |
|------|------|------|
| `/cursor/v1` | 8327 | Cursor 聊天：`input`→`messages`，Agent SSE |
| `/v1/responses` + gpt-image | 8328 | **生图**协议转换 + Responses 流式完结 |

生图 **不要** 依赖 Cursor Override；标准路径仍是 **`/v1/images/generations`**。
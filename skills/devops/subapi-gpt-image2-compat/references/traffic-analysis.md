# gpt-image-2 流量分析与 response.completed 根因

## 用户侧报错

```text
stream disconnected before completion: stream closed before response.completed
```

常见于：**Postman / Codex / 客户端** 对 SubAPI 发 **`POST /v1/responses`**，`model: gpt-image-2`，且 **`stream: true`** 或 **`Accept: text/event-stream`**。

## 上游真实约束

上游（经 New API 渠道）对 image 模型：

```text
model gpt-image-* is only supported on /v1/images/generations and /v1/images/edits
```

若不经侧车，**`/v1/responses` + gpt-image-2** → New API **503**（日志 type=5，`request_path` 为 responses/chat）。

## 侧车上线前第二处断流

8328 第一版对 `/v1/responses` 只返回 **整段 JSON**（`status: completed`），**没有** SSE 事件序列。客户端按流式解析时，连接在收到 JSON 后关闭，**永远等不到** `response.completed` → 与上表报错一致。

## 修复要点（现网）

1. 识别流式：`stream: true` 或 `Accept: text/event-stream`。
2. 先发 `response.created` / `in_progress` / `output_item.added` / `output_text.delta` / `output_text.done`。
3. **必须**发 **`response.completed`**（内嵌完整 `response` 对象，`status: completed`）。
4. 最后 **`data: [DONE]`**。
5. 不要在 **`response.output_text.done`** 就结束（与 Cursor Agent 文档一致；生图流无 tool_call，但仍需 `response.completed`）。

## 日志统计示例（修复前后对比思路）

近 N 条 `model_name LIKE 'gpt-image%'`：

| type | 含义 | 典型 request_path |
|------|------|-------------------|
| 2 | 成功 | `/v1/images/generations` |
| 5 | 失败 | `/v1/responses`、`/v1/chat/completions` |

侧车生效后，错路径请求应在 **8328 内部** 转为 images 调用，成功记录仍体现为 images 路径。

## 产物 URL

b64 解码写入 `/root/subapi-image-compat/artifacts/<uuid>.png`，公网：

`https://subapi.aigcfast.com/subapi-image-artifacts/<uuid>.png`

流式 `response.completed` 的 `output` 可含 `image_generation_call` + `result` 为该 URL。
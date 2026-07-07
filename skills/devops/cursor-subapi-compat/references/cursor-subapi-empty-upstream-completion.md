# Cursor /cursor/v1 empty upstream completion handling

## When this applies

Use this when SubAPI's Cursor translation service (`subapi-cursor-compat`, commonly the 8327 service) shows large Cursor Agent requests that return an apparently successful short stream:

```text
cursor-shape raw_len≈1.2–1.35MB
req-audit mode=chat-via-responses model=gpt-5.5 stream=True tools=... reasoning='high'|'xhigh'
resp-audit ... has_tool_calls=False finish_seen=stop chunks≈3–4 bytes≈350–600 usage_fallback=True
```

The durable bug is not the large raw body itself. It is the bridge converting an upstream empty/short Responses completion into a normal ChatCompletions `200 + finish_reason=stop` stream with fallback usage, leaving Cursor looking finished/stuck instead of surfacing an actionable signal.

## User workflow preference

If the user explicitly forbids `raw_len > 1MB && xhigh/high` model downgrade or routing changes, do **not** implement downgrade/fallback model selection. Fix the protocol semantics instead: empty upstream completion must not be presented as a normal stop, and must not become Cursor's misleading `User API Key Rate limit exceeded` banner.

When the user is waiting on this class of repair, execute and verify; avoid long explanations before action. Report short progress and then the concrete verification table.

## Current fix pattern

In the streaming `responses-to-chat` branch of `server.py`:

1. Do **not** call `send_response(200)` immediately.
2. Buffer early converted ChatCompletions SSE chunks in `pending`.
3. Parse outgoing chunks and only start the normal SSE response after seeing meaningful model output:
   - `delta.content`, or
   - `delta.tool_calls`.
4. If upstream completes/EOFs without text/tool output:
   - retry once automatically with a salted `prompt_cache_key`;
   - keep the same model and same reasoning/effort;
   - do **not** downgrade, route, or change the selected model.
5. If the retry also returns empty, return `200 text/event-stream` with a clear diagnostic chunk and header `X-Cursor-Upstream-Empty: 1` instead of a non-2xx HTTP error. Cursor custom provider UI may mislabel non-2xx bridge errors as `User API Key Rate limit exceeded`, so avoid `502/503` for this diagnostic path.

Example diagnostic text:

```text
上游本轮返回空响应，桥接层已自动重试并改为可识别的空响应事件；这不是 API Key 限流。后续请求会继续走同一会话，不需要换 Key/Base/模型。
```

Log the classifier result:

```text
empty-upstream retrying once with salted prompt_cache_key chunks=4 bytes=554 finish_seen=stop
resp-audit ... has_tool_calls=False saw_text=False finish_seen=stop chunks=4 bytes=554 empty_upstream=True retried_empty=True
```

Normal text/tool streams should still return `200 text/event-stream` and log `empty_upstream=False`.

## Verification recipe

Minimum verification after patching:

```bash
cd /root/subapi-cursor-compat
python3 -m py_compile server.py
systemctl restart subapi-cursor-compat
systemctl is-active subapi-cursor-compat
```

Then run a local fake-upstream bridge test before/without depending on the real provider:

- fake Responses stream with only `response.completed` → bridge retries once, then returns `200 text/event-stream` diagnostic with `X-Cursor-Upstream-Empty: 1`.
- fake Responses stream with `response.output_text.delta` + `response.completed` → bridge returns `200 text/event-stream` with the real text.

Finally test real Cursor-shaped traffic:

- A real small request should remain `200` and log `saw_text=True` or `has_tool_calls=True`.
- A large `raw_len≈1.3MB` request returning real text/tool calls should remain `200`.
- A large request returning an empty/short upstream completion should not be converted into a fake normal model answer, and should not surface as Cursor's rate-limit/key error.

## Pitfalls

- Do not suppress all short streams. A legitimate short answer like `OK` is small but has `delta.content`; it must pass.
- Do not rely only on byte count. Use the semantic signal: no text, no tool_calls, normal stop/completed.
- Do not emit HTTP `502/503` for this path if Cursor maps it to `User API Key Rate limit exceeded`.
- `usage_fallback=True` is UI-facing only; it must not hide an upstream empty completion.
- If later turns continue normally after one diagnostic chunk, do not tell the user to change API key/base/model; inspect follow-up `resp-audit` first.

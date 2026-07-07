# Cursor /cursor/v1 slow request audit

## When this applies

Use this when Cursor Agent UI stays on statuses such as `Planning next moves`, `Generating`, or tool-loop progress for a long time, but there is no obvious API key/rate-limit error.

## Log event types

SubAPI's Cursor translation service (`subapi-cursor-compat`) emits compact lifecycle logs for every request:

| Event | Meaning |
|---|---|
| `active-audit event=start` | Bridge received a request. Includes `req_id`, client, method, public path, upstream path. |
| `flow-audit event=request` | Parsed Cursor body. Includes `raw_len`, model, reasoning, tools, stream flag. |
| `flow-audit event=upstream_open` | New API/upstream returned HTTP headers. Includes upstream status/request ID and header latency. |
| `flow-audit event=retry_upstream_open` | Empty-upstream retry opened. |
| `resp-audit` | Final streaming result summary. Includes timing, output semantics, status. |
| `slow-audit` | JSON summary emitted when `elapsed_ms >= CURSOR_SLOW_AUDIT_MS` (default 15s). |
| `error-audit` | Upstream returned HTTP error (401/403/429/5xx etc.). |
| `exception-audit` | Bridge-side exception before a valid upstream HTTP response. |
| `active-audit event=end` | Request finished from the bridge perspective. |

All lifecycle events share `req_id`, so one request can be followed end-to-end.

## Example

```text
active-audit event=start req_id=19f3c2a0e9f-1 client=127.0.0.1 method=GET path=/cursor/v1/models upath=/v1/models
error-audit req_id=19f3c2a0e9f-1 client=127.0.0.1 mode=direct-subapi path=/cursor/v1/models upath=/v1/models raw_len=0 model= reasoning= tools=0 upstream_status=401 upstream_request_id=202607... elapsed_ms=3 bytes=124
active-audit event=end req_id=19f3c2a0e9f-1 elapsed_ms=3 status=http_error_401
```

```text
flow-audit event=request req_id=... mode=chat-via-responses raw_len=747181 model=gpt-5.5 reasoning=xhigh tools=17 stream=True
flow-audit event=upstream_open req_id=... upstream_status=200 upstream_request_id=202607... upstream_open_ms=1200
resp-audit req_id=... raw_len=747181 model=gpt-5.5 reasoning=xhigh tools=17 upstream_status=200 upstream_request_id=202607... has_tool_calls=True saw_text=True finish_seen=tool_calls tool_names=Shell chunks=548 bytes=118458 upstream_open_ms=1200 first_chunk_ms=3100 first_output_ms=3200 elapsed_ms=17200 status=ok
slow-audit {"req_id":"...","raw_len":747181,"model":"gpt-5.5","reasoning":"xhigh","tools":17,"tool_names":["Shell"],"upstream_open_ms":1200,"first_chunk_ms":3100,"first_output_ms":3200,"elapsed_ms":17200,"status":"ok"}
```

## Field interpretation

| Field | Meaning |
|---|---|
| `req_id` | Per-bridge request correlation ID. Use it to connect start/request/upstream/response/error/end lines. |
| `client` | Client IP seen by the bridge, usually local nginx. |
| `path` / `upath` | Public Cursor path and rewritten New API path. |
| `raw_len` | Cursor request body size at bridge entry. Large values mean the client is sending a large agent transcript/tool context. |
| `model` / `reasoning` | Effective upstream model and effort after aliases. |
| `tools` | Number of tools supplied by Cursor in the request. |
| `upstream_status` | HTTP status from New API/upstream. |
| `upstream_request_id` | New API request ID for joining with New API container logs. |
| `tool_names` | Tool call names emitted by the model in this response. |
| `upstream_open_ms` | Time until New API/upstream responds with HTTP headers. High value means queue/provider/network delay before SSE. |
| `first_chunk_ms` | Time until first translated SSE chunk from upstream. |
| `first_output_ms` | Time until first meaningful text/tool output. High value with low `upstream_open_ms` means provider thinking/stream latency. |
| `elapsed_ms` | Total bridge time for this request. |
| `status` | `ok`, `empty_upstream`, `write_broken`, `http_error_<code>`, `exception`, or `passthrough`. |
| `empty_upstream` | Upstream produced no text/tool output; handled by empty-upstream retry/diagnostic logic. |
| `write_broken` | Cursor/client disconnected while bridge was writing. |

## Quick triage

```bash
journalctl -u subapi-cursor-compat --since '20 minutes ago' --no-pager \
  | grep -E 'active-audit|flow-audit|resp-audit|slow-audit|error-audit|exception-audit' \
  | tail -160
```

Join one request:

```bash
REQ='19f3c2a0e9f-1'
journalctl -u subapi-cursor-compat --since '20 minutes ago' --no-pager | grep "$REQ"
```

Join New API by upstream request ID:

```bash
RID='202607...'
docker logs --since 20m new-api 2>&1 | grep "$RID"
```

Decision guide:

- `status=ok`, `has_tool_calls=True`, `finish_seen=tool_calls`: Cursor is actively doing multi-round tool work; UI may show `Planning next moves` between rounds.
- `elapsed_ms` high and `first_output_ms` high: model/provider thinking or slow TTFT.
- `upstream_open_ms` high: New API/provider queued before stream headers.
- `raw_len` high plus `reasoning=xhigh`: expensive agent turn; expect slower rounds.
- `write_broken=True`: Cursor/client stopped or disconnected; correlate with nginx `499` and New API `client_gone`.
- `error-audit upstream_status=429`: real rate-limit/upstream error, not the empty-stream bridge diagnosis.
- `empty_upstream=True`: not a normal slow turn; inspect `cursor-subapi-empty-upstream-completion.md`.

## Operational notes

- Default threshold is 15s via `CURSOR_SLOW_AUDIT_MS=15000`.
- This audit is diagnostic only. It does not change model, effort, routing, or request body.
- Keep it enabled by default; it is compact enough for production logs.

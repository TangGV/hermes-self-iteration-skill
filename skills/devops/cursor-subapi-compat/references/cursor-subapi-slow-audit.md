# Cursor /cursor/v1 slow request audit

## When this applies

Use this when Cursor Agent UI stays on statuses such as `Planning next moves`, `Generating`, or tool-loop progress for a long time, but there is no obvious API key/rate-limit error.

## What the bridge logs

SubAPI's Cursor translation service (`subapi-cursor-compat`) emits enriched `resp-audit` for every streaming Cursor bridge request and `slow-audit` when total bridge time exceeds `CURSOR_SLOW_AUDIT_MS` (default `15000` ms).

Example:

```text
resp-audit mode=chat-via-responses raw_len=747181 model=gpt-5.5 reasoning=xhigh tools=17 has_tool_calls=True saw_text=True finish_seen=tool_calls tool_names=Shell chunks=548 bytes=118458 usage_seen=True usage_out=True usage_fallback=True empty_upstream=False retried_empty=False write_broken=False write_broken_after_finish=False upstream_open_ms=1200 first_chunk_ms=3100 first_output_ms=3200 elapsed_ms=17200 status=ok
slow-audit {"mode":"chat-via-responses","raw_len":747181,"model":"gpt-5.5","reasoning":"xhigh","tools":17,"tool_names":["Shell"],"finish_seen":"tool_calls","has_tool_calls":true,"saw_text":true,"chunks":548,"bytes":118458,"upstream_open_ms":1200,"first_chunk_ms":3100,"first_output_ms":3200,"elapsed_ms":17200,"empty_upstream":false,"retried_empty":false,"write_broken":false,"write_broken_after_finish":false,"status":"ok"}
```

## Field interpretation

| Field | Meaning |
|---|---|
| `raw_len` | Cursor request body size at bridge entry. Large values mean the client is sending a large agent transcript/tool context. |
| `model` / `reasoning` | Effective upstream model and effort after aliases. |
| `tools` | Number of tools supplied by Cursor in the request. |
| `tool_names` | Tool call names emitted by the model in this response. |
| `upstream_open_ms` | Time until New API/upstream responds with HTTP headers. High value means queue/provider/network delay before SSE. |
| `first_chunk_ms` | Time until first translated SSE chunk from upstream. |
| `first_output_ms` | Time until first meaningful text/tool output. High value with low `upstream_open_ms` means provider thinking/stream latency. |
| `elapsed_ms` | Total bridge time for this request. |
| `status` | `ok`, `empty_upstream`, or `write_broken`. |
| `empty_upstream` | Upstream produced no text/tool output; handled by empty-upstream retry/diagnostic logic. |
| `write_broken` | Cursor/client disconnected while bridge was writing. |

## Quick triage

```bash
journalctl -u subapi-cursor-compat --since '20 minutes ago' --no-pager \
  | grep -E 'slow-audit|resp-audit|cursor-shape|req-audit' \
  | tail -120
```

Decision guide:

- `status=ok`, `has_tool_calls=True`, `finish_seen=tool_calls`: Cursor is actively doing multi-round tool work; UI may show `Planning next moves` between rounds.
- `elapsed_ms` high and `first_output_ms` high: model/provider thinking or slow TTFT.
- `raw_len` high plus `reasoning=xhigh`: expensive agent turn; expect slower rounds.
- `write_broken=True`: Cursor/client stopped or disconnected; correlate with nginx `499` and New API `client_gone`.
- `empty_upstream=True`: not a normal slow turn; inspect `cursor-subapi-empty-upstream-completion.md`.

## Operational notes

- Default threshold is 15s via `CURSOR_SLOW_AUDIT_MS=15000`.
- This audit is diagnostic only. It does not change model, effort, routing, or request body.
- Keep it enabled by default; it is compact enough for production logs.

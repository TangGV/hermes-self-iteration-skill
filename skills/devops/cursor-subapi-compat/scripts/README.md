# Unified Cursor compatibility bridge

This directory keeps production snapshots for the shared Cursor translation layer.

- `server.py`: CPA instance snapshot. Upstream defaults to CPA, used by `api.aigcfast.com/cursor/v1`.
- `subapi-server.py`: SubAPI instance snapshot generated from the same latest translator logic. Upstream defaults to New API/SubAPI, used by `subapi.aigcfast.com/cursor/v1`.

Both snapshots should stay logically identical for Cursor-facing protocol handling:

- ChatCompletions with tools -> Responses bridge
- Responses SSE -> ChatCompletions SSE tool calls
- finish_reason by last output kind
- call_id normalization
- stream usage/context statistics preservation
- metadata / stream_options preservation unless a specific upstream incompatibility is proven

Only deployment-specific defaults should differ: listen address, upstream address, and response identification headers.

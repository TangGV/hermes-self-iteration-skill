---
name: new-api-admin-ops
description: Operate and troubleshoot New API/SubAPI admin panels, especially billing/model pricing, groups, tokens, channels, and user-facing API base setup.
---

# New API / SubAPI Admin Operations

Use this skill when the user asks about New API, SubAPI, NewAPI, `subapi.aigcfast.com`, model pricing, group pricing, tokens, channels, model mapping, or where to configure billing/quotas in the admin panel.

## Core workflow

1. **Identify whether the question is about user billing or upstream routing.**
   - User-facing model cost: go to Billing → Model Pricing.
   - User/group markup or discount: go to Billing → Group Pricing.
   - Upstream keys, model list, or model name mapping: go to Channels, not pricing.
   - Token permissions/group assignment: go to Tokens and User/Groups as applicable.
2. **Give direct UI paths first.** The user prefers concise Chinese answers with practical direct links when available.
3. **For this user's SubAPI instance, prefer the independent API base and admin host already known from memory:** `https://subapi.aigcfast.com/v1` for OpenAI-compatible API base, and `https://subapi.aigcfast.com` for the panel.
4. **Do not repurpose the original `api.aigcfast.com` setup or token id=1 (`vip`) when discussing the separate SubAPI instance.** Treat SubAPI as independent unless the user explicitly asks to link/migrate.
5. **If editing live configuration is requested, verify target scope before destructive changes.** Price/group/token changes affect real users; inspect current settings first when tool access is available.

## Admin manual top-up vs balance logs quick answer

For “**给用户充了额度，账单/余额日志里没有，只有总余额变了**”:

- **Wallet → 账单** (`top_ups`) = **online payment orders only**. Admin **`add_quota`** does **not** create billing rows (`top_ups` can stay **0**).
- Admin top-up **does** write **`logs` type = 3 (管理)** when done via **用户管理 → 调整额度** → `POST /api/user/manage` (`action: add_quota`). It does **not** write type **1 (充值)** unless redemption/online callback paths run.
- User may be filtering **日志 → 充值** only — tell them to use **日志 → 管理** and filter by username.
- Pitfalls: direct DB `users.quota` edits; **`logs` cleared** by usage-stat reset while balance preserved — looks like “missing history”.
- Read-only checks and SQL: `references/subapi-admin-quota-vs-billing-logs.md`.

## Redemption / 兑换码 quick answer

For “SubAPI 没开兑换码 / 兑换码功能在哪 / 用户充值没有兑换码”:

- **Not missing feature:** New API has `redemptions` table and admin `/api/redemption`; on VPS1 the table exists (may be **0 rows** until codes are generated).
- **Gate:** User `enable_redemption` and admin **batch create** both require **`payment_setting.compliance_confirmed`** with current terms version (**v1**). Until an admin confirms in the panel, redemption, online top-up list, subscription plan edits, and non-zero invite rewards stay **locked** (frontend copy matches this).
- **Unrelated to self-use:** `SelfUseModeEnabled=false` (business billing) does **not** auto-enable redemption.
- **Fix:** Admin login → **系统设置 → 支付设置** → **确认合规声明** (`POST /api/option/payment_compliance`, session auth only, not API token) → then **兑换码** admin page to generate codes.
- **Do not** fix via channels, model pricing, or `SelfUseModeEnabled`.

See `references/subapi-redemption-payment-compliance.md` for DB keys, API anchors, and VPS verification commands.

## Mainland China compliance + 敏感词 quick answer

For “大陆合规别人怎么做 / 敏感词怎么配 / 点了合规声明就够吗”:

- **Two layers:** (1) **Payment compliance** in 支付设置 — operator liability + unlocks redemption/top-up/subscription/invite rewards; **not** legal advice or PRC GenAI filing. (2) **Content controls** — optional **敏感词** in 运营设置 (`CheckSensitiveEnabled`, `SensitiveWords`, `StopOnSensitiveEnabled`); prompt check via Aho-Corasick in `service/sensitive.go` / `controller/relay.go`.
- **Typical API-gateway operators (中转):** confirm payment compliance if selling quota; maintain a **local word list** or leave defaults; rely on **upstream** moderation; avoid marketing as “境内公众 GenAI 服务” unless building full compliance.
- **Public GenAI to PRC users:** others add filing/safety assessment, third-party moderation APIs, complaint channels, synthetic-content labeling, log retention — **beyond** New API toggles.
- **Panel:** Classic `https://subapi.aigcfast.com/console/setting` → 运营设置 → **敏感词** (`SettingsSensitiveWords.jsx`). Payment compliance text explicitly mentions 备案/内容安全 when serving GenAI in China — that is **acknowledgment**, not auto-implementation.
- **Do not** equate “确认合规声明” with deploying a full mainland content-security stack.

See `references/subapi-mainland-compliance-sensitive.md`.

## Image per-call pricing (按张 / 按次) quick answer

For “gpt-image-2 怎么计费 / 别人 0.08 元一张怎么设 / image2 按生成一次”:

- **Endpoint:** `POST /v1/images/generations` only; misrouted chat/responses → 503 and may log **quota=0**.
- **Billing fork:** If model id is in **`options.ModelPrice`** → **per-call USD** (`UsePrice=true`): `quota ≈ ModelPrice × quota_per_unit × group_ratio × n` (`image_handler.go` sets `OtherRatio("n")`). If **not** in ModelPrice but in **ModelRatio** → **token/ratio** billing from upstream usage (on VPS1 2026-06, `gpt-image-2` without ModelPrice often ~**690 quota** ≈ **0.01 CNY**/gen at `quota_per_unit=500000`, `usd_exchange_rate=7.3`).
- **Peer “0.08 元/张”:** add to **ModelPrice** (USD per generation): `0.08 CNY ÷ usd_exchange_rate` (e.g. **0.011** at rate 7.3) or **0.08** if they mean USD. Examples on same instance: `grok-imagine-image: 0.2`, `dall-e-3: 0.04`.
- **Panel:** 系统设置 → 计费 → **模型定价** → fixed price / ModelPrice; restart `new-api` after DB edits.
- **`gpt-image-*` quality tiers:** `dto/openai_image.go` only applies size/quality multipliers to **`dall-e*`**; for low/medium/high on `gpt-image-2`, split model aliases (`gpt-image-2-low`, etc.) with separate ModelPrice entries.
- **ModelPrice wins** over ModelRatio for the same name — remove or override ratio-only config when switching to per-image retail.

See `references/subapi-image-per-call-pricing.md`. Endpoint/Hermes routing: `references/subapi-gpt-image-2-hermes-dual-channel.md`.

## Self-use mode quick answer

For “SubAPI 自用模式是什么 / 怎么切换”:

- Explain it as a personal/private-use mode: suitable for self-hosted single-user usage, less strict about requiring complete model pricing/ratio configuration.
- It is controlled by the option key `SelfUseModeEnabled`; public status exposes `data.self_use_mode_enabled` at `/api/status`.
- Classic UI path: `https://subapi.aigcfast.com/console/setting?tab=operation` → 运营设置 → 通用设置 → 自用模式 → 保存通用设置.
- New/default UI path: `https://subapi.aigcfast.com/system-settings/operations/behavior` → System Behavior → Self-Use Mode.
- For this user's independent SubAPI, **self-use was the default for private Hermes/Cursor**; if they ask to **开启商业模式 / 对标官网价**, disable self-use and sync **every channel-visible model** — see **Business mode + official pricing** below.
- See `references/subapi-self-use-mode.md` for behavior details, API/DB knobs, and verification.

## Cursor compatibility quick answer

For “Cursor 直连 CPA 可以、通过 SubAPI 不行 / field messages is required”:

- Root cause: Cursor Override OpenAI Base URL may send Responses-style `input` payloads to `/v1/chat/completions`; New API expects `messages` and rejects with `field messages is required`.
- If the user wants **SubAPI-native** support, do **not** route Cursor to CLIProxyAPI/CPA or swap the key to `tjw`; that bypasses SubAPI token/billing/logs.
- Correct pattern: add a dedicated `/cursor/v1` compatibility endpoint that preserves `Authorization` exactly, converts Cursor Responses-style payloads into Chat Completions shape, then forwards to New API `/v1` (usually `http://127.0.0.1:3000/v1`).
- For Cursor Agent/file creation, keep the normalized request on `/v1/chat/completions` unless you also implement full Responses function-call → Chat `tool_calls` translation. A text-only `/responses` bridge can make Cursor say it will create a file without actually creating it.
- If Cursor starts repeatedly “calling skill/tool”, inspect the converted request history: Responses-style `function_call` and `function_call_output`/`tool_result` items must be preserved as ChatCompletions `assistant.tool_calls` and `role: tool` messages with matching `tool_call_id`; otherwise the model does not see tool completion and repeats the call.
- **`call_id` max 64:** Cursor may send longer `input[].call_id` → `Invalid 'input[N].call_id': string too long`. Normalize on **8327** (`subapi-cursor-compat`) **and** **8328** (`subapi-image-compat` non–`gpt-image-*` passthrough on `/v1/responses`) — only fixing 8327 leaves errors when Override is plain `/v1` or client hits `/v1/responses`. See agent skill **`cursor-subapi-compat`** → `references/call-id-normalization.md`; transform rules in `references/subapi-cursor-compat.md`.
- The user expects Cursor streaming to feel like typewriter output, not multi-second chunks. Verify streaming at the client behavior level; in the proxy avoid `read(65536)`, preserve SSE line boundaries, disable buffering/Nagle where possible, and only blame upstream/UI after confirming the proxy forwards promptly.
- Cursor “Extra High” thinking can add reasoning/thinking fields that some upstreams reject or route oddly. For this user's `/root/subapi-cursor-compat/server.py`, preserve only normalized `reasoning_effort` from top-level `reasoning_effort` or `reasoning.effort`; allow `low/medium/high/xhigh` plus `minimal/none`, and normalize the typo `xhight` to `xhigh`. Continue dropping raw `reasoning`, `reasoning_summary`, `thinking`, and `thinking_budget` to avoid unsupported-parameter errors. For `gpt-5.5`, `medium/high` are log-proven; `xhigh` should be passed through when the user explicitly needs it, but be ready to conditionally downgrade if the upstream rejects it.
- Verify `/cursor/v1/models` returns the SubAPI model list, Cursor-like `/cursor/v1/chat/completions` returns 200, and New API logs show the SubAPI `token_id`. If Cursor disconnects but the 8327/OpenResty logs show no `/cursor/v1` hit, check for cached Base URL, typo `/cusor/v1`, or the client still using plain `/v1` before debugging server code.
- **回看「我怎么填 Cursor」:** point to private repo `hermes-self-iteration-skill` → `cursor-subapi-compat` for Chinese checklist; technical transform rules remain in `references/subapi-cursor-compat.md`.
- See `references/subapi-cursor-compat.md` for transform rules, validation commands, and pitfalls.

## Current model cost (ad-hoc quote)

When the user asks **当前模型的费用** / how much **grok-composer** (or any SubAPI-routed model) costs:

1. **CPA `usage_events` has no per-request USD/cost column** — do not invent dollars from CPA alone.
2. **Authoritative user billing** for Hermes → SubAPI: query VPS `one-api.db` table `logs` (`quota`, `prompt_tokens`, `completion_tokens`, `model_name`) and `options` rows `ModelRatio`, `CompletionRatio` (and `ModelPrice` for image-style models).
3. Formula (typical): `quota ≈ (prompt + completion × CompletionRatio) × ModelRatio × group_multiplier`. Observed on this stack: `grok-composer-2.5-fast` often **MR 0.625, CR 2** vs **gpt-5.5 MR 2.5, CR 6** → Grok is roughly **~3× cheaper per token** in the same ledger.
4. `logs.created_at` is **Unix epoch** — filter “today” with CST timestamp range, not `date(created_at)` alone if timezone skew.
5. If `QuotaPerUnit` is empty in `options`, report **quota totals** and **quota/token**; ask the user for panel “quota ↔ 货币” or give formula for **~7k–8k quota per ~57k-input Hermes turn** when logs show that shape.
6. Separate **SubAPI quota** from **xAI/Codex subscription pools** (CPA quota API `Monthly` / `5h` windows).

See `references/subapi-model-cost-adhoc.md`.

## Model plaza “too many models” quick answer

For **「模型广场怎么这么多模型」** / plaza vs admin pricing feels huge:

1. **Plaza count = `/api/pricing` = token `/v1/models`** when abilities are synced — often **single digits** on a tightened channel, not hundreds.
2. **Inflators:** homepage **30+ vendor logos** (marketing only); **`options.ModelRatio`** (~200+ keys) = billing dictionary, **not** plaza catalog; stale **Hermes `custom_providers.subapi.models`** or **CC Switch** lists.
3. **Verify:** `GET /api/pricing`, `GET /v1/models` with user sk, `channels.models`, `COUNT(DISTINCT model) FROM abilities WHERE enabled=1`; compare `length(ModelRatio)` separately.
4. **Shrink plaza:** channel model string + **abilities** — do not need to delete entire `ModelRatio` JSON.

See `references/subapi-model-plaza-catalog-count.md`.

## Model pricing quick answer

For “SubAPI 在哪设置模型价格 / where to set model prices”:

- Admin panel: `https://subapi.aigcfast.com`
- Path: `系统设置` → `Billing / 计费` → `Model Pricing / 模型定价`
- Direct route: `https://subapi.aigcfast.com/system-settings/billing/model-pricing`
- Group pricing route: `https://subapi.aigcfast.com/system-settings/billing/group-pricing`
- On this instance, the actual backing values live in `one-api.db` → `options` rows such as `ModelRatio`, `CompletionRatio`, `CacheRatio`, and `ModelPrice`.
- If a model name is missing from the maps, inspect `setting/ratio_setting/model_ratio.go` for hardcoded fallbacks before assuming the UI is the source.
- For official GPT/Gemini price alignment tasks, use `references/subapi-official-pricing-sync.md`: it captures the effective `ModelRatio * 2` conversion on this instance, safe DB backup/update/restart/verification sequence, and the official price-to-ratio mappings from the 2026-06 sync.

See `references/subapi-pricing-lookup.md` for the session-derived lookup path and fallback notes.

## Business mode + official pricing (live VPS)

When the user asks to **关闭自用 / 开启商业** and **模型价格完全对标官网**:

1. Load `references/subapi-official-pricing-sync.md` for GPT/Gemini/xAI ratio math (`ModelRatio * 2` = input USD/1M on this instance).
2. Follow `references/subapi-business-mode-pricing-sync.md`: scope from **active channel model list**, backup `one-api.db`, set `SelfUseModeEnabled=false`, merge ratios, `docker restart new-api`, verify `http://127.0.0.1:3000/api/status` on VPS (`self_use_mode_enabled` false).
3. Prefer `scripts/subapi-sync-channel-pricing.py` (dry-run then `--apply`); extend `TOKEN_MAP` when new channel models lack maps — **warn on unmapped names** before apply.
4. **DeepSeek-only** channel sets: use DeepSeek API platform USD/1M in the business reference; map `deepseek-v4-*` aliases to flash/reasoner tiers when no separate card.
5. Tell the user business pricing ≠ full storefront: group pricing, top-up, sk-buy DNS verification may still be manual in panel.

## Scope clarification: New API vs CLIProxyAPI admin pages

Be careful not to mix up the two admin surfaces on this user's stack:

- `https://subapi.aigcfast.com` / `https://api.aigcfast.com/subapi/...` = **New API / SubAPI** panel and API
- `https://api.aigcfast.com/management.html#/login` = **CLIProxyAPI management panel**

If the user mentions `management.html`, `v0/management`, or a "management key", route the task to CLIProxyAPI-style management, not New API admin logic.

If the user says Cursor works against CPA/CLIProxyAPI but not through SubAPI/New API, check for Cursor's Override Base URL compatibility bug before changing New API prices/tokens/channels: Cursor may POST Responses-style `input` bodies to `/v1/chat/completions`, causing New API to return `field messages is required`. The practical fix is usually a `/cursor/v1` compatibility route/bridge to CLIProxyAPI under the SubAPI domain, not model pricing or token-group changes.

## SubAPI 直接跑通 `gpt-image-2`（不含 Hermes）quick answer

When the user asks to **开通 / 跑通 / 直接通过 SubAPI 生图**, or **「现在直接调用是不是会失败」**:

1. **Answer first:** SubAPI **does not** fail for image gen when the client uses **`POST /v1/images/generations`**. Failures are almost always **wrong endpoint** (`/v1/responses` or `/v1/chat/completions` with `model: gpt-image-2`) — relay **503** with *only supported on /v1/images/generations*.
2. **Do not** lead with Hermes, Telegram, or `image_gen` unless the user explicitly asks for Hermes wiring. Give **panel + curl/SDK + acceptance** only.
3. **Contract:** `https://subapi.aigcfast.com/v1` + Bearer **same sk** as chat; body `model`, `prompt`, `size`, `n`, `quality` (`low|medium|high`).
4. **Panel:** channel model list includes `gpt-image-2`; token **group** has ability **enabled** for that model (check `abilities` on VPS if UI unclear).
5. **Smoke:** `GET /v1/models` lists `gpt-image-2`; `POST /v1/images/generations` → **200** + `b64_json` or `url` (~25–35s). **Reference images:** use `POST /v1/images/edits` multipart; single image field `image`, multiple images field `image[]` (see `subapi-gpt-image2-compat` → `references/reference-image-edits.md`). **Official body has no chat prose** — see `references/subapi-official-images-response-shape.md`. **8328 must not** add `Image generated for prompt` / `Image:` sidecar text; map to `image_generation_call.result` only.
6. **Monitoring:** success = `logs.type=2` and `other.request_path` is `/v1/images/generations` or `/v1/images/edits`; noise/failure = `type=5` with `quota=0`. New API/SubAPI logs store billing/request metadata, **not** response `b64_json`; if the client needs the image later, save the HTTP response body or decode/store the PNG at the application layer.
7. **`openai_error` / 524 in app demos:** if New API logs show `error_type=openai_error` and `bad response status code 524`, treat it as an upstream timeout, not a frontend bug. Batch demo apps should return partial successes plus an `errors[]` array instead of failing the whole request after earlier images succeeded; see `subapi-gpt-image2-compat` → `references/subapi-image-demo-app.md`.

Full runbook: `references/subapi-image2-direct-client-runbook.md`. **One public URL messaging:** `references/subapi-single-base-url-messaging.md`. Postman import: `templates/subapi-gpt-image-2.postman_collection.json`. Architecture (incl. optional Hermes): `references/subapi-image-generation-architecture.md`.

## 对外只有一个 SubAPI 地址 quick answer

When the user says **不可能跟客户说用别的地址** / only one `subapi.aigcfast.com`:

1. **Reassure:** chat and images share **`https://subapi.aigcfast.com/v1`** — difference is **path** (`/chat/completions` vs `/images/generations`), same as OpenAI’s single `/v1` host.
2. **Do not** suggest a second domain for images. Optional **same-host** compat prefix (e.g. `/cursor/v1`) is for broken chat clients only, not the default image story.
3. **Simple recommendation (docs-only clients):** panel + Images API docs + Postman template. **If user explicitly wants nginx 转 image2 得到结果:** use deployed **8328** path routing (see `references/subapi-image-compat-live.md`), not a second domain.
4. See `references/subapi-single-base-url-messaging.md` for copy-paste client text (Chinese).

## SubAPI 生图「用什么方案」quick answer

For **「SubAPI 生图模型用什么方案来的」** / architecture (not pricing):

1. **Scheme:** New API at `subapi.aigcfast.com` exposes **OpenAI Images API** — `POST /v1/images/generations` (+ edits); same `sk-...` as chat billing.
2. **Models:** `GET /v1/models` with user token; image ids typically **`gpt-image-1`**, **`gpt-image-1.5`**, **`gpt-image-2`** (verify live).
3. **Not this scheme:** `gpt-image-*` on `/v1/responses` or as **chat** model in any client → **503**.
4. **Hermes (only if asked):** `image_gen.provider: openai` + `.env` `OPENAI_API_KEY` + `OPENAI_BASE_URL=https://subapi.aigcfast.com/v1`; tiers `gpt-image-2-low|medium|high`. Unset `image_gen.provider` → **FAL**, not SubAPI.
5. **CPA upstream:** `/v1/images/generations` may still show `model_alias: gpt-image-2` with internal `gpt-5.4-mini` in CPA — expected.

Full diagram: `references/subapi-image-generation-architecture.md`.

## `gpt-image-2` / image generation quick answer

For “SubAPI gpt-image-2 503 / 只能 images 端点 / 能转吗 / Hermes 生图走 SubAPI”:

- **Not a panel outage:** `gpt-image-2` on `POST /v1/responses` (or as a **chat** model in Hermes) fails with upstream text that only `/v1/images/generations` and `/v1/images/edits` are supported — SubAPI relays as 503.
- **SubAPI works for images** with the same sk: `POST https://subapi.aigcfast.com/v1/images/generations` (curl smoke test before blaming channels).
- **「转」for Hermes users:** dual channel — chat stays on `custom:subapi`; enable **`image_gen`** with `provider: openai`, set `.env` `OPENAI_API_KEY` + `OPENAI_BASE_URL=https://subapi.aigcfast.com/v1`, remove `gpt-image-2` from **chat** `custom_providers.subapi.models`. Do not promise automatic `/responses` → images rewrite on New API.
- Full steps, pitfalls, and alternatives: `references/subapi-gpt-image-2-hermes-dual-channel.md`.
- **Official Codex CLI/Desktop** (user question「codex 怎么生图」): default is **not** SubAPI — built-in **`image_gen`** via ChatGPT/Codex **OAuth** and Responses **`image_generation`** tool; artifacts in `~/.codex/generated_images/`. **Do not** equate with picking `gpt-image-2` + `wire_api=responses` against `subapi.aigcfast.com` (503). Cross-stack diagram: `cliproxyapi-cpa-ops` → `references/codex-image-generation-architecture.md`.
- **对外直接调用：** same sk + `POST /v1/images/generations` only; never document `gpt-image-2` on `/v1/responses` or chat model pickers.
- **Billing:** default on this stack is often **ratio/token** (not peer **0.08 CNY/image**); set **`ModelPrice`** for per-generation retail — see **Image per-call pricing** quick answer.
- **Live (2026-06-25):** `location = /v1/responses` and `/v1/chat/completions` → **8328** `subapi-image-compat` — `gpt-image-*` → Images API → JSON/SSE; **do not inject** sidecar text (`Image generated for prompt`, `Image:`); map official `data[0]` → **`image_generation_call.result`** only. **Non–image models** on same paths: passthrough after **`normalize_request_body`** (call_id≤64). Raw b64 still **`/v1/images/generations`**. Runbook: `references/subapi-image-compat-live.md`; official JSON shape: `references/subapi-official-images-response-shape.md`. Feasibility/options: `references/subapi-openresty-image-compat-feasibility.md`.

## Non-chat models exposed in `/v1/models` (audit)

When the user asks **哪些模型不支持 chat 却又开放** or to audit image-only models in the model list:

1. `GET /v1/models` with the **same token** clients use (not admin guesswork).
2. For each id, probe `POST /v1/chat/completions`, `POST /v1/responses`, and for `gpt-image*` also `POST /v1/images/generations`.
3. **503** with `only supported on /v1/images/generations` = mis-exposed for chat/Codex Responses — typical: **`gpt-image-2`**, **`gpt-image-1.5`** (both in `abilities` for `default` / `codex-pro` / `codex-plus` on VPS1, 2026-06-25).
4. **`model_not_found`** = not routed for that token/group — different problem (e.g. `gpt-image-1` in channel string but not in token list).
5. VPS: `sqlite3 .../one-api.db` on `abilities` + `channels`; `docker logs new-api | grep 'only supported on'`.

Run `scripts/subapi-probe-chat-vs-images.py` (env `SUBAPI_KEY` or Hermes `config.yaml` subapi key). Full checklist: `references/subapi-non-chat-model-audit.md`.

## SubAPI request-format and model-routing diagnostics

When the user reports OpenAI-compatible API errors for SubAPI models, test the exact endpoint/body combination before changing channels:

- `POST /v1/chat/completions` must use a `messages` array. If a client sends Responses-style `input` to this endpoint, New API returns `field messages is required`.
- Responses-style payloads belong on `POST /v1/responses`.
- **Image models** (`gpt-image-2`, **`gpt-image-1.5`**, etc.) belong on **`/v1/images/generations`** or **`/v1/images/edits`**, not `/v1/responses` or chat model lists. Both can appear in `/v1/models` while returning **503** on chat/responses — see `references/subapi-non-chat-model-audit.md`.
- `/v1/models` can list models that are visible in New API but not actually routeable upstream. For this user's stack, `gpt-5.3-codex-spark` has tested OK, while `gpt-5.3-codex` has returned `unknown provider for model gpt-5.3-codex`; `gpt-5.3c-codex` is not an advertised model and has returned no available channel.
- If asked for a client-ready curl, prefer an environment-variable token example so the final answer does not repeat full bearer tokens.

## Usage-stat reset quick answer

For “清理使用记录 / 重新开始统计 / reset SubAPI usage stats”:

- Back up `/root/new-api/data/one-api.db` first.
- Clear usage-history tables: `logs`, `quota_data`, and `perf_metrics`.
- Reset statistical counters only: `users.used_quota`, `users.request_count`, `tokens.used_quota`, `channels.used_quota`.
- Do **not** touch `users.quota`, `tokens.remain_quota`, token keys, channels, groups, or pricing options.
- After clearing, **do not restart** if the only goal is zero stats — active Hermes/Cursor clients can insert a new `logs` row within seconds. If `logs` count is 1 right after reset, run **one more clear pass** (same DELETE/UPDATE SQL or `scripts/subapi-reset-usage-stats.py`) and re-verify; restarting is optional for counter visibility, not required for DB truth.
- Backup naming on this instance: `one-api.db.backup-stats-reset-YYYYMMDD-HHMMSS` (stats) vs `backup-business-pricing-*` (pricing/self-use) — tell the user which file matches which operation.
- See `references/subapi-usage-stat-reset.md` for the exact backup/reset/verification workflow; prefer `scripts/subapi-reset-usage-stats.py` on VPS over hand-typed inline SQL when the script is present.

## OpenAI-compatible curl verification quick answer

When the user asks to “curl 测试下” or verify whether SubAPI is usable, do **both** health and real inference checks rather than stopping at `/api/status`:

1. `GET https://subapi.aigcfast.com/api/status` without auth verifies the panel/API service and public metadata.
2. `GET https://subapi.aigcfast.com/v1/models` with `Authorization: Bearer <key>` verifies token auth and visible model list. No auth should return `401 Invalid token`, which is expected.
3. Pick a returned chat-capable model, preferably `gpt-5.5`, `gpt-5.4-mini`, `gemini-2.5-flash`, `gpt-5.2`, then run `POST /v1/chat/completions` with a tiny `ping → pong` prompt. A `200` with a real reply is the success criterion.
4. Use the OpenAI-compatible base URL `https://subapi.aigcfast.com/v1` in client examples.
5. If the local environment has proxy/TLS oddities, retry the curl probe with `--noproxy '*'` before diagnosing the service as down.

See `scripts/subapi-curl-probe.sh` for a reusable redacted probe template.

## SubAPI 503 / `auth_unavailable` quick answer

When the user reports **503** with **`auth_unavailable: no auth available (providers=codex, model=gpt-5.5)`** on `https://subapi.aigcfast.com/v1/responses`:

1. Confirm SubAPI logs show **用户额度充足** — wallet is not the bottleneck.
2. Treat as **CPA/CLIProxyAPI Codex auth pool** empty or all disabled; grep `auth_unavailable` in `docker logs new-api`.
3. Cross-check CLIProxy **503 in 2–8ms** and **`/v0/management/auth-files`** active Codex count.
4. **Do not** change channels/tokens first; **do not** switch user's Cursor provider without explicit ask (investigate only).

See `references/subapi-503-auth-unavailable-relay.md` and `cliproxyapi-cpa-ops` → `references/cpa-503-auth-unavailable-diagnostics.md`.

## SubAPI `/v1/responses` nginx 413 quick answer

For HTML errors like **`413 Request Entity Too Large`** from `nginx/1.22.1` on `https://subapi.aigcfast.com/v1/responses`:

1. **Resolve active host first** — `subapi.aigcfast.com` may currently point to VPS2, not VPS1. Use `getent hosts subapi.aigcfast.com` and `curl -w '%{remote_ip}'` before editing configs.
2. Grep the active host nginx logs for `client intended to send too large body`; observed Codex Desktop failures were around **1,064,864 bytes**, i.e. nginx default ~1 MiB.
3. Add `client_max_body_size 100m;` to the active `subapi.aigcfast.com` TLS server block; also add `proxy_request_buffering off;` for API/streaming paths if large probes become 502 with `sendfile() failed (32: Broken pipe)`.
4. Verify with an intentionally invalid bearer token and large JSON bodies: success is **JSON `401 Invalid token` with `x-oneapi-request-id`**, not HTML `413`.
5. Watch for VPS2 nginx layout drift: `sites-enabled` may be a regular file, not a symlink; editing `sites-available` alone may not affect `nginx -T`. Do not leave backup files in `sites-enabled` because they create duplicate vhost warnings.

Full runbook: `references/subapi-nginx-413-active-dns-host.md`.



1. **Treat 429 as relay upstream failure first**, not SubAPI panel wallet exhaustion — verify on VPS1 `docker logs new-api` for `relay | ... | 429` and `channel error (channel #..., status code: 429)`.
2. If logs still say **用户额度充足** but upstream text is `The usage limit has been reached` or `All credentials for model gpt-5.4 are cooling down via provider codex`, the bottleneck is **CPA/codex**, not New API billing. Client retries explain the "exceeded retry limit" wrapper.
3. **Grep carefully:** use `relay.*| 429 |`, not bare `429` (false positives from timestamps/token counts).
4. Cross-check **`/root/.hermes/scripts/cpa_status_brief.py`**: per-model ok/fail and last event time; other models (e.g. grok) still OK ⇒ scoped outage.
5. **Remediation:** wait for cooldown, switch model temporarily, reduce parallel 429 retries — avoid channel/token surgery when wallet is sufficient.

Full log patterns, commands, and reporting template: `references/subapi-429-relay-diagnostics.md`.

## Codex model troubleshooting quick answer

For SubAPI/New API errors around `gpt-*-codex*` model names:

- `field messages is required` on `/v1/chat/completions` usually means the client sent a Responses-style `input` payload to the Chat Completions endpoint. Fix the client request shape: `/chat/completions` needs `messages`; `/responses` needs `input`.
- Do not rely on `/v1/models` alone. A Codex model may appear in the channel model list but still fail upstream with `unknown provider for model ...` or account-support errors. Always run a minimal real completion probe.
- Treat `No available channel for model ... under group ...` as model-name typo / group availability first; treat `unknown provider` as upstream/CLIProxyAPI mapping first, not pricing.
- See `references/subapi-codex-model-troubleshooting.md` for the concise reproduction and reporting pattern.

## VPS1 Hermes + SubAPI provider pitfall

When checking **VPS1 Hermes SubAPI 配置** (`/root/.hermes/config.yaml`):

- **`providers.subapi`** may already list `api: https://subapi.aigcfast.com/v1` and a valid `api_key`.
- The **active** gateway still uses **`model.provider`** (often stuck on **`openai-api`** + `https://api.openai.com/v1`) while **`.env` has no `OPENAI_API_KEY`** → `RuntimeError: Provider 'openai-api' ... no API key`.
- Fix: set **`model.provider`** to **`subapi`** (and matching default model), restart **`hermes-gateway`** — do not assume SubAPI works because the `providers` block exists.

See `vps-operations` → `references/vps1-hermes-subapi-provider-alignment.md` for redacted inspection commands and verification.

## Pitfalls

- When the user wants **SubAPI direct image API only**, do **not** default the answer to Hermes dual-channel — that belongs under `gpt-image-2` / Hermes questions only.
- Do **not** tell the user to change channel settings when the intent is user-visible pricing. Channels are for upstream keys, supported models, and model mapping.
- Older New API UI/docs may call this “倍率设置 / 模型倍率”; newer UI routes may be under `system-settings/billing`.
- Distinguish **model pricing** from **group pricing**: model pricing defines model-level charge ratios/prices; group pricing modifies pricing/availability by group.
- Keep answers short unless the user asks for a walkthrough; for “在哪设置” questions, a direct path plus one caveat is enough.
- After disabling self-use, **unpriced channel models** may stop routing or bill incorrectly — always sync pricing for the full channel list, not only GPT names.
- **Redemption vs billing mode:** missing redemption UI is usually **payment compliance not confirmed**, not “feature disabled on SubAPI” — see redemption quick answer above.
- **Admin top-up vs 账单:** do not tell the user to check **钱包账单** for manual admin quota; point to **日志 → 管理** or `logs.type=3`. **账单** is `top_ups`, not a full balance ledger.
- **Model plaza vs ModelRatio:** do not equate **模型广场** or `/v1/models` with every key in **模型定价 / ModelRatio**; explain homepage vendor logos are not routed models.
- **Postman / API examples for this user:** default to **multiline curl** (`--request`, `--url`, `--header`, `--data`) for Postman **Import → Raw text**; Collection JSON under `templates/` or single-line curl second.
- **Image compat (8328):** never add assistant-style copy around generated images; user wants **official Images fields only** — see `references/subapi-official-images-response-shape.md`.
- **Image UI tools:** when building a customer-facing image-generation page, use the mobile-first credential-first pattern in `references/mobile-image-generation-ui.md`: API base and key at the top, no default-key hints, user-entered credentials used per request, partial-success batch handling, and retry once for transient upstream image errors.

## CLIProxyAPI handoff note

If the user actually meant the `management.html` login on `api.aigcfast.com`, switch to the `cliproxyapi-cpa-ops` skill. That panel uses a management key under `remote-management.secret-key`, not a New API admin password.

## References

- `references/subapi-admin-quota-vs-billing-logs.md` — admin `add_quota` vs `top_ups` (账单) vs `logs` type 1/3; SSH verification; user-facing explanation.
- `references/subapi-redemption-payment-compliance.md` — 兑换码 locked until admin confirms payment compliance; `enable_redemption`, `/api/redemption`, `payment_setting.compliance_*` options.
- `references/subapi-mainland-compliance-sensitive.md` — payment compliance vs PRC GenAI obligations; 敏感词 panel/options; typical 中转 vs 对公众服务分层.
- `references/subapi-image-per-call-pricing.md` — `gpt-image-2` ModelPrice vs ModelRatio; CNY/USD per-image formula; logs verification; quality alias pattern.
- `references/subapi-503-auth-unavailable-relay.md` — SubAPI relay 503 `auth_unavailable` (codex), wallet vs CPA pool, user troubleshoot-only preference.
- `references/subapi-429-relay-diagnostics.md` — SubAPI `relay | 429`, client "exceeded retry limit", codex cooling down vs wallet quota, docker log grep, CPA cross-check.
- `references/subapi-image2-direct-client-runbook.md` — **直接 SubAPI 跑通 gpt-image-2**（面板+curl/SDK+验收+Postman）；用户问「直接调用会不会失败」时优先此文件，**不要默认扯 Hermes**。
- `templates/subapi-gpt-image-2.postman_collection.json` — Postman v2.1 import; variables `subapi_base`, `subapi_key`.
- `references/subapi-single-base-url-messaging.md` — 对外一个地址、两种路径；简单方案不 nginx 转协议。
- `scripts/subapi-image-smoke-test.py` — images 200 + responses/chat 503 三端点探活（`SUBAPI_KEY`）。
- `references/subapi-image-generation-architecture.md` — 「生图用什么方案」: Images REST vs Responses, `/v1/models` image ids, optional Hermes `image_gen`, CPA alias rows.
- `references/subapi-gpt-image-2-hermes-dual-channel.md` — `gpt-image-2` 503 on `/responses`, SubAPI images curl, Hermes `image_gen` + `OPENAI_BASE_URL` dual-channel, 「能转吗」.
- `references/subapi-openresty-image-compat-feasibility.md` — VPS1 OpenResty/1Panel paths, `/cursor/v1` precedent, sidecar vs lua vs friendly 400, external client contract.
- `references/subapi-image-compat-live.md` — **现网 8328** nginx 转 `gpt-image-2`（responses/chat → images → JSON/SSE）、**`response.completed`**、artifacts、流量分析、部署/回滚、多行 curl 验收。
- `references/subapi-official-images-response-shape.md` — 官方 `/v1/images/generations` 无说明文字；8328 禁止侧车文案；`image_generation_call` 映射规则。
- `scripts/subapi-image-compat-stream-verify.py` — 流式 `response.completed` + PNG artifact GET 探活。
- `references/subapi-non-chat-model-audit.md` — image models in `/v1/models` that 503 on chat/responses; abilities vs channels; `gpt-image-1.5` + `gpt-image-2`; remediation.
- `scripts/subapi-probe-chat-vs-images.py` — repeatable chat/responses/images probe for all token-visible models.
- `references/subapi-model-plaza-catalog-count.md` — 模型广场数量 vs ModelRatio/Hermes/CC Switch；`/api/pricing` 与 abilities 对齐验证。
- `references/subapi-model-pricing-route.md` — session-derived route mapping for New API/SubAPI model and group pricing pages.
- `references/subapi-model-cost-adhoc.md` — quote **当前模型费用** from `logs.quota` + ModelRatio/CompletionRatio; CPA has no cost column; CST epoch filter for `logs`.
- `references/subapi-business-mode-pricing-sync.md` — disable self-use + channel-scoped official pricing sync on VPS1 `one-api.db`.
- `vps-operations` → `references/vps1-hermes-subapi-provider-alignment.md` — VPS1 gateway `model.provider` vs `providers.subapi`.
- `scripts/subapi-sync-channel-pricing.py` — dry-run/`--apply` pricing merge for channel-visible models.

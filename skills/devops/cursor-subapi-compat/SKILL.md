---
name: cursor-subapi-compat
description: Cursor IDE：`api.aigcfast.com`（8326 CPA）与 `subapi.aigcfast.com`（8327 SubAPI）两条 /cursor/v1 线、call_id≤64（8326/8327/8328）、排障。
---

# Cursor 兼容入口（SubAPI 与 CPA 两条线）

## Context Usage / 压缩控制

- Context Usage 0% / 未压缩：先看 `references/cursor-context-usage-control.md`。
- Cursor UI 主要吃 Agent checkpoint `tokenDetails.usedTokens/maxTokens`，但 `/cursor/v1` 的 OpenAI-compatible streaming usage **也会影响递增统计**。
- **关键坑（2026-07-01 用户实测确认）：usage 只能出现在最终 `choices: []` chunk。** finish chunk 不带 usage；再发一条 `data: {"choices":[],"usage":{...}}`；然后 `[DONE]`。双写 usage（finish chunk + final chunk）会刷新/重置或显示异常，单尾部 usage 后用户确认“递增，没重置”。详见 `references/cursor-openai-usage-tail-chunk.md`。

## 先认用户实际 Base（必做）

| Override Base | Key | 上游 | 响应头辨认 |
|---------------|-----|------|------------|
| **`https://api.aigcfast.com/v1`** | CPA（如 `tjw`） | **直连** `127.0.0.1:8317`（**不经 8326**） | 通常 **无** `X-Cursor-Cpa-Compat` |
| **`https://api.aigcfast.com/cursor/v1`** | CPA（如 `tjw`） | **8326** → CPA **:8317** | `X-Cursor-Cpa-Compat: direct-cpa` |
| **`https://api.aigcfast.com/tl/cursor/v1`** | CPA（如 `tjw`） | **TrafficLens :8333** → **8326** → CPA **:8317** | `X-TrafficLens-Proxy: cursor-debug` + `X-Cursor-Cpa-Compat: direct-cpa` |

**Cursor Override：禁止 `http://`**（会 `ERROR_BAD_USER_API_KEY`）；`curl` 自测可用 http，与 Cursor 行为无关。
| **`https://subapi.aigcfast.com/cursor/v1`** | SubAPI **`sk-...`** | **8327** → New API **:3000** | `X-SubAPI-Cursor-Compat` |
| **`https://subapi.aigcfast.com/cursor/v2`** | CPA `api-keys` / 别名 | **8326** → CPA **:8317**，**不经 SubAPI/New API** | `X-Cursor-CPA-Compat: direct-cpa` |

**`/cursor/v2` 是同域 direct-CPA 对照实验入口**：当 `/cursor/v1` 出现 `client_gone/context canceled` 时，用它比较“SubAPI/New API 计费链路”与“CPA 直连兼容链路”。Cursor 填 `/cursor/v2` 时必须用 **CPA key/别名**，不是 SubAPI `sk-...`。详见 `references/cursor-v2-direct-cpa-bypass-subapi.md`。

**`/v1` 直连 CPA 可以**，但 **无** 侧车的 `tool_choice→auto`、`call_id` 缩短、模型别名 — Agent 易只回文字。要稳定 tool 循环用 **`/cursor/v1`** 或同域 direct-CPA 测试入口 **`/cursor/v2`**。详见 **`references/cursor-cpa-api-route.md`**。

用户说「走 api.aigcfast.com」时 **不要只修 8327**；`call_id` / `tool_choice` 等要在 **8326** 同步。Nginx：`cursor-cpa-compat.conf` + `root.conf`（`/v1`）。

## SubAPI 方案（计费走 SubAPI 时）

勿用纯 **`/v1`** Override（易 `messages` 错误；Agent 多轮 tool 可能 **`/v1/responses`→8328**）。

## Cursor 填写

| 项 | 值 |
|----|-----|
| Override Base | `https://subapi.aigcfast.com/cursor/v1`（SubAPI）或 **`https://api.aigcfast.com/cursor/v1`**（CPA Agent） |
| API Key | SubAPI `sk-...` 或 **CPA 别名** |
| 协议 | **必须 `https://`**；`http://api.aigcfast.com/...` 在 Cursor 常报 **Invalid API key** |
| 拼写 | `cursor` 非 `cusor` |

**回复风格（本用户）：** CPA/Cursor 运维结论 **短**（表 + 一两句），勿默认长文。遇到 `8317/8326/8327/3000` 这类端口号或内部编号，**禁止裸写数字当主语**；必须先用中文说明“它是什么、为什么存在”，再括号补编号，例如：`CPA 本体（8317）`、`CPA 的 Cursor 翻译服务（8326）`、`SubAPI 的 Cursor 翻译服务（8327）`、`New API/SubAPI 后台（3000）`、`Nginx 前台分流`。不要直接说“8326 有问题/修 8326/把 8326 逻辑移植到 8327”，要说“CPA 的 Cursor 翻译服务负责把 Cursor 请求翻译给 CPA，本次修的是这个翻译层”。

**Cursor 入参排查规则（本用户强偏好）：** 不要只凭结构摘要或字段缺失下结论。用户质疑“Cursor 应该带了/有没有被丢失”时，必须先做从 Cursor 到翻译服务入口的原始请求分析：安全记录顶层字段、`metadata`/`extra_body`、model、stream_options、messages role/keyset；必要时经用户授权临时捕获完整 body 到 VPS 本地文件（不发 Telegram、不记 Authorization/Key，限大小）。如果用户要求连续测试，保持捕获开启直到用户明确说关闭，不要擅自关闭。先证明字段是在 Cursor 入口没发、被模型名编码、藏在 messages，还是翻译层转换时丢失。字段/参数缺失类问题（如 reasoning/usage/metadata/stream_options/MAX/1M）不要只看转换后 payload 或后台计费日志；先在 Cursor 翻译服务入口加安全结构审计确认 Cursor 原始入参是否带字段、是否换字段名、是否藏在 metadata/extra_body/messages。

**Cursor reasoning 默认映射（当前约定）：** Cursor `/cursor/v1` 可能不显式传 `reasoning`/`reasoning_effort`，而是只传模型名。`gpt-5.5` 默认补 `reasoning.effort=high`；只有 `gpt-5.5-extra` / xextra 能力变体补 `reasoning.effort=xhigh`；若客户端显式传 `reasoning`/`reasoning_effort`，必须原样保留，不用模型名覆盖。Codex 走 `https://subapi.aigcfast.com/v1` 时会直接走 Responses API，能显式记录 `reasoning_effort=low|medium|high`，不要把 Codex `/v1` 的行为套到 Cursor `/cursor/v1`。详见 `references/cursor-reasoning-model-alias-and-body-capture.md`。

**翻译层 `MODEL_ALIASES`（Cursor 模型名 → 上游真实模型）：** 在 `scripts/server.py` / `scripts/subapi-server.py` 维护，**8326 与 8327 同步**。当前约定：`gpt-5.5-extra` → `gpt-5.5`；**`gpt-5.4` → `grok-composer-2.5-fast`**（让用户在 Cursor 选 custom-key 友好的 `gpt-5.4`，实际走 CPA 上的 Grok Composer）。改别名后备份、`py_compile`、重启对应 Cursor 翻译服务，并提交技能库 `scripts/`。详见 **`references/cursor-composer-custom-api-keys.md`**。

**改配置后新开 Agent 会话。**

## `/cursor/v2` CPA-bypass A/B test route

When comparing SubAPI-native Cursor behavior against direct CPA behavior on the same public SubAPI domain, expose:

```text
https://subapi.aigcfast.com/cursor/v1  -> SubAPI 的 Cursor 翻译服务（8327）-> New API/SubAPI 后台（3000）
https://subapi.aigcfast.com/cursor/v2  -> CPA 的 Cursor 翻译服务（8326）-> CPA 本体（8317）
```

`/cursor/v2` uses **CPA `api-keys` / aliases**, not SubAPI `sk-...` tokens. Verify by unauthenticated probes: `/cursor/v1/models` should show `X-SubAPI-Cursor-Compat`; `/cursor/v2/models` should show `X-Cursor-CPA-Compat`. Full nginx snippet and smoke tests: `references/cursor-v2-cpa-bypass-route.md`.

## 链路

```text
Cursor → /cursor/v1 → Nginx → 127.0.0.1:8327 subapi-cursor-compat → New API :3000
```

## call_id max 64（高频）

报错 `Invalid 'input[N].call_id': string too long` → **Responses `input[]`**。**裸 `/v1` 直连无截断** → 必须用 **`/cursor/v1`**（8326）或 8327。

- **8326**（`api.aigcfast.com`）：`normalize_request_body` 后转发 CPA（`/root/cursor-cpa-compat/server.py`）。
- **8327**（`subapi.../cursor/v1`）：`normalize_request_body`；`/v1/responses` 改 `input` 后须回写 body。
- **8328**：非 `gpt-image` 透传前同样规范化。

用户问「是不是标识被过滤」时：**先读 8326 源码**——曾删 `metadata`/`stream_options`；**现网应不再删**（`metadata` 可能带 Cursor 会话关联）。响应 **原样转发**，头 **`X-Cursor-CPA-Response-Filter: none`**。

- **HTTP 200 只回计划、不继续 tool**：用侧车审计 `journalctl -u cursor-cpa-compat | grep -E 'req-audit|resp-audit'`。现网 8326 使用**条件 tool_choice**：无 tool result 的首轮工具请求提升为 `required`，一旦消息里已有 `role=tool` / `tool_call_id` 则恢复 `auto` 让模型能收尾；同时 `parallel_tool_calls:false` 提升为 `true`。若 `resp-audit has_tool_calls=False` → 模型/CPA 未出 tool，不是侧车剥响应。若用户使用 `https://api.aigcfast.com/cursor/v1` + CPA 别名（如 `tjw`），Cursor 显示完成但没实际执行，且日志为 `tools>0 tool_choice='auto'` + `has_tool_calls=False finish_hint=stop`，这是模型文本 stop/未发 tool_calls；对明显写/改/执行/保存/文件/文档类任务，在 8326 将 `tool_choice:auto` 提升为 `required`，只保留分析/总结类为 `auto`。详见 **`references/cursor-cpa-actionable-tool-choice-required.md`**、**`references/cursor-cpa-8326-field-filter-and-agent-stops.md`**、**`scripts/verify-cursor-cpa-agent-audit.sh`**。

详见 **`references/call-id-normalization.md`**、**`references/cursor-cpa-api-route.md`**。

- **8326 调试日志开关**：`CURSOR_CPA_DEBUG_SSE=0` 默认关闭详细 `resp-summary events/tail`，只保留轻量 `req-audit`/`resp-audit finish_seen/tool_names/chunks/bytes`。深度排障才临时设 `CURSOR_CPA_DEBUG_SSE=1`，调完必须改回 `0` 并重启 8326；不要长期输出超长 `resp-summary`。该开关与配置要同步提交到私有技能库的 `scripts/server.py` 和 `scripts/cursor-cpa-compat.service`。
- **统一 CPA/SubAPI 的 Cursor 翻译层**：不要长期维护两套独立协议翻译代码。以当前正确的一套为基准，差异只保留为上游后台/监听地址/响应头配置；修任一线的 `usage`、tool bridge、finish_reason、call_id 等协议逻辑时，同步另一线。用户要求“先执行，不要马上重启”时，只替换文件、备份、`py_compile`、静态审计，并用 `MainPID`/`ActiveEnterTimestamp` 证明未重启；等确认后再只重启对应 Cursor 翻译服务。详见 `references/unified-cursor-translation-layer.md`。
- **统一 CPA/SubAPI 的 Cursor 翻译层**：不要长期维护两套独立协议翻译代码。以当前正确的一套为基准，差异只保留为上游后台/监听地址/响应头配置；修任一线的 `usage`、tool bridge、finish_reason、call_id 等协议逻辑时，同步另一线。用户要求“先执行，不要马上重启”时，只替换文件、备份、`py_compile`、静态审计，并用 `MainPID`/`ActiveEnterTimestamp` 证明未重启；等确认后再只重启对应 Cursor 翻译服务。详见 `references/unified-cursor-translation-layer.md`。
- **Cursor 推理难度与 `*-extra` 模型别名**：Cursor 自定义 OpenAI Base 可能不传标准 `reasoning` / `reasoning_effort`，而是用模型名表达难度。当前约定 `gpt-5.5-extra` = `gpt-5.5` + `reasoning.effort=xhigh`（不是 high）。显式 `reasoning` / `reasoning_effort` 必须原样保留，不要把用户显式 high 自动升级。若怀疑 Cursor 用别的字段，先加临时安全 `cursor-shape` 审计：只记录顶层字段、metadata/extra_body key、reasoning-like key、messages/input 数量/role/keyset，禁止记录正文、Key、tool arguments/output。若用户授权 full body 捕获，保存到 VPS 本地文件分析，不要发完整 body 到 Telegram；用户要求保持开启时不要自行关闭。Codex 走 `/v1/responses` 可显式带 `reasoning_effort`，不要和 Cursor `/cursor/v1` 的 ChatCompletions 形态混淆。详见 `references/cursor-extra-reasoning-alias-and-shape-audit.md` 与 `references/cursor-v1-vs-codex-v1-reasoning-and-context.md`。
- **`/cursor/v1` 不显示上下文/Token 使用量**：CPA/SubAPI 的 Cursor 翻译服务把 Cursor 的 ChatCompletions 流式请求转成 Responses，再转回 ChatCompletions SSE；若只转文本/tool_calls/finish_reason，就会丢 usage。保留 `stream_options.include_usage`，从 Responses SSE 的 `usage` / `response.usage` 捕获用量。**给 Cursor 的流式返回应按 OpenAI 形态在 `[DONE]` 前单独发送 `choices: []` 的 usage-only chunk**，不要只把 `usage` 附在 `finish_reason` chunk 上；Cursor 可能忽略后者并让 Context Usage UI 维持 `0%`。详见 `references/cursor-cpa-streaming-usage-stats.md` 与 `references/cursor-context-usage-ui-and-usage-chunk.md`。
- **`/cursor/v1` Context Usage 面板不准/一直 0%**：先分清三层：Cursor 翻译服务入口 `cursor-shape raw_len/messages._summary`、桥接返回 `usage-audit sent_usage_chunk=True prompt=...`、New API `prompt_tokens`。若入口 raw body 与服务端 usage 都是十万级，但 Cursor 面板仍显示几百 token，则不要判断为“少乘 1000”或继续改 usage 字段；该面板大概率是 Cursor 本地 UI 对 system/tools/rules/skills/MCP/conversation 的 context composition 估算。`/cursor/v1/models` 当前也不返回 `context_window`/`max_context`，所以 `272K` 不是从 SubAPI models 里来的。详见 `references/cursor-context-usage-panel-vs-api-usage.md`。
- **代码提交要求**：修复现网 8326 时，不只提交文档；必须把当前 `/root/cursor-cpa-compat/server.py`、Nginx snippet、systemd service 同步到 `TangGV/hermes-self-iteration-skill` 的 `skills/devops/cursor-subapi-compat/scripts/`，`py_compile` 通过后再 commit/push。

## 本机「访问不过去」与 Rate limit

CPA Base 时优先 **`cliproxyapi-cpa-ops`** → `references/cpa-windows-local-client-proxy.md`（Windows **7890**、`curl --noproxy`、**401**=打到 CPA）与 `references/cpa-client-api-key-rate-limit.md`（**429** vs **500 EOF** vs UI 误报）。**能 401/200 到 VPS** 不等于 Cursor Agent 正常 — Agent 仍用 **`/cursor/v1`**。

## 其他排障

- **`This model does not support custom API keys` / `ERROR_BAD_REQUEST`（workbench 堆栈）** → 选了 **官方 Composer**（如 Composer 2.5 Fast），**未到** `/cursor/v1`；改选 **`gpt-5.5` 或 `gpt-5.4`**（后者经别名走 `grok-composer-2.5-fast`）。详见 **`references/cursor-composer-custom-api-keys.md`**。
- `field messages is required` → 用了 `/v1` 而非 `/cursor/v1`
- `ERROR_BAD_USER_API_KEY` → 先查 **https** + CPA 别名；SubAPI 线且无 VPS `/cursor/v1` 日志 → 未到 SubAPI
- Agent 不写文件 → 须保留 `/chat/completions` + `tool_calls` 转换，勿仅文本 SSE
- **`/cursor/v1` 不断重复执行 / 工具循环停不下来**：不要只看 8326 `resp-audit has_tool_calls=True` 就判断 Cursor 该继续。Chat-via-Responses 桥接的终止条件必须看**最后一个 assistant 输出类型**：最后是 function_call 才 `finish_reason=tool_calls`；若先有 tool_call 后又输出最终文本 / Done / `response.completed`，应返回 `finish_reason=stop`。旧逻辑 `finish_reason = "tool_calls" if saw_tool else "stop"` 会把已完成的一轮误报成还需工具，导致 Cursor 再发下一轮。详见 `references/cursor-cpa-responses-finish-reason-loop.md`。
- **HTTP 200 但 UI 停在「收到，我现在去改…」** → 先对 `access.log` + CPA `main.log`；若 200 且无后续 POST，多为 **无 `tool_calls` 或 Cursor 未发下一轮**，不是侧车删响应字段（8326 不剥 `tool_calls`）。**远程 TL 无 aigcfast 但 8326 有 req-audit** → Override 未走 18888，见 `references/trafficlens-remote-vps1-cursor-analysis.md`、`references/cursor-v1-override-vs-remote-tl.md`。
- **`/cursor/v1` 提示完成但实际没继续执行**：若 8326 审计是 `tools>0` + `tool_choice='auto'` + `has_tool_calls=False` + `finish_hint=stop`，且 CPA `failed=0` / TTFT 正常，则不是断流/TTFB，而是模型选择了纯文本收尾，Cursor 合法结束。优先修 `/root/cursor-cpa-compat/server.py` 的条件 `tool_choice: required` 策略或加 `resp-audit text_prefix`，不要先重启 CPA/New API。详见 `references/cursor-cpa-8326-auto-stop-no-toolcalls.md`。
- **`/cursor/v1` 不断重复执行 / 循环**：先查 1Panel/OpenResty access log 与 8326 `req-audit`/`resp-audit`。若同一 Cursor 云端 IP 反复 POST `/cursor/v1/chat/completions`，且每轮 `has_tool_calls=True`、HTTP 200、CPA `failed=0`，说明不是 CPA/New API 故障，也不是 8326 自循环，而是 Cursor Agent 正在持续执行 tool-call rounds；先建议用户在 Cursor 停止/取消当前 Agent，会话级止血优于重启 CPA。详见 `references/cursor-cpa-repeated-agent-loop-triage.md`。
- **SubAPI `/cursor/v1` 频繁 `client_gone` / `context canceled`**：不要先调 nginx/New API timeout，也不要从单条 CPA/New API 日志判断“次次请求都坏”。先用 `journalctl -u subapi-cursor-compat` 统计 `cursor-shape`、`resp-audit`、`write_broken=True`、`finish_seen=tool_calls|stop|None` 的占比，再对齐 New API `stream_status.end_reason='client_gone'`。若多数 `resp-audit` 正常且少数 `write_broken=True`，说明路径不是全局故障；常见于 `gpt-5.5-extra` / `reasoning=xhigh` / 大 raw body 长流时客户端提前断开。若 `resp-audit has_tool_calls=True finish_seen=tool_calls` 且几秒内有下一条 `cursor-shape`、raw_len 增长，通常是 Cursor 收到 tool_call 后关闭当前流并进入下一轮工具执行，New API 记成 `client_gone`，不是服务端短超时。若要隔离 SubAPI/New API 计费链路，新增/使用同域 **`/cursor/v2` direct-CPA** 对照：`subapi.aigcfast.com/cursor/v2 -> CPA 的 Cursor 翻译服务（8326） -> CPA 本体（8317）`，详见 `references/cursor-v2-direct-cpa-bypass-subapi.md`。Nginx `/cursor/v1` 仍应核对 `proxy_read_timeout/proxy_send_timeout`、buffering off、error.log。真实优化点在翻译层：BrokenPipe/ConnectionReset 时显式关闭 upstream response，并记录 `write_broken` / `tool_handoff_disconnect`。详见 `references/subapi-cursor-client-gone-triage.md`。
- **SubAPI `/cursor/v1` frequent `client_gone` or low cache:** first distinguish bridge artifacts from real upstream failures. If SubAPI's Cursor translation service returns `finish_seen=tool_calls` and Cursor immediately sends the next Agent round, New API may log `client_gone/context canceled` when the bridge stops reading upstream too early; fix by draining upstream SSE to EOF after sending ChatCompletions `[DONE]`. For low `cached_tokens`, do not blame CPA `round-robin` until CPA Usage Keeper proves multiple active `source/auth_index` values; a single account can still show 0% cache when multiple Cursor Agent prefix streams/model-paths interleave. See `references/subapi-cursor-client-gone-cache-diagnostics.md`.
- **SubAPI `/cursor/v1` xhigh 超长等待但 Codex CLI 更大上下文正常：**不要只归因于上下文大。对比 New API `logs.other.admin_info.channel_affinity`：Codex CLI 通常带 `prompt_cache_key`，New API 以 `key_path=prompt_cache_key` 固定 channel/provider cache；Cursor 自定义 OpenAI 请求顶层常只有 `messages/model/stream/stream_options/tools/user`，没有 `prompt_cache_key`。若慢请求表现为 `admin_info.channel_affinity` 缺失、`cache_tokens` 低/0、`use_time` 100–300s，应在 SubAPI 的 Cursor 翻译服务 `chat_to_responses_payload()` 中保留已有 `prompt_cache_key`，无则基于 `model + user` 合成稳定 `prompt_cache_key` 后转发 `/v1/responses`。验证标准：后续 `/cursor/v1` 账本出现 `channel_affinity.key_path=prompt_cache_key`，xhigh 大上下文 cache 命中恢复，耗时降到十几/几十秒。详细排查/修复/合成探针见 `references/cursor-subapi-prompt-cache-affinity.md`。详细排障与验证见 `references/cursor-subapi-prompt-cache-affinity.md`。
- **Cursor `/cursor/v1` 长等待 / `ERROR_NETWORK_ERROR` / `[resource_exhausted]` 但 Codex CLI 更大上下文正常：不要先归因“大上下文+xhigh”。先对比 New API `logs.other.admin_info.channel_affinity`、`cache_tokens/prompt_tokens` 和桥接入口 `cursor-shape`。已验证一类根因是 SubAPI 的 Cursor 翻译层把 ChatCompletions+tools 转 `/v1/responses` 后未携带/生成 `prompt_cache_key`，导致 New API 无 `channel_affinity`、缓存命中率大跌；无 affinity 的 `xhigh` 请求平均/尾延迟可比有 affinity 高数倍。修复方向：保留 Cursor 原始 `prompt_cache_key`，若缺失则基于安全稳定会话字段合成，确保 New API affinity 规则命中。详见 `references/cursor-subapi-prompt-cache-key-affinity.md`。
- **subapi3 `/cursor/v1` 首次满上下文后后续 Context Usage 永远 0%：**不要用本机 Cursor CLI `composer-2.5` 成功就判定链路正常；CLI 可能走 Cursor 官方 Agent/`api2.cursor.sh`，未命中 subapi3。必须看 VPS3 `subapi-cursor-compat` 是否出现新的 `cursor-shape`。若真实 `/cursor/v1` 日志有 `raw_len≈1.2–1.35MB`、`reasoning='xhigh'`，但 `resp-audit usage_seen=False usage_out=False usage_fallback=False`，直接检查服务环境是否缺少 `CURSOR_EMIT_USAGE_PREROLL=1`。已知 VPS2 正常口径是 `CURSOR_EMIT_USAGE_PREROLL=1` + `CURSOR_EMIT_USAGE_CHUNK=0`：预发估算 usage 给 Cursor，且不发尾部 usage 避免 UI 覆盖/重置。只重启 SubAPI 的 Cursor 翻译服务，不动 New API/CPA；再验证 `usage_seen=True usage_out=True usage_fallback=True write_broken=False`。若 usage 已正常但仍卡住，继续对比官方 Composer 2.5 的工具分段/cache/blob 流与 SubAPI 的大 `messages` payload；重点识别 `chunks<=4`、`bytes≈554/358`、无有效内容/tool_calls 的上游空短流，不要把它包装成正常 `finish_reason=stop` + fallback usage。**若用户明确说“不做大 raw_len + xhigh 降级/分流”，禁止实现模型降级；改协议语义：延迟发送 200 SSE 头，只有见到 `delta.content` 或 `delta.tool_calls` 才转正常流；若上游空短流，先用 salted `prompt_cache_key` 自动重试一次（不改模型/effort），仍空再以 200 SSE 返回明确诊断，避免 Cursor 把非 2xx 误显示成 `User API Key Rate limit exceeded`。**若 UI 卡在 `Planning next moves` 但日志仍为 `has_tool_calls=True/finish_seen=tool_calls/status=ok`，这是 Cursor 多轮工具循环或上游慢，不是空流；用 `resp-audit`/`slow-audit` 的 `raw_len/model/reasoning/tools/upstream_open_ms/first_output_ms/elapsed_ms/tool_names/status` 定位慢段。详见 `references/subapi3-cursor-v1-context-usage-preroll.md`、`references/subapi3-cursor-usage-preroll-sync.md`、`references/cursor-official-composer-vs-subapi-100-context.md`、`references/cursor-subapi-empty-upstream-completion.md`、`references/cursor-subapi-slow-audit.md`。
- **需要包体级确认时**：让 Cursor 改填 **`https://api.aigcfast.com/tl/cursor/v1`**，走 TrafficLens→8326→CPA；看 `/var/log/trafficlens/cursor-debug.jsonl`，不要把普通 Nginx/8326/CPA 日志分析误称为 TrafficLens 分析。详见 `references/trafficlens-cursor-debug-route.md`。
- **Windows 本地/远程抓 Cursor**：只想抓指定进程时，**禁止默认** `trafficlens.exe proxy-on`。远程 VPS1：**`cursor-tl-launcher.exe`**（内置 `45.143.233.108:18888` + 包内 `vps1-trafficlens-ca.crt`）。本地 MITM：**`win-start-cursor.ps1`** 或 **`win-start-mitm.ps1 -SkipSystemProxy`**。已打开的 Cursor **不会**继承代理；启动器应杀旧进程或让用户先全关 Cursor。详见 `references/trafficlens-windows-cursor-process-scope.md`。
- **本机「CLI 分析流量」/ Context 0% vs 大 raw_len**：用户问「**我们不是做了流量分析吗**」→ **先 TrafficLens**（远程 **`win-start-cursor-vps1-remote.ps1`** / **`cursor-tl-launcher`** → VPS1 **`remote-cursor-mitm.jsonl`**；或 **`/tl/cursor/v1`** → **`cursor-debug.jsonl`**），再 **`cursor.requestTraces.log`**（`getBlob.slow` / `writeInitialRequest`），最后 **8327 `raw_len` + `usage_seen`**。Windows **没有** Cursor 内置明文抓包 CLI。Override **subapi/api `/cursor/v1` 直连时常不进 18888 JSONL**，不能因 TL 无行否认流量。详见 **`references/trafficlens-triage-flow-context-and-empty-stream.md`**、**`references/cursor-request-traces-local-traffic-analysis.md`**。
- **Windows TrafficLens GUI `TTM_ADDTOOL failed`**：这是本地 `github.com/lxn/walk` / Win32 Tooltip 初始化问题，不是 Cursor/CPA/SubAPI 请求链路。先查 `cmd/trafficlens-gui/main_windows.go`、`CueBanner`/隐式 tooltip、最小窗口二分；交接见 `references/trafficlens-windows-gui-tooltip-handoff.md`。
- **远程 TL 对比正常 Cursor vs `/cursor/v1`**：用户要把 Cursor 流量打到远程给我们分析时，优先 **VPS1** `http://45.143.233.108:18888`（**HTTP CONNECT 代理，不是 WebSocket**）+ Windows **`cursor-tl-launcher.exe`** / 双击 **`start-cursor-vps1-trafficlens.cmd`**（v0.3.25+ zip；可解压到任意盘如 `G:\Downloads\trafficlens-windows-amd64`）。**默认不要**建议 `proxy-on` 改系统代理。用户明确要求 **不要限制 IP** 时，删掉 nft/iptables 上对 `18888` 的 per-source accept + 末尾 drop，不要只加白名单。用户说 **触发了** 时：先看 JSONL 是否增长 + `api2`；若 Override `/cursor/v1` 但 JSONL 仍无 `aigcfast`，**同时**查 8326 `req-audit`/`resp-audit`（Override 常不经 TL）。详见 `references/trafficlens-remote-vps1-cursor-analysis.md`、`references/cursor-v1-override-vs-remote-tl.md`。
- **Cursor Agent 官方链路**：CLI/Agent 常打 `api2.cursor.sh` / `repo*.cursor.sh` / `agent*.cursor.sh`，主体多为 `application/proto` / Connect/gRPC-like；用 TL v0.3.22+ 的 `proto` 摘要、embedded JSON、`cursor_hints` 判断，不要只套 OpenAI JSON/SSE。详见 `references/trafficlens-windows-cursor-process-scope.md`。
- **Cursor 云端代理现象**：Override Base 请求到 VPS 时，access log 里可能是 AWS Cursor 后端 IP（如 `52.44.113.131`、`184.73.225.134`），不是用户本机公网 IP；本机 TrafficLens 只看到 `api2.cursor.sh` 不代表 `/cursor/v1` 没打到 VPS。
- **`/cursor/v2` direct-CPA bypass for A/B testing**：当用户要比较 SubAPI/New API 计费路径和直连 CPA 路径时，可在同一公开域名下保留 `/cursor/v1` 给 SubAPI key，新增 `/cursor/v2` 指向 CPA 的 Cursor 翻译服务；`/cursor/v2` 必须使用 CPA `api-keys`/别名。用无 Key 探活头区分：`/cursor/v1` 应有 `X-SubAPI-Cursor-Compat`，`/cursor/v2` 应有 `X-Cursor-CPA-Compat: direct-cpa`。详见 `references/cursor-v2-direct-cpa-bypass.md`。
- **`/cursor/v1` 不断重复执行 / 停不下来**：先判定是否真走 8326（access log `/cursor/v1` + 8326 `req-audit`/`resp-audit`），不要把裸 `/v1/chat/completions` 的 CPA usage 混成 8326 问题。必须审计最终发给 Cursor 的 `finish_reason`（如 `finish_seen=tool_calls|stop|None`）和 Responses SSE 原始事件摘要。重点查两个桥接坑：
  1. Responses 可能同时发送 `response.function_call_arguments.delta` 与 `response.output_item.done.item.arguments`，ChatCompletions SSE 只能给 Cursor 拼一次参数；双发会把 JSON arguments 拼坏，引发工具异常/重试/循环。
  2. 最终文本不一定是 `response.output_text.delta`，也可能是 `response.output_item.done item.type=message` 或 `response.output_text.done`；这些应把 `last_output_kind` 标为 text 并最终返回 `finish_reason=stop`。
  不要把“超过 N 次工具调用强制 stop”当正式修复；这只是临时止血，会掩盖协议层根因。若最后确实是 `function_call CreatePlan`，那不是 stop 漏识别，而是模型/Agent 真实要求工具，需区分 Cursor 工具内部 `/v1/responses` 调用与 8326 主链路。修复后用真实 stream probe 验证公网仍是 `text/event-stream` 打字机效果。详见 `references/cursor-cpa-createplan-repeat.md` 与 `references/cursor-cpa-responses-sse-repeat-loop.md`。
- **`/cursor/v1` 直连 CPA Agent 显示 Done 但没执行工具**：若 `req-audit tools>0 tool_choice='auto|required'`，但 `resp-audit has_tool_calls=False finish_hint=stop`，且 CPA `failed=0`/TTFT 正常，说明 ChatCompletions 路径返回了纯文本 stop，Cursor 合法结束。仅强制 `tool_choice=required` 可能无效；对带 tools 的 Cursor Agent 请求应考虑 `chat/completions -> /v1/responses -> ChatCompletions SSE tool_calls` 桥接。注意 Responses 输入里 assistant 历史内容必须是 plain string 或 `output_text`，不能误转 `input_text`，否则会报 `Invalid value: 'input_text'. Supported values are: 'output_text' and 'refusal'`。详见 `references/cursor-cpa-chat-via-responses-tool-bridge.md`。
- **临时强制工具实验**：可短期把 8326 的 `tool_choice` 从 `auto` 改为 `required` 验证模型是否被迫出 tool；必须备份、`py_compile`、只重启 8326，并保留回滚路径。详见 `references/trafficlens-cursor-debug-route.md`。

详见 **`references/cursor-pitfalls.md`**、**`references/cursor-cpa-8326-field-filter-and-agent-stops.md`**、**`references/trafficlens-cursor-debug-route.md`**、**`references/trafficlens-windows-cursor-process-scope.md`**。

## 与 gpt-image

`gpt-image-2` 对话路径见 **`subapi-gpt-image2-compat`**（8328）；Cursor 选生图模型走对话仍会 503，除非客户端用 Images API。

## VPS 克隆 / 迁移验证（关键坑）

**仅检查 systemd 状态和端口不够。** VPS1→VPS2 克隆翻译层后必须验证**实际代码内容**，不是只看 `systemctl is-active`。

全量迁移审计还包括 SubAPI DB 完整性、CPA 密钥、SSL 证书、DNS 等 — 见 `vps-operations` → `references/vps-migration-audit-checklist.md`。

### 已知翻车场景

VPS2 克隆后 `cursor-cpa-compat`（8326）仍为旧版代码，保留了 `high→xhigh` 自动提升逻辑（见 `references/cursor-reasoning-model-alias-and-body-capture.md` 最终约定 `gpt-5.5→high`、只有 `gpt-5.5-extra→xhigh`），而 `subapi-cursor-compat`（8327）已是新版。两条线代码结构不同时，nginx 路由决定实际命中的版本。

### 验证清单（每项都得过）

```bash
# 1. 两线的 reasoning 映射是否对
grep -n "reasoning\|gpt-5.5\|xhigh" /root/cursor-cpa-compat/server.py | head -20
grep -n "reasoning\|gpt-5.5\|xhigh" /root/subapi-cursor-compat/server.py | head -20

# 2. high→xhigh 自动提升是否已删除（应为否）
grep -c "high.*xhigh\|promote.*xhigh" /root/cursor-cpa-compat/server.py

# 3. CURSOR_FULL_CAPTURE 应为 0 或不存在
grep -c "CURSOR_FULL_CAPTURE\|full.capture" /root/sursor-cpa-compat/server.py
grep -c "CURSOR_FULL_CAPTURE\|full.capture" /root/subapi-cursor-compat/server.py

# 4. nginx /cursor/ 路由指向正确（应为 8326 或 8327 视情况）
grep -A3 "cursor" /etc/nginx/sites-enabled/api2.aigcfast.com
```

### 从本地仓库部署到 VPS2（当代码过期时）

来源（Windows 本机）：
- CPA 翻译层 → `C:\Users\t\hermes-self-iteration-skill\skills\devops\cursor-subapi-compat\scripts\server.py`
- SubAPI 翻译层 → `C:\Users\t\hermes-self-iteration-skill\skills\devops\cursor-subapi-compat\scripts\subapi-server.py`

目标（VPS2 `62.106.70.67`）：
- `/root/cursor-cpa-compat/server.py`（监听 `127.0.0.1:8326`，上游 CPA `127.0.0.1:8317`）
- `/root/subapi-cursor-compat/server.py`（监听 `127.0.0.1:8327`，上游 SubAPI `127.0.0.1:3000`）

```bash
# 1. 备份
ssh root@62.106.70.67 \
  "cp /root/cursor-cpa-compat/server.py /root/cursor-cpa-compat/server.py.bak-\$(date +%Y%m%d-%H%M%S) && \
   cp /root/subapi-cursor-compat/server.py /root/subapi-cursor-compat/server.py.bak-\$(date +%Y%m%d-%H%M%S)"

# 2. 部署
scp -i ~/.ssh/id_ed25519 \
  "/c/Users/t/hermes-self-iteration-skill/skills/devops/cursor-subapi-compat/scripts/server.py" \
  root@62.106.70.67:/root/cursor-cpa-compat/server.py
scp -i ~/.ssh/id_ed25519 \
  "/c/Users/t/hermes-self-iteration-skill/skills/devops/cursor-subapi-compat/scripts/subapi-server.py" \
  root@62.106.70.67:/root/subapi-cursor-compat/server.py

# 3. 重启并确认
ssh root@62.106.70.67 "systemctl restart cursor-cpa-compat subapi-cursor-compat && sleep 2 && \
  ss -tlnp | grep -E '8326|8327'"
```

**部署后必须再跑一遍上面的验证清单**，确认 reasoning 映射、无 high→xhigh 提升、CURSOR_FULL_CAPTURE 状态。

## 私有仓库

`TangGV/hermes-self-iteration-skill` → `skills/devops/cursor-subapi-compat/`（含 `scripts/server.py`）。

## 相关文档

- `references/call-id-normalization.md` — **call_id≤64**（8326/8327/8328）
- `references/cursor-cpa-api-route.md` — **api.aigcfast.com**：`/v1` 直连 CPA vs `/cursor/v1` 8326
- `references/cursor-cpa-8326-field-filter-and-agent-stops.md` — **metadata/标识**、200 但 Agent 停住、**req/resp-audit**
- `references/trafficlens-cursor-debug.md` — **TrafficLens** `/tl/cursor/v1` 包体级流量解析、JSONL/SSE/tool_calls 判断
- `references/trafficlens-triage-flow-context-and-empty-stream.md` — **先 TL 再 requestTraces 再 8327**：0% vs 大 `raw_len`、subapi Override 不进 JSONL、空流 `bytes≈358 usage_seen=False`、远程启动器复现
- `references/trafficlens-windows-cursor-process-scope.md` — Windows 本地只抓 Cursor 进程、`win-start-cursor.ps1`、`-SkipSystemProxy`、Cursor Agent proto 观测与 release 验收
- `references/trafficlens-remote-vps1-cursor-analysis.md` — VPS1 远程 TL、`cursor-tl-launcher`、**18888=HTTP 非 WS**、**不要限制 IP**、官方 vs `/cursor/v1` 对比
- `references/cursor-v1-override-vs-remote-tl.md` — Override `/cursor/v1` **常不进 18888 JSONL**；须并用 8326 审计判断
- `scripts/verify-cursor-cpa-agent-audit.sh` — VPS 上查 8326 审计行
- `scripts/summarize-vps1-remote-cursor-jsonl.py` — VPS1 上只读汇总 `remote-cursor-mitm.jsonl`（hosts/客户端 IP/Agent 相关 path）
- `references/cursor-cpa-actionable-tool-choice-required.md` — **Cursor `/cursor/v1` 显示完成但没执行**：`tools>0 tool_choice=auto` + `has_tool_calls=False stop` 时，对明显写/改/执行类任务在 8326 强制 `tool_choice=required`，保留分析/总结为 `auto`。
- `references/cursor-cpa-chat-via-responses-tool-bridge.md` — **api.aigcfast.com/cursor/v1** direct-CPA Cursor Agent stops after prose/Done: Cursor cloud IPs, why Chat `tool_choice=required` may still return text `stop`, and the durable chat-via-Responses SSE `delta.tool_calls` bridge pattern.
- `references/cursor-cpa-createplan-repeat.md` — **api.aigcfast.com/cursor/v1** repeated execution after tool calls: finish by last output kind, message item final text, function_call argument delta/done de-duplication, and how to distinguish real `CreatePlan` loops from missed stop handling.
- `references/cursor-cpa-finish-reason-loop-guard.md` — **/cursor/v1 反复工具执行/断了又继续**：Responses→ChatCompletions 桥接必须按最后输出类型决定 `finish_reason`，审计 `finish_seen=stop|tool_calls`，必要时用 `LOOP_GUARD_TOOL_RESULTS` 止血。
- `references/cursor-cpa-responses-sse-repeat-loop.md` — **Cursor `/cursor/v1` 不断重复执行**：不要用 loop guard 掩盖；区分 `/cursor/v1` 与裸 `/v1`；审计 `finish_seen`、Responses SSE events；避免 `function_call_arguments.delta` 与 `output_item.done.arguments` 双发导致 Cursor 参数 JSON 重复/损坏；识别 `item.type=message` 作为最终文本 stop。
- `references/cursor-cpa-streaming-usage-stats.md` — `/cursor/v1` streaming usage chunk shape and bridge-side `usage` capture.
- `references/cursor-context-usage-panel-vs-api-usage.md` — Cursor Context Usage panel may stay small even when `/cursor/v1` returns large OpenAI-compatible `usage`; includes `usage-audit`/New API comparison and the “not *1000” conclusion.
- `references/cursor-context-usage-proto-fields.md` — 本地 Cursor bundle 证据：Context Usage tray 读取 `agent.v1.ConversationTokenDetails.used_tokens/max_tokens` 与 `PromptTokenBreakdownSnapshot.categories[].estimated_tokens`，不是直接读取 OpenAI `usage.prompt_tokens`；保留 usage chunk 但不要把面板 0%/1% 直接归因给 `/cursor/v1` usage 缺失。
- `references/cursor-context-usage-local-panel-analysis.md` — 本机 Cursor CLI/logs 证据：`272K` 来自 local `model_params.context`，面板总数等于 System/Tools/Rules/Skills/MCP/Conversation 分项求和，非 API usage。
- `references/cursor-request-traces-local-traffic-analysis.md` — **无 MITM 时**本机 `cursor.requestTraces.log`：Blob/getBlob、writeInitialRequest、0% 与 ~1MB raw_len 对拍、8327 空流 `bytes≈358 usage_seen=False`
- `references/cursor-context-usage-vs-subapi-body.md` — **面板 0% / 未压缩** 与 **`raw_len` ~1MB**、**gpt-5.5+xhigh 0 token 空流**（`bytes≈358 usage_seen=False`）；勿把 1.1MB 说成 1M token
- `references/cursor-pitfalls.md` — 排障速查
- `references/cursor-composer-custom-api-keys.md` — **Composer vs custom key**、Request ID 未到 VPS、`gpt-5.4` → `grok-composer-2.5-fast` 别名
- `cliproxyapi-cpa-ops` → `references/cpa-windows-local-client-proxy.md`、`references/cpa-client-api-key-rate-limit.md` — 本机代理与 CPA 限流文案"
# Cursor Context Usage 0% / reset 修正记录（2026-07-01）

## 背景

用户在 Cursor 中使用：

- Base URL：`https://subapi.aigcfast.com/cursor/v1`
- 模型：`gpt-5.5-extra` / `gpt-5.4`
- 兼容层：VPS2 `subapi-cursor-compat`，本机监听 `127.0.0.1:8327`

现象：

1. Cursor 面板 `Context Usage` 长期显示 `0%`。
2. 同一会话服务端 `cursor-shape raw_len` 可见 174KB ～ 1.1MB。
3. 截图一度出现 `-613 / 272K Tokens`，分类合计为 613（`System prompt 75 + Tool definitions 239 + Rules 27 + Skills 55 + MCP 47 + Subagent definitions 25 + Conversation 145`），说明 Cursor 内部 UI 曾被错误刷新成负数。
4. 后续发现：单位为 K 时首次显示正常，但再次触发会被刷新；修正后变为递增，不再重置。

## 本地 Cursor 反编译结论

Cursor 3.9.16 本地安装包：

```text
C:\Users\t\AppData\Local\Programs\cursor\resources\app\out\vs\workbench\workbench.desktop.main.js
```

关键逻辑：

```js
function eIy(n,e){
  if(!n || n.maxTokens <= 0) return;
  const t = n.maxTokens;
  const i = Math.min(n.usedTokens, t);
  return {
    contextUsagePercent: i / t * 100,
    contextTokensUsed: e ? i : void 0,
    contextTokenLimit: e ? t : void 0
  }
}
```

Cursor UI 的 Context Usage 优先取：

- `contextTokensUsed / contextTokenLimit`
- 否则退回 `contextUsagePercent`
- 这些来自 `conversationState.tokenDetails` / checkpoint

同时本地代码也解析 OpenAI usage：

- Chat Completions：`usage.prompt_tokens` / `usage.completion_tokens` / `usage.total_tokens`
- Responses：`usage.input_tokens` / `usage.output_tokens` / `usage.total_tokens`

但普通 OpenAI usage 并不是 Cursor Context Usage 的唯一来源；它能影响递增统计，但不会提供完整 `promptContextUsageTree`。

## 修正方案演进

### 第一版：补流尾 usage chunk（实验）

在 `subapi-server.py` 的 Responses→Chat SSE 转换中，增加标准 OpenAI 流式 usage chunk：

```text
data: {"choices":[],"usage":{...}}
data: [DONE]
```

实现函数：

- `normalize_usage(usage)`：把 Responses usage 转成 Chat Completions usage 形态。
- `estimate_chat_prompt_usage(obj, raw_len)`：当上游没有 usage 时按请求体粗估 prompt tokens，只用于 Cursor UI，不用于 SubAPI/NewAPI 计费。
- `chat_usage_chunk(resp_id, model, usage)`：生成 `choices: []` usage chunk。

验证：

```text
usage_seen=True usage_out=True usage_fallback=False
```

### 第二版：只在最终 `choices: []` chunk 带 usage

第一版曾同时在 finish chunk 和最后 `choices: []` chunk 带 usage：

```text
data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{...}}
data: {"choices":[],"usage":{...}}
```

用户反馈 UI 会被再次触发刷新/重置。

修正为严格标准尾部形态：

```text
data: {"choices":[{"delta":{},"finish_reason":"stop"}]}
data: {"choices":[],"usage":{...}}
data: [DONE]
```

验证结果：

```text
bytes 1348
usage_count 1
choices_empty 1
finish_has_usage False
```

用户反馈：**这次是递增的了，没重置**。

## 现网验证命令

在 VPS2 上用有效 SubAPI token 触发：

```bash
curl -sS -N https://subapi.aigcfast.com/cursor/v1/chat/completions \
  -H "Authorization: Bearer $SUBAPI_KEY" \
  -H "Content-Type: application/json" \
  --data @- <<'JSON' >/tmp/cursor_usage_test.sse
{"model":"gpt-5.4","stream":true,"messages":[{"role":"user","content":"请只回复 ok。"}],"tools":[{"type":"function","function":{"name":"noop","description":"no op","parameters":{"type":"object","properties":{}}}}]}
JSON

python3 - <<'PY'
s=open('/tmp/cursor_usage_test.sse',encoding='utf-8',errors='ignore').read()
print('bytes',len(s),'usage_count',s.count('"usage"'),'choices_empty',s.count('"choices":[]'))
pre=s.split('"choices":[]')[0]
print('finish_has_usage', ('"finish_reason":"stop"' in pre or '"finish_reason":"tool_calls"' in pre) and '}],"usage"' in pre)
print('\n'.join(s.strip().splitlines()[-10:]))
PY
```

期望：

```text
usage_count 1
choices_empty 1
finish_has_usage False
```

8327 日志期望：

```text
resp-audit ... usage_seen=True usage_out=True usage_fallback=False
```

若上游没 usage 但 fallback 估算生效：

```text
usage_seen=True usage_out=True usage_fallback=True
```

其中 `usage_seen=True` 是审计样本中看到了输出 usage，不等于上游真实 usage；需结合 `usage_fallback` 区分。

## 相关提交

```text
13a4d95 Add Cursor usage chunk fallback
82ec3c7 Send usage only in final SSE chunk
```

## 关键注意事项

1. **最终有效方案**：现网开启 `CURSOR_EMIT_USAGE_PREROLL=1`、关闭 `CURSOR_EMIT_USAGE_CHUNK=0`。
2. 形态是：模型开始输出前先发一条估算 `choices: [] + usage`，后续正常流，结尾不再发 usage。这样 Cursor 过程里能先看到上下文统计，结束时也不会再次覆盖。
3. **不要**在 finish chunk 和 final chunk 双写 usage；双写会导致 Cursor 重新刷新/覆盖，用户观察到会重置。
4. **不要**只在最后 `choices: []` 发 usage；用户确认这种方案“结束才有统计”，且仍可能覆盖 Cursor 自己的 K 级统计。
5. `estimate_chat_prompt_usage()` 的估算 usage **只用于响应给 Cursor UI**，不得用于计费。
6. `Context Usage` 仍可能不等价于服务端 `raw_len`，大请求保护仍应看 `cursor-shape raw_len`。
7. 对 `gpt-5.5-extra + xhigh + 大 body` 仍要警惕空流；usage chunk 只能帮助某些 UI 统计，不保证模型返回正文。

## 当前部署

VPS2：

```text
/root/subapi-cursor-compat/server.py
systemctl restart subapi-cursor-compat
systemctl is-active subapi-cursor-compat  # active
```

公网：

```text
https://subapi.aigcfast.com/cursor/v1
```

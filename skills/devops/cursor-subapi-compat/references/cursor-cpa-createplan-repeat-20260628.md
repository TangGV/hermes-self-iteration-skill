# api.aigcfast.com /cursor/v1 重复执行排障记录（2026-06-28）

## 背景

用户反馈 `https://api.aigcfast.com/cursor/v1` 在 Cursor Agent 中“不断重复执行 / 还没执行完又断 / 又触发”。现网链路：

```text
Cursor → https://api.aigcfast.com/cursor/v1
  → 1Panel OpenResty `/cursor/` location
  → 127.0.0.1:8326 cursor-cpa-compat
  → 127.0.0.1:8317 CLIProxyAPI/CPA
```

关键服务/文件：

```text
systemd: cursor-cpa-compat.service
code:    /root/cursor-cpa-compat/server.py
nginx:   /opt/1panel/www/sites/api.aigcfast.com/proxy/cursor-cpa-compat.conf
log:     journalctl -u cursor-cpa-compat
access:  /opt/1panel/www/sites/api.aigcfast.com/log/access.log
usage:   /root/cpa-usage-keeper/data/app.db usage_events
```

## 现象与证据

### 1. 最初的重复执行

OpenResty access log 显示 Cursor 云端 IP 连续请求：

```text
3.209.66.12 / 184.73.225.134 / 52.44.113.131
POST /cursor/v1/chat/completions HTTP/2.0
User-Agent: Cursor/1.0
```

8326 journal 初始审计可见：

```text
req-audit mode=chat-via-responses model=gpt-5.5 stream=True tools=17 tool_choice=None
resp-audit mode=chat-via-responses has_tool_calls=True bytes=262144
```

CPA 用量健康，无 5xx/429 主因：

```text
CPA /healthz 200
usage_events failed=0 为主
```

### 2. 第一层 bug：结束条件过粗

旧版桥接在 Responses SSE → ChatCompletions SSE 时使用：

```python
finish_reason = "tool_calls" if saw_tool else "stop"
```

问题：一轮中只要早先出现过 function_call，即使后面已经输出最终文本，最后也会返回 `finish_reason=tool_calls`，导致 Cursor 继续下一轮。

修复思路：维护 `last_output_kind`，最后一次 output 是工具才返回 `tool_calls`，最后一次 output 是文本则返回 `stop`。

```python
last_output_kind = "tool"  # response function_call
last_output_kind = "text"  # output_text / message
finish = "tool_calls" if last_output_kind == "tool" else "stop"
```

### 3. 第二层 bug：最终文本可能不是 output_text.delta

Responses API 不一定只用：

```text
response.output_text.delta
```

表示最终文本，也可能以 message output item 完成：

```text
response.output_item.added item.type=message
response.output_item.done  item.type=message
response.output_text.done
```

桥接需要把这些都视作 `last_output_kind="text"`，必要时从 message item 的 `content[].text` 提取最终文本。

### 4. 第三层 bug：function_call arguments 重复发送

Responses SSE 可能既流式发送：

```text
response.function_call_arguments.delta
```

又在：

```text
response.output_item.done item.type=function_call arguments=完整参数
```

再给完整 arguments。

ChatCompletions SSE 的 `delta.tool_calls[].function.arguments` 是增量拼接语义。如果已经发送过 delta，再把完整 arguments 发送一次，会造成 Cursor 端拼接出重复/损坏 JSON 参数，从而引起工具异常、重试或上下文异常膨胀。

修复：按 tool key 记录 `tool_arg_streamed[key]`，如果已经有 delta，`output_item.done` 上的完整 arguments 不再重复转发；仅在没有 delta 的情况下补发完整参数。

## 调试补丁：结构化摘要日志

为了避免盲猜，给 8326 添加了 outgoing SSE 摘要审计：

```text
resp-summary reason=... finish=... last=... events=... tools=... tail=...
resp-audit mode=... has_tool_calls=... finish_seen=... tool_names=... chunks=... bytes=...
```

示例：

```text
resp-summary reason=response.completed finish=tool_calls last=tool
 events={"response.created":1,"response.in_progress":1,
         "response.output_item.added":3,"response.output_item.done":3,
         "response.output_text.delta":45,"response.output_text.done":1,
         "response.function_call_arguments.delta":1395,
         "response.function_call_arguments.done":1,"response.completed":1}
 tools=CreatePlan
 tail=[..., {"type":"response.output_item.done","item_type":"function_call","name":"CreatePlan","args_len":3316}, {"type":"response.completed"}]
```

这条证明该轮最后确实是 `function_call CreatePlan`，不是 stop 漏识别。

## 关键结论：CreatePlan 重复是模型/Agent 行为，不是 stop 漏判

后续数据表明，修完协议翻译后，部分轮次仍返回：

```text
finish=tool_calls last=tool tools=CreatePlan
```

这表示上游模型在该轮最后明确要求调用 `CreatePlan`。按 OpenAI ChatCompletions 协议，桥接必须返回：

```json
"finish_reason": "tool_calls"
```

否则会吞掉有效工具调用。

同时 CPA usage_events 中出现大量：

```text
POST /v1/responses gpt-5.4 / gpt-5.4-mini
```

这些不像 8326 主桥接的 `gpt-5.5` 请求，更像 Cursor `CreatePlan` 工具内部又发起的模型调用。因此循环链路很可能是：

```text
Agent(gpt-5.5) → CreatePlan
Cursor 执行 CreatePlan → 内部多次 /v1/responses 生成计划
工具结果回到 Agent → Agent 再次 CreatePlan
```

## 不推荐的处理

不要用粗暴 loop guard 作为最终修复，例如：

```python
if tool_results >= 8:
    return finish_reason="stop"
```

这只能止血，会吞掉正常的长工具链，不能解决“应该在哪停”的协议问题。该方案曾短暂验证用，最终应移除或禁用。

## 推荐处理方案

### A. 必须保留的协议修复

1. `last_output_kind` 判定最后输出类型。
2. 识别 message item / output_text.done 作为文本结束。
3. 避免 function_call arguments delta + done 完整参数重复发送。
4. 保留 `resp-summary` 摘要日志，直到稳定验证完成。

### B. 针对 CreatePlan 重复的精准策略

如果后续仍出现 CreatePlan 循环，不要误判为 stop 漏识别；应做 CreatePlan 级别策略：

1. **优先方案**：请求转换时降低重复计划倾向。若输入历史里已有 CreatePlan 工具结果，不再注入“必须工具”的 nudge，也不要把工具选择强推到计划工具。
2. **精准拦截**：同一请求历史已有 CreatePlan tool result 后，如果本轮又只生成 CreatePlan，可返回文本总结/停止，或在 system nudge 中要求“已有计划则不要再次调用 CreatePlan，继续执行非计划工具或收尾”。
3. **观察 Cursor 内部工具**：CreatePlan 工具内部会触发额外 `/v1/responses`，需结合 usage_events 判断哪些是 8326 主链路，哪些是工具内部模型调用。

## 运维核查命令

```bash
# 入口请求
awk '/\/cursor\/v1\/chat\/completions/ {print}' \
  /opt/1panel/www/sites/api.aigcfast.com/log/access.log | tail -40

# 8326 审计
journalctl -u cursor-cpa-compat --since '30 min ago' --no-pager -o short-iso \
  | grep -E 'req-audit|resp-summary|resp-audit|error|Traceback'

# CPA usage_events 最近记录
python3 - <<'PY'
import sqlite3
con=sqlite3.connect('/root/cpa-usage-keeper/data/app.db')
for row in con.execute('''
  select id,timestamp,endpoint,model,failed,latency_ms,
         input_tokens,output_tokens,reasoning_tokens,total_tokens,request_id
  from usage_events order by id desc limit 60
'''):
    print(row)
PY
```

## 当前状态（本次记录）

- 8326 已部署协议修复：`last_output_kind`、message item 文本识别、arguments 去重。
- 8326 已部署结构化 `resp-summary` / `tool_names` 审计。
- 用户反馈“这次可以了”，后续继续调试时保留日志观察。
- 若再次重复，重点看 `resp-summary finish/last/tools/tail`，不要先重启 CPA/New API。

# Cursor 调 CPA `/cursor/v1` 问题解决总结

## 一句话结论

本次问题的根因不是 CPA 服务故障，而是 Cursor Agent 使用 ChatCompletions 工具调用语义，而 CPA/上游走 Responses SSE 事件语义；`cursor-cpa-compat` 在 `Responses SSE → ChatCompletions SSE` 桥接时，对 `finish_reason`、最终文本事件、function_call arguments 增量语义处理不完整，导致 Cursor 误以为工具调用还没结束或工具参数被拼坏，从而重复执行。

最终通过修复 8326 `cursor-cpa-compat` 的协议桥接逻辑解决：

1. 按**最后一个 assistant 输出类型**决定 `finish_reason`。
2. 识别 `message item` / `output_text.done` 作为最终文本。
3. 避免 `function_call_arguments.delta` 与 `output_item.done.arguments` 双发。
4. 增加结构化审计日志。
5. 验证公网 `/cursor/v1` 仍保持打字机流式输出。

## 当前目标链路

```text
Cursor
  → https://api.aigcfast.com/cursor/v1
  → OpenResty /cursor/
  → 127.0.0.1:8326 cursor-cpa-compat
  → 127.0.0.1:8317 CLIProxyAPI / CPA
  → Codex / 上游模型
```

## 遇到的问题

### 1. Cursor Agent 不断重复执行工具

表现：

```text
POST /cursor/v1/chat/completions HTTP/2.0 200
POST /cursor/v1/chat/completions HTTP/2.0 200
POST /cursor/v1/chat/completions HTTP/2.0 200
...
```

8326 日志：

```text
req-audit mode=chat-via-responses model=gpt-5.5 stream=True tools=17
resp-audit mode=chat-via-responses has_tool_calls=True
```

Cursor 云端 IP 常见为：

```text
3.209.66.12
184.73.225.134
52.44.113.131
```

### 2. `finish_reason` 判断错误

旧逻辑：

```python
finish_reason = "tool_calls" if saw_tool else "stop"
```

问题：同一轮里只要出现过工具调用，即便后面已经输出最终文本，也会返回 `tool_calls`，Cursor 因此继续下一轮。

正确逻辑：

```python
last_output_kind = "tool"  # 最新输出是 function_call
last_output_kind = "text"  # 最新输出是最终文本/message
finish = "tool_calls" if last_output_kind == "tool" else "stop"
```

### 3. Responses 的最终文本事件不止一种

不能只识别：

```text
response.output_text.delta
```

还要识别：

```text
response.output_text.done
response.output_item.added item.type=message
response.output_item.done  item.type=message
```

这些都应视为文本输出，让最终 `finish_reason=stop`。

### 4. function_call arguments 被重复发送

Responses SSE 可能同时发送：

```text
response.function_call_arguments.delta
response.output_item.done item.arguments=完整参数
```

ChatCompletions SSE 的 `delta.tool_calls[].function.arguments` 是增量拼接语义。若把 delta 和完整参数都发给 Cursor，Cursor 会拼出重复/损坏 JSON，导致工具异常、重试或循环。

正确处理：

```python
if delta:
    tool_arg_streamed[key] = True
    yield delta_arguments

if args and not tool_arg_streamed.get(key):
    yield full_arguments
```

### 5. CreatePlan 重复不是 stop 漏判

修复协议桥接后，有些轮次日志显示：

```text
resp-summary reason=response.completed finish=tool_calls last=tool tools=CreatePlan
```

这说明该轮最后确实是 `function_call: CreatePlan`，桥接必须返回 `tool_calls`，否则会吞掉有效工具调用。

同时 usage_events 出现大量：

```text
POST /v1/responses gpt-5.4 / gpt-5.4-mini
```

判断为 Cursor `CreatePlan` 工具内部又调用模型生成计划。这属于 Cursor Agent/模型行为，应与协议 bug 区分。

## 正确分析流程

1. **先确认入口**：access log 里是否是 `/cursor/v1/chat/completions`，不要把裸 `/v1` 流量当成 8326 问题。
2. **确认服务健康**：`cursor-cpa-compat active`、CPA health、usage_events failed/latency。
3. **看最终语义**：审计发给 Cursor 的 `finish_seen=stop|tool_calls|None`。
4. **看原始 Responses 事件**：`resp-summary events/tail/tools/last`。
5. **区分协议问题与真实工具调用**：最后是 message/text 才应 stop；最后是 function_call 就应 tool_calls。
6. **确认流式体验**：用真实 stream probe 检查本地 8326 与公网 `/cursor/v1` 是否逐 chunk 输出。

## 运维核查命令

```bash
# /cursor/v1 入口请求
awk '/\/cursor\/v1\/chat\/completions/ {print}' \
  /opt/1panel/www/sites/api.aigcfast.com/log/access.log | tail -40

# 8326 审计
journalctl -u cursor-cpa-compat --since '30 min ago' --no-pager -o short-iso \
  | grep -E 'req-audit|resp-summary|resp-audit|error|Traceback'

# 服务与连接
systemctl status cursor-cpa-compat --no-pager -l
ss -tnp | grep -E ':(8326|8317)\b' || true

# CPA usage_events
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

## 流式验证结果

测试公网 `/cursor/v1` 和 VPS 本地 8326：

| 路径 | TTFB | 总耗时 | chunk 数 | 平均间隔 | 结尾 |
|---|---:|---:|---:|---:|---|
| `127.0.0.1:8326` | 600ms | 2.8s | 45 | 64ms | `stop` |
| `https://api.aigcfast.com/cursor/v1` | 2.56s | 5.68s | 45 | 129ms | `stop` |

响应头：

```text
Content-Type: text/event-stream
X-Cursor-CPA-Compat: chat-via-responses
X-Accel-Buffering: no
```

结论：修复后仍为正常打字机效果，没有被 OpenResty 或 8326 整包缓冲。

## 最终落地文件

```text
/root/cursor-cpa-compat/server.py
/etc/systemd/system/cursor-cpa-compat.service
/opt/1panel/www/sites/api.aigcfast.com/proxy/cursor-cpa-compat.conf
```

仓库记录：

```text
skills/devops/cursor-subapi-compat/scripts/server.py
skills/devops/cursor-subapi-compat/scripts/cursor-cpa-compat.service
skills/devops/cursor-subapi-compat/scripts/cursor-cpa-compat-nginx.conf
skills/devops/cursor-subapi-compat/references/cursor-cpa-createplan-repeat-20260628.md
```

## 最终结果

修复后，Cursor 通过：

```text
https://api.aigcfast.com/cursor/v1
```

可以正常：

- 走 CPA key / CPA 上游；
- 保留 Cursor Agent 工具调用；
- 正确停止，不再错误重复执行；
- 保持 SSE 打字机输出；
- 通过结构化日志定位后续问题。

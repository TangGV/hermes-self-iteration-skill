# api.aigcfast.com /cursor/v1 重复执行排障与最终处理方案（2026-06-28）

## 背景

用户反馈 `https://api.aigcfast.com/cursor/v1` 在 Cursor Agent 中出现多轮异常行为：

- “不断重复执行”
- “还没执行完又断”
- “又触发”
- 怀疑“有结束条件过来了但兼容层没识别”

现网链路：

```text
Cursor
  → https://api.aigcfast.com/cursor/v1
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

## 正确分析方法

### 1. 先分清流量入口

不要把所有 CPA 用量都归因到 `/cursor/v1`。必须先用 access log 判定请求到底是不是走 8326：

```bash
awk '/\/cursor\/v1\/chat\/completions/ {print}' \
  /opt/1panel/www/sites/api.aigcfast.com/log/access.log | tail -40
```

判断标准：

| 现象 | 含义 |
|---|---|
| `POST /cursor/v1/chat/completions` | 走 8326 cursor-cpa-compat |
| `POST /v1/chat/completions` | 裸 CPA 8317，不经过 8326 |
| usage_events 中很多 `/v1/responses` | 可能是 Cursor 工具内部模型调用，不一定是 8326 主链路 |

Cursor 云端请求常见 IP：

```text
3.209.66.12
184.73.225.134
52.44.113.131
```

### 2. 再看 8326 对外发给 Cursor 的 finish_reason

仅看 `has_tool_calls=True` 不够。真正决定 Cursor 是否继续的是最后发给 Cursor 的：

```text
finish_reason=tool_calls | stop
```

因此需要 8326 记录：

```text
resp-audit mode=... has_tool_calls=... finish_seen=... tool_names=... chunks=... bytes=...
```

以及 Responses 原始事件摘要：

```text
resp-summary reason=... finish=... last=... events=... tools=... tail=...
```

### 3. 最后区分“协议翻译 bug”与“模型真实要求继续工具”

| 证据 | 判断 |
|---|---|
| 最后有最终文本 / message，但 `finish_seen=tool_calls` | 桥接结束条件 bug |
| 最后一项是 `function_call`，`finish=tool_calls` | 模型真实要求工具，不能强行吞掉 |
| `finish_seen=stop` 但 Cursor 仍继续 | Cursor 端消费/旧会话状态问题 |
| `resp-audit` 缺失 / 连接断开 | 上游/网络/CPA 连接问题 |

## 问题一：结束条件过粗

旧版桥接在 Responses SSE → ChatCompletions SSE 时使用：

```python
finish_reason = "tool_calls" if saw_tool else "stop"
```

问题：一轮里只要早先出现过 function_call，即使后面已经输出最终文本，最后也会返回 `finish_reason=tool_calls`，导致 Cursor 继续下一轮。

正确方案：维护最后一个 assistant 输出类型：

```python
last_output_kind = "tool"  # 最新输出是 function_call
last_output_kind = "text"  # 最新输出是最终文本/message
finish = "tool_calls" if last_output_kind == "tool" else "stop"
```

## 问题二：最终文本不一定是 output_text.delta

Responses API 不一定只用：

```text
response.output_text.delta
```

表示最终回答，也可能用：

```text
response.output_item.added item.type=message
response.output_item.done  item.type=message
response.output_text.done
```

正确方案：这些事件都必须把 `last_output_kind` 标成 `text`。如果没有收到 delta，则从 message item 中提取：

```python
def message_item_text(item) -> str:
    parts = []
    for part in item.get("content") or []:
        if part.get("text") is not None:
            parts.append(str(part.get("text")))
    return "".join(parts)
```

## 问题三：function_call arguments 被重复发送

Responses SSE 可能同时发送：

```text
response.function_call_arguments.delta
```

以及：

```text
response.output_item.done item.type=function_call arguments=完整参数
```

ChatCompletions SSE 的 `delta.tool_calls[].function.arguments` 是**增量拼接语义**。如果已经把 delta 发给 Cursor，再在 `output_item.done` 把完整 arguments 发一次，Cursor 会拼出重复/损坏 JSON 参数，进而导致工具异常、重试、上下文膨胀或循环。

正确方案：按 tool key 记录是否已经流式发送过参数：

```python
tool_arg_streamed = {}

# arguments.delta
if delta:
    tool_arg_streamed[key] = True
    yield delta_arguments

# output_item.done
if args and not tool_arg_streamed.get(key):
    yield full_arguments
```

即：**delta 和 done 完整参数只能二选一发给 Cursor。**

## 问题四：CreatePlan 重复不是 stop 漏判

修完协议翻译后，有些轮次仍然显示：

```text
resp-summary reason=response.completed finish=tool_calls last=tool
...
tools=CreatePlan
...
tail=[..., {"type":"response.output_item.done","item_type":"function_call","name":"CreatePlan","args_len":3316}, {"type":"response.completed"}]
```

这表示该轮最后确实是：

```text
function_call: CreatePlan
```

这种情况按协议必须返回：

```json
"finish_reason": "tool_calls"
```

否则会吞掉有效工具调用。也就是说，CreatePlan 重复是模型/Agent 行为，不是 stop 漏识别。

同时 usage_events 里出现大量：

```text
POST /v1/responses gpt-5.4 / gpt-5.4-mini
```

这些不像 8326 主桥接的 `gpt-5.5` 请求，更像 Cursor `CreatePlan` 工具内部又发起的模型调用。循环链路可能是：

```text
Agent(gpt-5.5) → CreatePlan
Cursor 执行 CreatePlan → 内部多次 /v1/responses 生成计划
工具结果回到 Agent → Agent 再次 CreatePlan
```

## 不推荐方案

不要把粗暴 loop guard 当最终修复：

```python
if tool_results >= 8:
    return finish_reason="stop"
```

这只能止血，会吞掉正常长工具链，掩盖协议层问题。可短期救火，但正式方案必须基于 Responses SSE 事件和最终输出类型判断。

## 最终正确处理方案

### 8326 Responses → ChatCompletions SSE 桥接必须具备

1. **按最后输出类型决定 finish_reason**
   - 最后是 function_call → `tool_calls`
   - 最后是文本/message → `stop`
2. **识别所有文本结束事件**
   - `response.output_text.delta`
   - `response.output_text.done`
   - `response.output_item.added item.type=message`
   - `response.output_item.done item.type=message`
3. **function_call arguments 去重**
   - 收到 `response.function_call_arguments.delta` 后，不再发送 `output_item.done.item.arguments` 的完整参数
   - 只有未收到 delta 时才用 done 的完整参数补发
4. **保留结构化审计**
   - `resp-summary`: 原始 Responses SSE 事件计数、最后 tail、工具名
   - `resp-audit`: 最终发给 Cursor 的 `finish_seen`、tool_names、chunk 数、bytes
5. **不要轻易重启 CPA/New API**
   - 先查 8326、access log、usage_events；CPA 健康且 failed=0 时，重启通常无意义

## 验证：打字机流式效果

最终验证 `/cursor/v1` 仍是流式，不是整包缓冲。

测试请求：

```text
model: gpt-5.5
stream: true
messages: 要求中文从一数到二十，每个数字换行
tools: Noop（但系统提示不要调用工具）
```

结果：

| 路径 | 结果 | TTFB | 总耗时 | chunk 数 | 平均间隔 | 结尾 |
|---|---:|---:|---:|---:|---:|---|
| VPS 本地 `127.0.0.1:8326` | 流式 | 600ms | 2.8s | 45 | 64ms | `stop` |
| 公网 `https://api.aigcfast.com/cursor/v1` | 流式 | 2.56s | 5.68s | 45 | 129ms | `stop` |

实际增量：

```text
一
\n
二
\n
三
\n
四
\n
五
\n
六
\n
```

响应头：

```text
Content-Type: text/event-stream
X-Cursor-CPA-Compat: chat-via-responses
X-Accel-Buffering: no
```

结论：OpenResty 与 8326 都没有整包缓冲，公网仍有正常打字机效果。

## 运维核查命令

```bash
# 入口请求：确认是否走 /cursor/v1
awk '/\/cursor\/v1\/chat\/completions/ {print}' \
  /opt/1panel/www/sites/api.aigcfast.com/log/access.log | tail -40

# 8326 审计：看 finish 和 Responses 原始事件摘要
journalctl -u cursor-cpa-compat --since '30 min ago' --no-pager -o short-iso \
  | grep -E 'req-audit|resp-summary|resp-audit|error|Traceback'

# 连接状态
ss -tnp | grep -E ':(8326|8317)\b' || true

# CPA usage_events：区分 8326 主链路与工具内部调用
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

## 复盘：本次有效的问题分析流程

1. **先确认请求入口**：`/cursor/v1` vs 裸 `/v1`，避免把 CPA 直连流量误归因到 8326。
2. **再确认服务健康**：8326 active、CPA health、usage_events failed/latency。
3. **审计发给 Cursor 的最终语义**：必须看 `finish_seen=stop|tool_calls|None`。
4. **回看 Responses 原始事件类型**：不要只看 `has_tool_calls=True`；要看最后一个 output item 是 message 还是 function_call。
5. **定位桥接协议语义**：ChatCompletions SSE arguments 是 delta 拼接，Responses done 可能携带完整 arguments，不能双发。
6. **区分协议 bug 与 Agent 行为**：CreatePlan 末尾 function_call 是真实工具调用，不是 stop 漏判。
7. **最后验证用户体验**：用真实 stream probe 检查公网和本地是否仍是打字机效果。

## 当前状态

- 8326 已部署协议修复：`last_output_kind`、message item 文本识别、arguments 去重。
- 8326 已部署结构化 `resp-summary` / `tool_names` 审计。
- `/cursor/v1` 已确认可正常 stop，用户反馈“这次全部解决了问题”。
- `/cursor/v1` 已确认公网仍为 `text/event-stream` 打字机效果。
- 后续如果复现，优先看 `resp-summary finish/last/tools/tail`，不要先重启 CPA/New API。

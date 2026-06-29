#!/usr/bin/env python3
"""Cursor -> OpenAI-compatible upstream compatibility bridge.

/cursor/v1 is a Cursor-specific production bridge for direct CPA keys.
For Cursor Agent, ChatCompletions tool forcing is not reliable on this CPA/Codex
path, so chat/completions requests with tools are routed through /v1/responses
and Responses SSE tool events are translated back into ChatCompletions SSE
`delta.tool_calls` for Cursor.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

UPSTREAM = "http://127.0.0.1:3000"
LISTEN = ("127.0.0.1", 8327)
DEBUG_SSE_SUMMARY = os.getenv("CURSOR_COMPAT_DEBUG_SSE", os.getenv("CURSOR_CPA_DEBUG_SSE", "")).lower() in {"1", "true", "yes", "on"}
CURSOR_FULL_CAPTURE = os.getenv("CURSOR_FULL_CAPTURE", "0").lower() in {"1", "true", "yes", "on"}
CURSOR_CAPTURE_DIR = Path(os.getenv("CURSOR_CAPTURE_DIR", "/var/log/cursor-full-capture"))
CURSOR_CAPTURE_MAX_BYTES = int(os.getenv("CURSOR_CAPTURE_MAX_BYTES", "2097152"))

HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-length",
    "host", "accept-encoding",
}

MODEL_ALIASES = {"gpt-5.5-extra": "gpt-5.5"}
MODEL_REASONING_ALIASES = {"gpt-5.5": "high", "gpt-5.5-extra": "xhigh"}
DROP_FOR_RESPONSES: set[str] = set()
DROP_FOR_CHAT = {"input", "instructions", "store", "previous_response_id", "truncation", "include", "prompt_cache_retention", "text", "reasoning_summary", "thinking", "thinking_budget"}

ACTIONABLE_TOOL_HINTS = (
    "write", "create", "edit", "modify", "update", "fix", "implement",
    "run", "execute", "apply", "save", "commit", "generate", "continue",
    "写", "创建", "新建", "修改", "改", "修", "执行", "运行", "保存",
    "落地", "实现", "继续", "生成", "提交", "文档", "文件",
)
SUMMARY_ONLY_HINTS = (
    "summarize", "summary", "explain", "analyze", "review only",
    "总结", "解释", "分析", "只分析", "不要修改", "别修改", "无需修改",
)


def normalize_call_id(call_id, fallback_seed=""):
    s = str(call_id or "").strip()
    if not s:
        s = "call_" + hashlib.sha256(str(fallback_seed).encode()).hexdigest()[:32]
    if len(s) <= 64:
        return s
    return "call_" + hashlib.sha256(s.encode()).hexdigest()[:58]


def _content_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                for key in ("text", "content", "input"):
                    if isinstance(item.get(key), str):
                        parts.append(item[key])
        return "\n".join(parts)
    return str(value)


def should_force_tool_choice(messages) -> bool:
    if not isinstance(messages, list):
        return False
    user_texts = []
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") in ("user", "developer"):
            text = _content_text(msg.get("content"))
            if text:
                user_texts.append(text)
    if not user_texts:
        return False
    hay = "\n".join(user_texts[-4:]).lower()
    if any(h.lower() in hay for h in SUMMARY_ONLY_HINTS):
        return False
    return any(h.lower() in hay for h in ACTIONABLE_TOOL_HINTS)


def normalize_reasoning(obj: dict) -> bool:
    # Preserve Cursor/New API reasoning difficulty exactly. In particular, do not
    # upgrade high -> xhigh; the user expects high to remain high end-to-end.
    return False


def normalize_ids_in_chat(obj: dict) -> bool:
    changed = False
    messages = obj.get("messages")
    if not isinstance(messages, list):
        return False
    out = []
    for m in messages:
        if not isinstance(m, dict):
            out.append(m); continue
        m = dict(m)
        if m.get("tool_call_id") and len(str(m["tool_call_id"])) > 64:
            m["tool_call_id"] = normalize_call_id(m["tool_call_id"], str(m.get("content"))[:80])
            changed = True
        if isinstance(m.get("tool_calls"), list):
            tcs = []
            for tc in m["tool_calls"]:
                if not isinstance(tc, dict):
                    tcs.append(tc); continue
                tc = dict(tc)
                if tc.get("id") and len(str(tc["id"])) > 64:
                    tc["id"] = normalize_call_id(tc["id"], str(tc.get("function"))[:80])
                    changed = True
                tcs.append(tc)
            m["tool_calls"] = tcs
        out.append(m)
    if changed:
        obj["messages"] = out
    return changed


def chat_content_to_responses(content, role="user"):
    if content is None:
        return ""
    text_type = "output_text" if role == "assistant" else "input_text"
    if isinstance(content, str):
        # Responses accepts plain strings for simple text; this avoids sending
        # assistant content parts typed as input_text, which Codex rejects.
        return content
    if isinstance(content, list):
        out = []
        for item in content:
            if isinstance(item, str):
                out.append({"type": text_type, "text": item})
            elif isinstance(item, dict):
                typ = item.get("type")
                if typ in ("text", "input_text", "output_text"):
                    out.append({"type": text_type, "text": item.get("text", "")})
                elif typ == "image_url" and role != "assistant":
                    img = item.get("image_url")
                    url = img.get("url") if isinstance(img, dict) else img
                    if url:
                        out.append({"type": "input_image", "image_url": url})
                else:
                    txt = item.get("text") or item.get("content")
                    if isinstance(txt, str):
                        out.append({"type": text_type, "text": txt})
        return out or ""
    return str(content)


def chat_messages_to_responses_input(messages):
    out = []
    if not isinstance(messages, list):
        return out
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role") or "user"
        if role == "developer":
            role = "system"
        if role == "tool":
            call_id = normalize_call_id(msg.get("tool_call_id"), str(msg.get("content"))[:80])
            out.append({"type": "function_call_output", "call_id": call_id, "output": _content_text(msg.get("content"))})
            continue
        if role == "assistant" and isinstance(msg.get("tool_calls"), list):
            content = msg.get("content")
            if content:
                out.append({"role": "assistant", "content": chat_content_to_responses(content, "assistant")})
            for tc in msg.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") or {}
                call_id = normalize_call_id(tc.get("id") or tc.get("call_id"), str(fn)[:80])
                args = fn.get("arguments") or "{}"
                if not isinstance(args, str):
                    args = json.dumps(args, ensure_ascii=False, separators=(",", ":"))
                out.append({"type": "function_call", "call_id": call_id, "name": fn.get("name") or "tool", "arguments": args})
            continue
        if role not in ("system", "user", "assistant"):
            role = "user"
        out.append({"role": role, "content": chat_content_to_responses(msg.get("content"), role)})
    return out


def chat_tools_to_responses_tools(tools):
    if not isinstance(tools, list):
        return None
    out = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        if t.get("type") == "function" and isinstance(t.get("function"), dict):
            fn = t["function"]
            x = {"type": "function", "name": fn.get("name") or "tool"}
            if fn.get("description") is not None:
                x["description"] = fn.get("description")
            if fn.get("parameters") is not None:
                x["parameters"] = fn.get("parameters")
            out.append(x)
        elif t.get("type") == "function" and t.get("name"):
            out.append(t)
    return out or None


def make_actionable_nudge():
    return {
        "role": "system",
        "content": "Cursor Agent compatibility instruction: the user is asking for an actionable coding/file/command task. Do not finish with prose only. Use the available tools to perform the requested action. Only provide a final text answer after the necessary tool calls have completed.",
    }


def chat_to_responses_payload(obj: dict) -> tuple[dict, bool]:
    out = dict(obj)
    changed = False
    original_model = out.get("model") if isinstance(out.get("model"), str) else None
    if original_model in MODEL_REASONING_ALIASES:
        effort = MODEL_REASONING_ALIASES[original_model]
        if not out.get("reasoning") and not out.get("reasoning_effort"):
            out["reasoning"] = {"effort": effort}
            changed = True
    if original_model in MODEL_ALIASES:
        out["model"] = MODEL_ALIASES[original_model]
        changed = True
    changed = normalize_reasoning(out) or changed
    normalize_ids_in_chat(out)
    messages = out.get("messages")
    actionable = should_force_tool_choice(messages)
    has_tool_result = False
    if isinstance(messages, list):
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            if msg.get("role") == "tool" or msg.get("tool_call_id"):
                has_tool_result = True
                break
    force_initial_tool = actionable and not has_tool_result
    if force_initial_tool and isinstance(messages, list):
        already = any(isinstance(m, dict) and isinstance(m.get("content"), str) and "Cursor Agent compatibility instruction" in m.get("content", "") for m in messages)
        if not already:
            messages = [make_actionable_nudge()] + messages
            changed = True
    resp = {}
    for k in ("model", "stream", "temperature", "top_p", "reasoning", "reasoning_effort", "service_tier", "user"):
        if k in out:
            resp[k] = out[k]
    if "max_output_tokens" in out:
        resp["max_output_tokens"] = out["max_output_tokens"]
    elif "max_tokens" in out:
        resp["max_output_tokens"] = out["max_tokens"]
    if messages is not None:
        resp["input"] = chat_messages_to_responses_input(messages)
    tools = chat_tools_to_responses_tools(out.get("tools"))
    if tools:
        resp["tools"] = tools
        if force_initial_tool:
            resp["tool_choice"] = "required"
        elif out.get("tool_choice") not in (None, {}, "none"):
            # After Cursor has returned any tool result, do not keep forcing required.
            # Let the model either call another tool or finish; otherwise failed Read
            # attempts can loop forever.
            resp["tool_choice"] = "auto" if out.get("tool_choice") == "required" else out.get("tool_choice")
    for k in DROP_FOR_RESPONSES:
        resp.pop(k, None)
    return resp, True


def normalize_chat_body(raw: bytes) -> tuple[bytes, bool]:
    if not raw:
        return raw, False
    try:
        obj = json.loads(raw.decode("utf-8"))
    except Exception:
        return raw, False
    if not isinstance(obj, dict):
        return raw, False
    changed = False
    original_model = obj.get("model") if isinstance(obj.get("model"), str) else None
    if original_model in MODEL_REASONING_ALIASES:
        effort = MODEL_REASONING_ALIASES[original_model]
        if not obj.get("reasoning") and not obj.get("reasoning_effort"):
            obj["reasoning"] = {"effort": effort}
            changed = True
    if original_model in MODEL_ALIASES:
        obj["model"] = MODEL_ALIASES[original_model]
        changed = True
    changed = normalize_reasoning(obj) or changed
    changed = normalize_ids_in_chat(obj) or changed
    for key in DROP_FOR_CHAT:
        if key in obj:
            obj.pop(key, None); changed = True
    if not changed:
        return raw, False
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), True


def build_response_request_from_chat(raw: bytes) -> tuple[bytes, bool, dict]:
    obj = json.loads(raw.decode("utf-8"))
    resp, changed = chat_to_responses_payload(obj)
    return json.dumps(resp, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), changed, resp


def sse_event(event, data):
    if event:
        return f"event: {event}\n".encode() + f"data: {data}\n\n".encode()
    return f"data: {data}\n\n".encode()


def normalize_usage(usage):
    """Map Responses token usage to ChatCompletions usage shape for Cursor statistics."""
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
    completion = usage.get("completion_tokens", usage.get("output_tokens"))
    total = usage.get("total_tokens")
    if total is None and isinstance(prompt, int) and isinstance(completion, int):
        total = prompt + completion
    out = dict(usage)
    if prompt is not None:
        out["prompt_tokens"] = prompt
    if completion is not None:
        out["completion_tokens"] = completion
    if total is not None:
        out["total_tokens"] = total
    return out if any(k in out for k in ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens")) else None


def chat_chunk(resp_id, model, delta=None, finish=None, usage=None):
    chunk = {
        "id": resp_id or "chatcmpl-cursor-compat",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}],
    }
    normalized_usage = normalize_usage(usage)
    if normalized_usage is not None:
        chunk["usage"] = normalized_usage
    return json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))


def message_item_text(item) -> str:
    if not isinstance(item, dict):
        return ""
    parts = []
    for part in item.get("content") or []:
        if not isinstance(part, dict):
            continue
        if part.get("text") is not None:
            parts.append(str(part.get("text")))
        elif part.get("type") in ("output_text", "text") and part.get("content") is not None:
            parts.append(str(part.get("content")))
    if item.get("text") is not None:
        parts.append(str(item.get("text")))
    return "".join(parts)


def responses_sse_to_chat(resp):
    resp_id = "chatcmpl-cursor-compat"
    model = None
    event = ""
    sent_role = False
    saw_tool = False
    last_output_kind = None  # "tool" if the latest assistant output is a function_call; "text" for final prose.
    tool_indices = {}
    tool_arg_streamed = {}
    next_tool_index = 0
    completed = False
    text_buf = []
    event_counts = {}
    tool_names_seen = []
    tail_events = []
    usage_seen = None

    def note_event(typ, obj):
        event_counts[typ] = event_counts.get(typ, 0) + 1
        item = obj.get("item") if isinstance(obj, dict) else None
        rec = {"type": typ}
        if isinstance(item, dict):
            rec["item_type"] = item.get("type")
            if item.get("type") == "function_call":
                rec["name"] = item.get("name")
                if item.get("name") and item.get("name") not in tool_names_seen and len(tool_names_seen) < 20:
                    tool_names_seen.append(item.get("name"))
                args = item.get("arguments")
                if isinstance(args, str):
                    rec["args_len"] = len(args)
            elif item.get("type") == "message":
                txt = message_item_text(item)
                rec["message_text_len"] = len(txt)
                rec["status"] = item.get("status")
        delta = obj.get("delta") if isinstance(obj, dict) else None
        if isinstance(delta, str):
            rec["delta_len"] = len(delta)
        tail_events.append(rec)
        if len(tail_events) > 24:
            del tail_events[0]

    def log_summary(reason, finish):
        if not DEBUG_SSE_SUMMARY:
            return
        try:
            sys.stderr.write("%s resp-summary reason=%s finish=%s last=%s events=%s tools=%s tail=%s\n" % (
                time.strftime("%Y-%m-%dT%H:%M:%S%z"), reason, finish, last_output_kind,
                json.dumps(event_counts, ensure_ascii=False, separators=(",", ":")),
                ",".join(tool_names_seen),
                json.dumps(tail_events, ensure_ascii=False, separators=(",", ":"))[:2000],
            ))
            sys.stderr.flush()
        except Exception:
            pass

    while True:
        raw = resp.readline()
        if not raw:
            break
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            continue
        if line.startswith("event:"):
            event = line[6:].strip()
            continue
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            continue
        try:
            obj = json.loads(data)
        except Exception:
            continue
        if obj.get("id"):
            resp_id = obj.get("id")
        if obj.get("model"):
            model = obj.get("model")
        typ = obj.get("type") or event
        if isinstance(obj.get("usage"), dict):
            usage_seen = obj.get("usage")
        if isinstance(obj.get("response"), dict) and isinstance(obj["response"].get("usage"), dict):
            usage_seen = obj["response"].get("usage")
        note_event(typ, obj)
        if not sent_role:
            yield sse_event(None, chat_chunk(resp_id, model, {"role": "assistant"}))
            sent_role = True
        if typ in ("response.output_text.delta", "response.refusal.delta"):
            delta = obj.get("delta") or obj.get("text") or ""
            if delta:
                last_output_kind = "text"
                text_buf.append(str(delta))
                yield sse_event(None, chat_chunk(resp_id, model, {"content": str(delta)}))
        elif typ == "response.output_text.done":
            last_output_kind = "text"
            txt = obj.get("text") or obj.get("delta") or ""
            if txt and not text_buf:
                text_buf.append(str(txt))
                yield sse_event(None, chat_chunk(resp_id, model, {"content": str(txt)}))
        elif typ == "response.output_item.added":
            item = obj.get("item") or {}
            if isinstance(item, dict) and item.get("type") == "message":
                last_output_kind = "text"
            if isinstance(item, dict) and item.get("type") == "function_call":
                saw_tool = True
                last_output_kind = "tool"
                call_id = normalize_call_id(item.get("call_id") or item.get("id"), str(item.get("name")) + str(obj.get("output_index")))
                key = str(obj.get("output_index", call_id))
                idx = tool_indices.setdefault(key, next_tool_index)
                if idx == next_tool_index:
                    next_tool_index += 1
                tool_arg_streamed.setdefault(key, False)
                yield sse_event(None, chat_chunk(resp_id, model, {"tool_calls": [{"index": idx, "id": call_id, "type": "function", "function": {"name": item.get("name") or "tool", "arguments": ""}}]}))
        elif typ == "response.function_call_arguments.delta":
            saw_tool = True
            last_output_kind = "tool"
            key = str(obj.get("output_index", obj.get("item_id", "0")))
            idx = tool_indices.setdefault(key, next_tool_index)
            if idx == next_tool_index:
                next_tool_index += 1
            delta = obj.get("delta") or ""
            if delta:
                tool_arg_streamed[key] = True
            yield sse_event(None, chat_chunk(resp_id, model, {"tool_calls": [{"index": idx, "function": {"arguments": str(delta)}}]}))
        elif typ == "response.output_item.done":
            item = obj.get("item") or {}
            if isinstance(item, dict) and item.get("type") == "message":
                last_output_kind = "text"
                txt = message_item_text(item)
                if txt and not text_buf:
                    text_buf.append(txt)
                    yield sse_event(None, chat_chunk(resp_id, model, {"content": txt}))
            if isinstance(item, dict) and item.get("type") == "function_call":
                saw_tool = True
                last_output_kind = "tool"
                key = str(obj.get("output_index", item.get("call_id", "0")))
                idx = tool_indices.setdefault(key, next_tool_index)
                if idx == next_tool_index:
                    next_tool_index += 1
                args = item.get("arguments")
                # Responses often sends arguments both as deltas and again on item.done.
                # ChatCompletions SSE expects argument deltas only once; duplicating corrupts JSON args.
                if isinstance(args, str) and args and not tool_arg_streamed.get(key):
                    yield sse_event(None, chat_chunk(resp_id, model, {"tool_calls": [{"index": idx, "function": {"arguments": args}}]}))
        elif typ == "response.completed":
            completed = True
            finish = "tool_calls" if last_output_kind == "tool" else "stop"
            log_summary("response.completed", finish)
            yield sse_event(None, chat_chunk(resp_id, model, {}, finish, usage_seen))
            yield sse_event(None, "[DONE]")
            break
    if not completed:
        finish = "tool_calls" if last_output_kind == "tool" else "stop"
        log_summary("stream_ended_without_response.completed", finish)
        yield sse_event(None, chat_chunk(resp_id, model, {}, finish, usage_seen))
        yield sse_event(None, "[DONE]")


def response_text(obj):
    texts = []
    for item in obj.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for p in item.get("content") or []:
                if isinstance(p, dict) and p.get("type") in ("output_text", "text") and p.get("text") is not None:
                    texts.append(str(p.get("text")))
        elif item.get("type") == "output_text" and item.get("text") is not None:
            texts.append(str(item.get("text")))
    if not texts and obj.get("output_text") is not None:
        texts.append(str(obj.get("output_text")))
    return "".join(texts)


def responses_json_to_chat(payload):
    try:
        obj = json.loads(payload.decode("utf-8", "replace"))
    except Exception:
        return payload
    if not isinstance(obj, dict):
        return payload
    tool_calls = []
    for item in obj.get("output") or []:
        if isinstance(item, dict) and item.get("type") == "function_call":
            tool_calls.append({"id": normalize_call_id(item.get("call_id") or item.get("id"), str(item.get("name"))), "type": "function", "function": {"name": item.get("name") or "tool", "arguments": item.get("arguments") or "{}"}})
    msg = {"role": "assistant", "content": response_text(obj)}
    finish = "stop"
    if tool_calls:
        msg["tool_calls"] = tool_calls
        finish = "tool_calls"
    chat = {
        "id": obj.get("id", "chatcmpl-cursor-compat"), "object": "chat.completion",
        "created": int(obj.get("created_at") or time.time()), "model": obj.get("model"),
        "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
    }
    usage = normalize_usage(obj.get("usage"))
    if usage is not None:
        chat["usage"] = usage
    return json.dumps(chat, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def audit_request(obj: dict, mode: str) -> str:
    tools = obj.get("tools")
    n_tools = len(tools) if isinstance(tools, list) else 0
    reasoning = obj.get("reasoning")
    if isinstance(reasoning, dict):
        reasoning = reasoning.get("effort") or reasoning.get("level") or reasoning
    reasoning = reasoning or obj.get("reasoning_effort")
    return f"mode={mode} model={obj.get('model') or '?'} stream={bool(obj.get('stream'))} tools={n_tools} tool_choice={obj.get('tool_choice')!r} reasoning={reasoning!r}"


def _shape_value(v, depth=0):
    """Safe structural summary: no message text, no credentials."""
    if depth >= 2:
        if isinstance(v, dict):
            return {"type": "dict", "keys": sorted(map(str, v.keys()))[:40]}
        if isinstance(v, list):
            return {"type": "list", "len": len(v)}
        return type(v).__name__
    if isinstance(v, dict):
        return {str(k): _shape_value(val, depth + 1) for k, val in list(v.items())[:40] if str(k).lower() not in {"authorization", "api_key", "key", "token"}}
    if isinstance(v, list):
        return {"type": "list", "len": len(v), "first": _shape_value(v[0], depth + 1) if v else None}
    if isinstance(v, str):
        x = v.strip()
        if len(x) > 80:
            x = x[:80] + "…"
        return {"type": "str", "len": len(v), "sample": x if depth == 0 else ""}
    return v


def find_reasoning_like(obj):
    hits = []
    needles = ("reason", "effort", "think", "budget", "verbosity", "intelligence", "mode")
    def walk(v, path="", depth=0):
        if depth > 4:
            return
        if isinstance(v, dict):
            for k, val in v.items():
                ks = str(k)
                p = f"{path}.{ks}" if path else ks
                if any(n in ks.lower() for n in needles):
                    hits.append((p, _shape_value(val)))
                if ks in ("messages", "input"):
                    # Avoid logging content; only inspect per-item keys/roles.
                    if isinstance(val, list):
                        roles = []
                        keysets = []
                        for item in val[:6]:
                            if isinstance(item, dict):
                                roles.append(item.get("role") or item.get("type"))
                                keysets.append(sorted(map(str, item.keys())))
                        hits.append((p + "._summary", {"len": len(val), "roles": roles, "keysets": keysets}))
                    continue
                if ks.lower() in {"content", "text", "arguments", "output"}:
                    continue
                walk(val, p, depth + 1)
        elif isinstance(v, list):
            for i, item in enumerate(v[:6]):
                walk(item, f"{path}[{i}]", depth + 1)
    walk(obj)
    return hits[:80]


def audit_cursor_shape(obj: dict, raw_len: int, path: str) -> str:
    if not isinstance(obj, dict):
        return "non_dict"
    top_keys = sorted(str(k) for k in obj.keys())
    meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else None
    extra = obj.get("extra_body") if isinstance(obj.get("extra_body"), dict) else None
    payload = {
        "path": path,
        "raw_len": raw_len,
        "top_keys": top_keys,
        "metadata_keys": sorted(map(str, meta.keys())) if meta else [],
        "extra_body_keys": sorted(map(str, extra.keys())) if extra else [],
        "reasoning_like": find_reasoning_like(obj),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))[:4000]


def capture_cursor_body(obj: dict, raw: bytes, path: str):
    """Temporary full request-body capture for user-authorized debugging.
    Body only; no HTTP Authorization header. Stores locally on VPS.
    """
    if not CURSOR_FULL_CAPTURE or not isinstance(obj, dict):
        return
    try:
        CURSOR_CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        rec = {
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "path": path,
            "raw_len": len(raw),
            "truncated": len(raw) > CURSOR_CAPTURE_MAX_BYTES,
            "body": obj,
        }
        data = json.dumps(rec, ensure_ascii=False, indent=2)
        if len(data.encode("utf-8")) > CURSOR_CAPTURE_MAX_BYTES:
            # Preserve structure enough for analysis but prevent unbounded logs.
            rec["body"] = obj.copy()
            if isinstance(rec["body"].get("messages"), list):
                rec["body"]["messages"] = rec["body"]["messages"][-20:]
                rec["messages_truncated_to_last"] = 20
            data = json.dumps(rec, ensure_ascii=False, indent=2)
        latest = CURSOR_CAPTURE_DIR / "subapi-latest.json"
        latest.write_text(data, encoding="utf-8")
        (CURSOR_CAPTURE_DIR / f"subapi-{ts}.json").write_text(data, encoding="utf-8")
    except Exception as e:
        try:
            sys.stderr.write("%s capture-cursor-body failed: %r\n" % (time.strftime("%Y-%m-%dT%H:%M:%S%z"), e))
            sys.stderr.flush()
        except Exception:
            pass


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S%z"), fmt % args))
        sys.stderr.flush()

    def upstream_path(self) -> str:
        path = self.path
        if path == "/cursor/v1":
            return "/v1"
        if path.startswith("/cursor/v1/"):
            return "/v1/" + path[len("/cursor/v1/"):]
        if path.startswith("/v1"):
            return path
        return "/v1" + (path if path.startswith("/") else "/" + path)

    def make_headers(self, content_length=None):
        headers = {}
        for k, v in self.headers.items():
            if k.lower() not in HOP:
                headers[k] = v
        if content_length is not None:
            headers["Content-Length"] = str(content_length)
        return headers

    def add_bridge_headers(self, changed: bool, mode="direct-subapi"):
        self.send_header("X-Cursor-Compat", mode)
        self.send_header("X-SubAPI-Cursor-Compat", mode)
        if changed:
            self.send_header("X-Cursor-Transform", "chat-via-responses-or-field-filter")
            self.send_header("X-SubAPI-Cursor-Transform", "chat-via-responses-or-field-filter")
        self.send_header("X-Cursor-Response-Filter", "none")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")

    def proxy(self, method: str):
        upath = self.upstream_path()
        body = None
        changed = False
        mode = "direct-subapi"
        response_mode = "passthrough"
        if method in {"POST", "PUT", "PATCH"}:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            body = raw
            if raw and upath.endswith("/chat/completions"):
                try:
                    obj = json.loads(raw.decode("utf-8"))
                    if isinstance(obj, dict):
                        self.log_message("cursor-shape %s", audit_cursor_shape(obj, len(raw), upath))
                        capture_cursor_body(obj, raw, upath)
                    if isinstance(obj, dict) and isinstance(obj.get("tools"), list) and obj.get("tools"):
                        body, changed, robj = build_response_request_from_chat(raw)
                        upath = upath.rsplit("/chat/completions", 1)[0] + "/responses"
                        mode = "chat-via-responses"
                        response_mode = "responses-to-chat"
                        self.log_message("req-audit %s", audit_request(robj, mode))
                    else:
                        body, changed = normalize_chat_body(raw)
                        obj2 = json.loads((body or raw).decode("utf-8"))
                        if isinstance(obj2, dict):
                            self.log_message("req-audit %s", audit_request(obj2, "chat-native"))
                except Exception as e:
                    self.log_message("transform failed: %r", e)
                    body, changed = normalize_chat_body(raw)
        req = Request(UPSTREAM + upath, data=body, headers=self.make_headers(len(body) if body is not None else None), method=method)
        try:
            with urlopen(req, timeout=3600) as resp:
                if response_mode == "responses-to-chat" and (body and b'"stream":true' in body.lower()):
                    self.send_response(resp.status)
                    self.send_header("Content-Type", "text/event-stream")
                    self.add_bridge_headers(changed, mode)
                    self.end_headers()
                    buf = bytearray(); cap = 256 * 1024
                    saw_tool = False
                    finish_seen = None
                    tool_names = []
                    chunk_count = 0
                    for c in responses_sse_to_chat(resp):
                        chunk_count += 1
                        if len(buf) < cap:
                            buf.extend(c[: cap - len(buf)])
                        if b"tool_calls" in c:
                            saw_tool = True
                        # Parse our outgoing ChatCompletions SSE chunks enough to know why Cursor continues.
                        try:
                            for part in c.split(b"data: ")[1:]:
                                line = part.split(b"\n", 1)[0].strip()
                                if not line or line == b"[DONE]" or not line.startswith(b"{"):
                                    continue
                                o = json.loads(line.decode("utf-8", "replace"))
                                choice = (o.get("choices") or [{}])[0]
                                fr = choice.get("finish_reason")
                                if fr:
                                    finish_seen = fr
                                delta = choice.get("delta") or {}
                                for tc in delta.get("tool_calls") or []:
                                    fn = (tc.get("function") or {}).get("name")
                                    if fn and fn not in tool_names and len(tool_names) < 12:
                                        tool_names.append(fn)
                        except Exception:
                            pass
                        try:
                            self.wfile.write(c); self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            break
                    self.log_message("resp-audit mode=%s has_tool_calls=%s finish_seen=%s tool_names=%s chunks=%s bytes=%s usage_seen=%s", mode, saw_tool, finish_seen, ",".join(tool_names), chunk_count, len(buf), b'"usage"' in buf)
                else:
                    payload = resp.read()
                    if response_mode == "responses-to-chat":
                        payload = responses_json_to_chat(payload)
                    self.send_response(resp.status)
                    for k, v in resp.headers.items():
                        if k.lower() not in HOP:
                            self.send_header(k, v)
                    self.add_bridge_headers(changed, mode)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
        except HTTPError as e:
            payload = e.read()
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() not in HOP:
                    self.send_header(k, v)
            self.add_bridge_headers(changed, mode)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:
            payload = json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.add_bridge_headers(changed, mode)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    def do_GET(self): self.proxy("GET")
    def do_POST(self): self.proxy("POST")
    def do_PUT(self): self.proxy("PUT")
    def do_PATCH(self): self.proxy("PATCH")
    def do_DELETE(self): self.proxy("DELETE")


if __name__ == "__main__":
    httpd = ThreadingHTTPServer(LISTEN, Handler)
    print(f"cursor-compat listening on {LISTEN[0]}:{LISTEN[1]} -> {UPSTREAM}", flush=True)
    httpd.serve_forever()

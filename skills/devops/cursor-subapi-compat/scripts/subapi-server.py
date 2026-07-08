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
import itertools
import json
import os
import re
import socket
import sys
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

UPSTREAM = "http://127.0.0.1:3000"
LISTEN = ("127.0.0.1", 8327)
REQ_COUNTER = itertools.count(1)
DEBUG_SSE_SUMMARY = os.getenv("CURSOR_COMPAT_DEBUG_SSE", os.getenv("CURSOR_CPA_DEBUG_SSE", "")).lower() in {"1", "true", "yes", "on"}
# Off by default: OpenAI final usage chunks make Cursor usage increment, but can
# also overwrite Cursor's internal Context Usage panel. Enable only for tests.
CURSOR_EMIT_USAGE_CHUNK = os.getenv("CURSOR_EMIT_USAGE_CHUNK", "0").lower() in {"1", "true", "yes", "on"}
# Experimental: emit one estimated usage chunk before the model stream starts so
# Cursor can show context during generation. Keep off unless explicitly testing.
CURSOR_EMIT_USAGE_PREROLL = os.getenv("CURSOR_EMIT_USAGE_PREROLL", "0").lower() in {"1", "true", "yes", "on"}
CURSOR_FULL_CAPTURE = os.getenv("CURSOR_FULL_CAPTURE", "0").lower() in {"1", "true", "yes", "on"}
CURSOR_CAPTURE_DIR = Path(os.getenv("CURSOR_CAPTURE_DIR", "/var/log/cursor-full-capture"))
CURSOR_CAPTURE_MAX_BYTES = int(os.getenv("CURSOR_CAPTURE_MAX_BYTES", "2097152"))
CURSOR_SLOW_AUDIT_MS = int(os.getenv("CURSOR_SLOW_AUDIT_MS", "15000"))

HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-length",
    "host", "accept-encoding",
}

MODEL_ALIASES = {
    "gpt-5.5-extra": "gpt-5.5",
    "gpt-5.4": "grok-composer-2.5-fast",
}
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


def _safe_json_obj(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            obj = json.loads(value)
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None


def _message_text_for_plan_hint(msg) -> str:
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
        return "\n".join(x for x in parts if x)
    return ""


def _is_plan_function_name(name: str) -> bool:
    n = (name or "").lower().replace("_", "").replace("-", "")
    return n in {"createplan", "updateplan"} or ("plan" in n and "create" in n)


# Cursor built-in tool names that must never be treated as CreatePlan args.name.
_CURSOR_BUILTIN_TOOL_NAMES = {
    "shell", "read", "write", "grep", "glob", "list", "delete", "search",
    "websearch", "browser", "provider-switcher", "channel-switcher", "updateplan",
}


def _looks_like_plan_display_name(name: str) -> bool:
    n = (name or "").strip()
    if not n or len(n) < 3:
        return False
    low = n.lower().replace("_", "").replace("-", "")
    if low in _CURSOR_BUILTIN_TOOL_NAMES:
        return False
    if n.lower().startswith("workspace-tidy"):
        return True
    # Real plan names are usually titles/sentences, not single PascalCase tool ids.
    if n in {"Shell", "Read", "Write", "Grep", "Glob", "Delete"}:
        return False
    if " " in n or "：" in n or ":" in n or len(n) >= 12:
        return True
    return low not in _CURSOR_BUILTIN_TOOL_NAMES


def _failed_createplan_tool_call_ids(messages) -> set:
    """CreatePlan tool results Cursor marks as interrupted/error must not anchor plan_lock."""
    failed: set = set()
    if not isinstance(messages, list):
        return failed
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "tool":
            continue
        if not _is_plan_function_name(str(msg.get("name") or "")):
            continue
        txt = _message_text_for_plan_hint(msg).lower()
        if "interrupted" in txt or "error" in txt:
            tid = msg.get("tool_call_id")
            if isinstance(tid, str) and tid:
                failed.add(tid)
    return failed


def _extract_plan_names_from_messages(messages) -> list[str]:
    names = []
    if not isinstance(messages, list):
        return names
    failed_cp = _failed_createplan_tool_call_ids(messages)
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        for tc in msg.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            if tc.get("id") in failed_cp:
                continue
            fn = tc.get("function") or {}
            if not _is_plan_function_name(str(fn.get("name") or "")):
                continue
            args = _safe_json_obj(fn.get("arguments")) or {}
            name = args.get("name")
            if isinstance(name, str) and _looks_like_plan_display_name(name):
                names.append(name.strip())
        if msg.get("role") == "tool":
            # msg["name"] is the tool id (Shell/Read/...), NOT CreatePlan args.name.
            if not _is_plan_function_name(str(msg.get("name") or "")):
                continue
            args = _safe_json_obj(msg.get("content"))
            if isinstance(args, dict):
                name = args.get("name") or args.get("planName")
                if isinstance(name, str) and _looks_like_plan_display_name(name):
                    names.append(name.strip())
        txt = _message_text_for_plan_hint(msg)
        if "createPlanToolCall" in txt or '"createPlanToolCall"' in txt:
            for m in re.finditer(
                r'createPlanToolCall"\s*:\s*\{[^}]*"args"\s*:\s*\{[^}]*"name"\s*:\s*"([^"\n]{1,200})"',
                txt,
                flags=re.DOTALL,
            ):
                val = m.group(1).strip()
                if _looks_like_plan_display_name(val) and val not in names:
                    names.append(val)
    dedup = []
    for n in names:
        if n not in dedup:
            dedup.append(n)
    return dedup


def _latest_user_text(messages) -> str:
    if not isinstance(messages, list):
        return ""
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            blob = _message_text_for_plan_hint(msg)
            m = re.search(r"<user_query>\s*(.*?)\s*</user_query>", blob, flags=re.DOTALL | re.IGNORECASE)
            if m and m.group(1).strip():
                return m.group(1).strip()
            return blob
    return ""


def _user_wants_new_plan(text: str) -> bool:
    """Only explicit user intent to start a new plan (user_query text). No keyword lists for updates."""
    if not text:
        return False
    low = text.lower()
    if "更新计划" in text or "update plan" in low:
        return False
    if "不要新建" in text or "不要新建计划" in text or "别再新建" in text:
        return False
    markers = (
        "新建计划", "另一个计划", "重新制定", "重新创建", "从零", "另起",
        "new plan", "another plan", "from scratch", "start over",
    )
    if any(m.lower() in low for m in markers):
        return True
    if "新计划" in text and "更新计划" not in text:
        return True
    return False


def _first_plan_identity(messages) -> str:
    """Official session root: first CreatePlan.args.name in transcript order."""
    names = _extract_plan_names_from_messages(messages)
    if names:
        return names[0]
    slugs = _extract_plan_slugs_from_plan_md_paths(messages)
    return slugs[0] if slugs else ""


def resolve_plan_lock_name(obj: dict) -> str:
    """Custom API parity: after the first CreatePlan in messages, force stable args.name on outbound SSE.

    Official GUI keeps plan state client-side; the bridge only sees messages. Model often emits
    new titles (official CLI also uses v2/v3 names on casual optimize). Lock to the **first**
    plan identity in the thread unless user_query explicitly requests a new plan.
    """
    if not isinstance(obj, dict):
        return ""
    messages = obj.get("messages")
    if _user_wants_new_plan(_latest_user_text(messages)):
        return ""
    if not _conversation_has_createplan_history(messages):
        return ""
    return _first_plan_identity(messages)


def _conversation_has_createplan_history(messages) -> bool:
    if not isinstance(messages, list):
        return False
    if _extract_plan_slugs_from_plan_md_paths(messages):
        return True
    failed_cp = _failed_createplan_tool_call_ids(messages)
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        for tc in msg.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            if tc.get("id") in failed_cp:
                continue
            fn = tc.get("function") or {}
            if _is_plan_function_name(str(fn.get("name") or "")):
                return True
        if msg.get("role") == "tool" and _is_plan_function_name(str(msg.get("name") or "")):
            tid = msg.get("tool_call_id")
            if isinstance(tid, str) and tid in failed_cp:
                continue
            txt = _message_text_for_plan_hint(msg).lower()
            if "interrupted" in txt or "error" in txt:
                continue
            return True
        txt = _message_text_for_plan_hint(msg)
        if "createPlanToolCall" in txt:
            return True
        if ".plan.md" in txt and ("edited" in txt.lower() or "editToolCall" in txt):
            return True
    return False


def _extract_plan_slugs_from_plan_md_paths(messages) -> list[str]:
    slugs: list[str] = []
    if not isinstance(messages, list):
        return slugs
    pat = re.compile(r"([a-z][a-z0-9]+(?:-[a-z0-9]+)*)_[a-f0-9]{6,}\.plan\.md", re.IGNORECASE)
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        txt = _message_text_for_plan_hint(msg)
        for m in pat.finditer(txt):
            val = m.group(1).strip()
            if val and val not in slugs:
                slugs.append(val)
    return slugs


PLAN_SSE_CHAR_CHUNK = 24


def _latest_user_turn_plan_mode(messages) -> bool:
    if not isinstance(messages, list):
        return False
    for msg in reversed(messages):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        return "Plan mode is active" in _message_text_for_plan_hint(msg)
    return False


def _iter_char_chunks(text: str, size: int = PLAN_SSE_CHAR_CHUNK):
    if not text:
        return
    for i in range(0, len(text), max(1, int(size))):
        yield text[i : i + size]


def _fix_createplan_arguments_text(arg_text: str, tool_name: str, plan_lock_name: str) -> str:
    if not arg_text or not plan_lock_name or not _is_plan_function_name(tool_name):
        return arg_text
    try:
        obj = json.loads(arg_text)
    except Exception:
        obj = None
    if isinstance(obj, dict) and "name" in obj:
        if str(obj.get("name") or "").strip() != plan_lock_name:
            obj["name"] = plan_lock_name
            return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        return arg_text
    return re.sub(
        r'"name"\s*:\s*"(?:[^"\\]|\\.)*"',
        '"name":' + json.dumps(plan_lock_name, ensure_ascii=False),
        arg_text,
        count=1,
    )


def should_add_plan_update_nudge(obj: dict, plan_name: str) -> bool:
    """Reuse args.name when thread already has a plan anchor (official --continue semantics)."""
    if not plan_name or not isinstance(obj, dict):
        return False
    messages = obj.get("messages")
    if _user_wants_new_plan(_latest_user_text(messages)):
        return False
    return _conversation_has_createplan_history(messages) and bool(plan_name)


def make_plan_update_nudge(plan_name: str):
    safe_name = str(plan_name).replace("\n", " ")[:180]
    return {
        "role": "system",
        "content": (
            "Cursor Plan update (match official Cursor Plan mode): an existing plan is already active "
            f"with slug/name {safe_name!r}. Do NOT call CreatePlan again for revisions, simplifications, or v2/v3 updates. "
            "Instead: use ReadFile on the existing `.cursor/plans/` file for that plan (match the slug in the filename), "
            "then update that `.plan.md` in place (same pattern as official Plan mode: Edited …plan.md), using Shell or other allowed write tools. "
            "Do not create a new plan file, new slug, or second plan entry."
        ),
    }


def strip_createplan_tool_when_locked(obj: dict, plan_lock_name: str) -> bool:
    """Official follow-up turns use edit-in-place, not a second CreatePlan tool call."""
    if not plan_lock_name or not isinstance(obj, dict):
        return False
    if not _conversation_has_createplan_history(obj.get("messages")):
        return False
    tools = obj.get("tools")
    if not isinstance(tools, list):
        return False
    kept = []
    removed = False
    for t in tools:
        if not isinstance(t, dict):
            kept.append(t)
            continue
        fn = t.get("function") if isinstance(t.get("function"), dict) else {}
        if _is_plan_function_name(fn.get("name")):
            removed = True
            continue
        kept.append(t)
    if not removed:
        return False
    obj["tools"] = kept
    return True


def chat_to_responses_payload(obj: dict) -> tuple[dict, bool, str]:
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
    plan_names = _extract_plan_names_from_messages(messages)
    plan_update_name = _first_plan_identity(messages) or (plan_names[0] if plan_names else "")
    add_plan_nudge = should_add_plan_update_nudge(out, plan_update_name)
    plan_lock_name = resolve_plan_lock_name(out)
    if plan_lock_name:
        plan_update_name = plan_lock_name
        add_plan_nudge = True
        if strip_createplan_tool_when_locked(out, plan_lock_name):
            changed = True
    if force_initial_tool and isinstance(messages, list):
        already = any(isinstance(m, dict) and isinstance(m.get("content"), str) and "Cursor Agent compatibility instruction" in m.get("content", "") for m in messages)
        if not already:
            messages = [make_actionable_nudge()] + messages
            changed = True
    if add_plan_nudge and isinstance(messages, list):
        already = any(isinstance(m, dict) and isinstance(m.get("content"), str) and "Cursor Plan compatibility instruction" in m.get("content", "") for m in messages)
        if not already:
            messages = [make_plan_update_nudge(plan_update_name)] + messages
            out["_cursor_plan_update_name"] = plan_update_name
            changed = True
    resp = {}
    for k in ("model", "stream", "temperature", "top_p", "reasoning", "reasoning_effort", "service_tier", "user", "prompt_cache_key"):
        if k in out:
            resp[k] = out[k]
    # Cursor custom-OpenAI requests usually do not include Codex's prompt_cache_key.
    # New API/CPA use prompt_cache_key to keep channel affinity and provider-side
    # prompt cache stable. Without it, Cursor /cursor/v1 can round-robin across
    # accounts and repeatedly miss cache, causing multi-minute xhigh turns.
    if not resp.get("prompt_cache_key"):
        user_key = out.get("user") if isinstance(out.get("user"), str) and out.get("user") else ""
        if user_key:
            resp["prompt_cache_key"] = "cursor:" + hashlib.sha256((str(resp.get("model") or original_model or "") + ":" + user_key).encode("utf-8")).hexdigest()[:24]
            changed = True
    if "max_output_tokens" in out:
        resp["max_output_tokens"] = out["max_output_tokens"]
    elif "max_tokens" in out:
        resp["max_output_tokens"] = out["max_tokens"]
    if messages is not None:
        resp["input"] = chat_messages_to_responses_input(messages)
    tools = chat_tools_to_responses_tools(out.get("tools"))
    if tools:
        resp["tools"] = tools
        # Do not forward `metadata` to /v1/responses — upstream rejects Unsupported parameter: metadata.
        # Plan-update hint stays in the injected system message only (_cursor_plan_update_name is for local audit).
        if force_initial_tool:
            resp["tool_choice"] = "required"
        elif out.get("tool_choice") not in (None, {}, "none"):
            # After Cursor has returned any tool result, do not keep forcing required.
            # Let the model either call another tool or finish; otherwise failed Read
            # attempts can loop forever.
            resp["tool_choice"] = "auto" if out.get("tool_choice") == "required" else out.get("tool_choice")
    for k in DROP_FOR_RESPONSES:
        resp.pop(k, None)
    return resp, changed, plan_lock_name


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


def build_response_request_from_chat(raw: bytes) -> tuple[bytes, bool, dict, str]:
    obj = json.loads(raw.decode("utf-8"))
    resp, changed, plan_lock_name = chat_to_responses_payload(obj)
    return json.dumps(resp, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), changed, resp, plan_lock_name


def salted_retry_body(body: bytes, reason: str = "empty") -> bytes:
    """Keep model/reasoning unchanged; only change prompt_cache_key to avoid a poisoned empty upstream cache/affinity path on retry."""
    try:
        obj = json.loads(body.decode("utf-8"))
    except Exception:
        return body
    if not isinstance(obj, dict):
        return body
    base = obj.get("prompt_cache_key")
    if not isinstance(base, str) or not base:
        base = "cursor"
    obj["prompt_cache_key"] = base + ":retry-" + reason + ":" + hashlib.sha256((base + str(time.time_ns())).encode("utf-8")).hexdigest()[:8]
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


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


def _rough_token_estimate(text: str) -> int:
    """Conservative rough estimate for UI-only usage fallback; not used for billing."""
    if not text:
        return 0
    # Mixed Chinese/code/JSON tends to be closer than raw len/4 alone. Keep it
    # conservative so Cursor sees non-zero usage without wildly overstating.
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, int(ascii_chars / 4 + non_ascii_chars * 1.5))


def estimate_chat_prompt_usage(obj: dict, raw_len: int = 0):
    """Best-effort prompt usage for Cursor UI when upstream omits usage.

    Cursor Context Usage is not guaranteed to consume OpenAI usage, but if it
    does, it expects a standard usage chunk. This estimate is response-facing
    only; SubAPI/NewAPI billing still uses upstream usage.
    """
    if not isinstance(obj, dict):
        return None
    total = 0
    for msg in obj.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        total += 4
        content = msg.get("content")
        if isinstance(content, str):
            total += _rough_token_estimate(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, str):
                    total += _rough_token_estimate(part)
                elif isinstance(part, dict):
                    total += _rough_token_estimate(str(part.get("text") or part.get("content") or part.get("image_url") or ""))
        if isinstance(msg.get("tool_calls"), list):
            total += _rough_token_estimate(json.dumps(msg.get("tool_calls"), ensure_ascii=False, separators=(",", ":")))
        if msg.get("name"):
            total += 1
    tools = obj.get("tools")
    if isinstance(tools, list) and tools:
        total += _rough_token_estimate(json.dumps(tools, ensure_ascii=False, separators=(",", ":")))
    # Account for JSON/system wrapper overhead. raw_len fallback prevents 0 on
    # unusual payloads where content is nested differently.
    raw_est = max(0, int(raw_len / 5)) if raw_len else 0
    prompt = max(total, raw_est)
    if prompt <= 0:
        return None
    return {"prompt_tokens": int(prompt), "completion_tokens": 0, "total_tokens": int(prompt)}


def chat_usage_chunk(resp_id, model, usage):
    normalized_usage = normalize_usage(usage)
    if normalized_usage is None:
        return None
    chunk = {
        "id": resp_id or "chatcmpl-cursor-compat",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [],
        "usage": normalized_usage,
    }
    return json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))


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


def responses_sse_to_chat(resp, fallback_usage=None, plan_lock_name=""):
    resp_id = "chatcmpl-cursor-compat"
    model = None
    event = ""
    sent_role = False
    saw_tool = False
    last_output_kind = None  # "tool" if the latest assistant output is a function_call; "text" for final prose.
    tool_indices = {}
    tool_arg_streamed = {}
    tool_names_by_key = {}
    tool_arg_full = {}
    next_tool_index = 0
    completed = False
    text_buf = []
    event_counts = {}
    tool_names_seen = []
    tail_events = []
    usage_seen = None
    preroll_usage_sent = False

    def maybe_emit_preroll_usage():
        nonlocal preroll_usage_sent
        if preroll_usage_sent or not CURSOR_EMIT_USAGE_PREROLL:
            return None
        preroll_usage_sent = True
        return chat_usage_chunk(resp_id, model, fallback_usage)

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
        # After we have already translated response.completed and sent ChatCompletions [DONE]
        # to Cursor, keep draining the upstream New API stream until EOF instead of closing
        # immediately. Closing right after response.completed makes New API record
        # stream_status=client_gone/context canceled even though Cursor received a valid
        # tool_calls/stop finish.
        if completed:
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
            preroll = maybe_emit_preroll_usage()
            if preroll:
                yield sse_event(None, preroll)
            yield sse_event(None, chat_chunk(resp_id, model, {"role": "assistant"}))
            sent_role = True
        if typ in ("response.output_text.delta", "response.refusal.delta"):
            delta = obj.get("delta") or obj.get("text") or ""
            if delta:
                last_output_kind = "text"
                text_buf.append(str(delta))
                for piece in _iter_char_chunks(str(delta)):
                    yield sse_event(None, chat_chunk(resp_id, model, {"content": piece}))
        elif typ == "response.output_text.done":
            last_output_kind = "text"
            txt = obj.get("text") or obj.get("delta") or ""
            if txt and not text_buf:
                text_buf.append(str(txt))
                for piece in _iter_char_chunks(str(txt)):
                    yield sse_event(None, chat_chunk(resp_id, model, {"content": piece}))
        elif typ == "response.output_item.added":
            item = obj.get("item") or {}
            if isinstance(item, dict) and item.get("type") == "message":
                last_output_kind = "text"
            if isinstance(item, dict) and item.get("type") == "function_call":
                saw_tool = True
                last_output_kind = "tool"
                call_id = normalize_call_id(item.get("call_id") or item.get("id"), str(item.get("name")) + str(obj.get("output_index")))
                key = str(obj.get("output_index", call_id))
                tool_names_by_key[key] = str(item.get("name") or "tool")
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
                prev_full = tool_arg_full.get(key, "")
                merged = prev_full + str(delta)
                tool_name = tool_names_by_key.get(key, "")
                merged = _fix_createplan_arguments_text(merged, tool_name, plan_lock_name)
                tool_arg_full[key] = merged
                emit = merged[len(prev_full):]
                for piece in _iter_char_chunks(emit):
                    yield sse_event(None, chat_chunk(resp_id, model, {"tool_calls": [{"index": idx, "function": {"arguments": piece}}]}))
        elif typ == "response.output_item.done":
            item = obj.get("item") or {}
            if isinstance(item, dict) and item.get("type") == "message":
                last_output_kind = "text"
                txt = message_item_text(item)
                if txt and not text_buf:
                    text_buf.append(txt)
                    for piece in _iter_char_chunks(txt):
                        yield sse_event(None, chat_chunk(resp_id, model, {"content": piece}))
            if isinstance(item, dict) and item.get("type") == "function_call":
                saw_tool = True
                last_output_kind = "tool"
                key = str(obj.get("output_index", item.get("call_id", "0")))
                tool_names_by_key[key] = str(item.get("name") or tool_names_by_key.get(key, "tool"))
                idx = tool_indices.setdefault(key, next_tool_index)
                if idx == next_tool_index:
                    next_tool_index += 1
                args = item.get("arguments")
                # Responses often sends arguments both as deltas and again on item.done.
                # ChatCompletions SSE expects argument deltas only once; duplicating corrupts JSON args.
                if isinstance(args, str) and args and not tool_arg_streamed.get(key):
                    tool_name = tool_names_by_key.get(key, str(item.get("name") or "tool"))
                    args = _fix_createplan_arguments_text(args, tool_name, plan_lock_name)
                    for piece in _iter_char_chunks(args):
                        yield sse_event(None, chat_chunk(resp_id, model, {"tool_calls": [{"index": idx, "function": {"arguments": piece}}]}))
        elif typ == "response.completed":
            completed = True
            finish = "tool_calls" if last_output_kind == "tool" else "stop"
            log_summary("response.completed", finish)
            yield sse_event(None, chat_chunk(resp_id, model, {}, finish))
            if CURSOR_EMIT_USAGE_CHUNK and not preroll_usage_sent:
                usage_chunk = chat_usage_chunk(resp_id, model, usage_seen or fallback_usage)
                if usage_chunk:
                    yield sse_event(None, usage_chunk)
            yield sse_event(None, "[DONE]")
            # Do not break here. Drain any trailing upstream SSE bytes until EOF so the
            # New API container sees a clean upstream completion rather than a canceled
            # downstream context. No more chunks are forwarded to Cursor after [DONE].
            continue
    if not completed:
        finish = "tool_calls" if last_output_kind == "tool" else "stop"
        log_summary("stream_ended_without_response.completed", finish)
        yield sse_event(None, chat_chunk(resp_id, model, {}, finish))
        if CURSOR_EMIT_USAGE_CHUNK and not preroll_usage_sent:
            usage_chunk = chat_usage_chunk(resp_id, model, usage_seen or fallback_usage)
            if usage_chunk:
                yield sse_event(None, usage_chunk)
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
        req_start = time.monotonic()
        req_id = "%x-%d" % (int(time.time() * 1000), next(REQ_COUNTER))
        client_ip = (self.headers.get("X-Forwarded-For") or self.headers.get("X-Real-IP") or (self.client_address[0] if self.client_address else "")).split(",")[0].strip()
        upath = self.upstream_path()
        body = None
        changed = False
        mode = "direct-subapi"
        response_mode = "passthrough"
        fallback_usage = None
        plan_lock_name = ""
        request_raw_len = 0
        request_model = ""
        request_reasoning = ""
        request_tools_count = 0
        self.log_message("active-audit event=start req_id=%s client=%s method=%s path=%s upath=%s", req_id, client_ip, method, self.path, upath)
        if method in {"POST", "PUT", "PATCH"}:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            request_raw_len = len(raw)
            body = raw
            if raw and upath.endswith("/chat/completions"):
                try:
                    obj = json.loads(raw.decode("utf-8"))
                    if isinstance(obj, dict):
                        request_model = str(obj.get("model") or "")
                        request_tools_count = len(obj.get("tools") or []) if isinstance(obj.get("tools"), list) else 0
                        r0 = obj.get("reasoning")
                        if isinstance(r0, dict):
                            request_reasoning = str(r0.get("effort") or "")
                        else:
                            request_reasoning = str(obj.get("reasoning_effort") or r0 or "")
                        self.log_message("cursor-shape %s", audit_cursor_shape(obj, len(raw), upath))
                        capture_cursor_body(obj, raw, upath)
                        fallback_usage = estimate_chat_prompt_usage(obj, len(raw))
                    if isinstance(obj, dict) and isinstance(obj.get("tools"), list) and obj.get("tools"):
                        body, changed, robj, plan_lock_name = build_response_request_from_chat(raw)
                        upath = upath.rsplit("/chat/completions", 1)[0] + "/responses"
                        mode = "chat-via-responses"
                        response_mode = "responses-to-chat"
                        request_model = str(robj.get("model") or request_model)
                        rr = robj.get("reasoning") if isinstance(robj, dict) else None
                        if isinstance(rr, dict):
                            request_reasoning = str(rr.get("effort") or request_reasoning)
                        self.log_message("req-audit %s", audit_request(robj, mode))
                        if plan_lock_name:
                            self.log_message("plan-lock name=%s", plan_lock_name[:120])
                            if isinstance(robj, dict) and isinstance(robj.get("tools"), list):
                                self.log_message(
                                    "plan-lock tools=%s createplan_present=%s",
                                    len(robj.get("tools") or []),
                                    any(
                                        _is_plan_function_name(
                                            ((t.get("function") or {}) if isinstance(t, dict) else {}).get("name")
                                        )
                                        for t in (robj.get("tools") or [])
                                    ),
                                )
                        self.log_message("flow-audit event=request req_id=%s client=%s mode=%s path=%s upath=%s raw_len=%s model=%s reasoning=%s tools=%s stream=%s plan_lock=%s", req_id, client_ip, mode, self.path, upath, request_raw_len, request_model, request_reasoning, request_tools_count, bool(robj.get("stream")), bool(plan_lock_name))
                    else:
                        body, changed = normalize_chat_body(raw)
                        obj2 = json.loads((body or raw).decode("utf-8"))
                        if isinstance(obj2, dict):
                            self.log_message("req-audit %s", audit_request(obj2, "chat-native"))
                            self.log_message("flow-audit event=request req_id=%s client=%s mode=%s path=%s upath=%s raw_len=%s model=%s reasoning=%s tools=%s stream=%s", req_id, client_ip, "chat-native", self.path, upath, request_raw_len, request_model, request_reasoning, request_tools_count, bool(obj2.get("stream")))
                except Exception as e:
                    self.log_message("transform failed: %r", e)
                    body, changed = normalize_chat_body(raw)
        req = Request(UPSTREAM + upath, data=body, headers=self.make_headers(len(body) if body is not None else None), method=method)
        try:
            with urlopen(req, timeout=3600) as resp:
                upstream_open_ms = int((time.monotonic() - req_start) * 1000)
                upstream_request_id = resp.headers.get("X-Oneapi-Request-Id") or resp.headers.get("X-Request-Id") or resp.headers.get("Request-Id") or ""
                self.log_message("flow-audit event=upstream_open req_id=%s upstream_status=%s upstream_request_id=%s upstream_open_ms=%s", req_id, getattr(resp, "status", ""), upstream_request_id, upstream_open_ms)
                if response_mode == "responses-to-chat" and (body and b'"stream":true' in body.lower()):
                    # Do not send Cursor a normal 200/stop stream until we have seen
                    # meaningful model output (text or tool_calls).  The xAI/NewAPI failure
                    # mode for large Cursor contexts is a tiny Responses stream that only
                    # contains completion/usage plumbing; older bridge code translated that
                    # into a normal ChatCompletions stop with fallback usage, which leaves
                    # Cursor stuck at 0% with no actionable error.  Keep the early chunks
                    # pending; if the upstream finishes empty, return an explicit 502.
                    buf = bytearray(); cap = 256 * 1024
                    pending = []
                    headers_sent = False
                    saw_tool = False
                    saw_text = False
                    finish_seen = None
                    tool_names = []
                    chunk_count = 0
                    usage_out = False
                    usage_fallback_out = False
                    write_broken = False
                    write_broken_after_finish = False
                    first_chunk_ms = None
                    first_output_ms = None

                    def start_sse_response():
                        nonlocal headers_sent
                        if headers_sent:
                            return
                        self.send_response(resp.status)
                        self.send_header("Content-Type", "text/event-stream")
                        self.add_bridge_headers(changed, mode)
                        self.end_headers()
                        headers_sent = True

                    for c in responses_sse_to_chat(resp, fallback_usage=fallback_usage, plan_lock_name=plan_lock_name):
                        chunk_count += 1
                        if first_chunk_ms is None:
                            first_chunk_ms = int((time.monotonic() - req_start) * 1000)
                        if len(buf) < cap:
                            buf.extend(c[: cap - len(buf)])
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
                                if isinstance(o.get("usage"), dict):
                                    usage_out = True
                                    if fallback_usage and o.get("usage") == normalize_usage(fallback_usage):
                                        usage_fallback_out = True
                                delta = choice.get("delta") or {}
                                if delta.get("content"):
                                    saw_text = True
                                for tc in delta.get("tool_calls") or []:
                                    saw_tool = True
                                    fn = (tc.get("function") or {}).get("name")
                                    if fn and fn not in tool_names and len(tool_names) < 12:
                                        tool_names.append(fn)
                        except Exception:
                            pass

                        if first_output_ms is None and (saw_text or saw_tool):
                            first_output_ms = int((time.monotonic() - req_start) * 1000)
                        if not headers_sent and not (saw_text or saw_tool):
                            pending.append(c)
                            continue
                        try:
                            start_sse_response()
                            if pending:
                                for pc in pending:
                                    self.wfile.write(pc)
                                pending.clear()
                            self.wfile.write(c); self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            write_broken = True
                            write_broken_after_finish = bool(finish_seen)
                            try:
                                resp.close()
                            except Exception:
                                pass
                            break

                    empty_upstream_completion = (
                        not headers_sent
                        and not write_broken
                        and not saw_tool
                        and not saw_text
                        and finish_seen in {"stop", "tool_calls", None}
                    )
                    retried_empty_upstream = False
                    if empty_upstream_completion:
                        retried_empty_upstream = True
                        self.log_message("empty-upstream retrying once req_id=%s with salted prompt_cache_key chunks=%s bytes=%s finish_seen=%s", req_id, chunk_count, len(buf), finish_seen)
                        retry_body = salted_retry_body(body, "empty") if body is not None else body
                        retry_req = Request(UPSTREAM + upath, data=retry_body, headers=self.make_headers(len(retry_body) if retry_body is not None else None), method=method)
                        try:
                            with urlopen(retry_req, timeout=3600) as retry_resp:
                                retry_upstream_request_id = retry_resp.headers.get("X-Oneapi-Request-Id") or retry_resp.headers.get("X-Request-Id") or retry_resp.headers.get("Request-Id") or ""
                                if retry_upstream_request_id:
                                    upstream_request_id = retry_upstream_request_id
                                self.log_message("flow-audit event=retry_upstream_open req_id=%s upstream_status=%s upstream_request_id=%s", req_id, getattr(retry_resp, "status", ""), retry_upstream_request_id)
                                buf = bytearray(); pending = []; headers_sent = False
                                saw_tool = False; saw_text = False; finish_seen = None; tool_names = []
                                chunk_count = 0; usage_out = False; usage_fallback_out = False
                                for c in responses_sse_to_chat(retry_resp, fallback_usage=fallback_usage, plan_lock_name=plan_lock_name):
                                    chunk_count += 1
                                    if first_chunk_ms is None:
                                        first_chunk_ms = int((time.monotonic() - req_start) * 1000)
                                    if len(buf) < cap:
                                        buf.extend(c[: cap - len(buf)])
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
                                            if isinstance(o.get("usage"), dict):
                                                usage_out = True
                                                if fallback_usage and o.get("usage") == normalize_usage(fallback_usage):
                                                    usage_fallback_out = True
                                            delta = choice.get("delta") or {}
                                            if delta.get("content"):
                                                saw_text = True
                                            for tc in delta.get("tool_calls") or []:
                                                saw_tool = True
                                                fn = (tc.get("function") or {}).get("name")
                                                if fn and fn not in tool_names and len(tool_names) < 12:
                                                    tool_names.append(fn)
                                    except Exception:
                                        pass
                                    if first_output_ms is None and (saw_text or saw_tool):
                                        first_output_ms = int((time.monotonic() - req_start) * 1000)
                                    if not headers_sent and not (saw_text or saw_tool):
                                        pending.append(c)
                                        continue
                                    start_sse_response()
                                    if pending:
                                        for pc in pending:
                                            self.wfile.write(pc)
                                        pending.clear()
                                    self.wfile.write(c); self.wfile.flush()
                                empty_upstream_completion = (not headers_sent and not saw_tool and not saw_text and finish_seen in {"stop", "tool_calls", None})
                        except Exception as retry_e:
                            self.log_message("empty-upstream retry failed: %r", retry_e)
                    if empty_upstream_completion:
                        # Cursor maps non-2xx custom-provider failures to the misleading
                        # "User API Key Rate limit exceeded" banner.  After one real retry
                        # has also produced an empty upstream completion, return a normal SSE
                        # diagnostic instead of an HTTP error so the user sees the real cause.
                        diagnostic = "上游本轮返回空响应，桥接层已自动重试并改为可识别的空响应事件；这不是 API Key 限流。后续请求会继续走同一会话，不需要换 Key/Base/模型。"
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.add_bridge_headers(changed, mode)
                        self.send_header("X-Cursor-Upstream-Empty", "1")
                        self.end_headers()
                        self.wfile.write(sse_event(None, chat_chunk("chatcmpl-cursor-compat", None, {"role": "assistant"})))
                        self.wfile.write(sse_event(None, chat_chunk("chatcmpl-cursor-compat", None, {"content": diagnostic})))
                        self.wfile.write(sse_event(None, chat_chunk("chatcmpl-cursor-compat", None, {}, "stop")))
                        self.wfile.write(sse_event(None, "[DONE]")); self.wfile.flush()
                    elapsed_ms = int((time.monotonic() - req_start) * 1000)
                    status_kind = "empty_upstream" if empty_upstream_completion else ("write_broken" if write_broken else "ok")
                    self.log_message("resp-audit req_id=%s client=%s mode=%s path=%s upath=%s raw_len=%s model=%s reasoning=%s tools=%s upstream_status=%s upstream_request_id=%s has_tool_calls=%s saw_text=%s finish_seen=%s tool_names=%s chunks=%s bytes=%s usage_seen=%s usage_out=%s usage_fallback=%s empty_upstream=%s retried_empty=%s write_broken=%s write_broken_after_finish=%s upstream_open_ms=%s first_chunk_ms=%s first_output_ms=%s elapsed_ms=%s status=%s", req_id, client_ip, mode, self.path, upath, request_raw_len, request_model, request_reasoning, request_tools_count, getattr(resp, "status", ""), upstream_request_id, saw_tool, saw_text, finish_seen, ",".join(tool_names), chunk_count, len(buf), b'"usage"' in buf, usage_out, usage_fallback_out, empty_upstream_completion, retried_empty_upstream, write_broken, write_broken_after_finish, upstream_open_ms, first_chunk_ms, first_output_ms, elapsed_ms, status_kind)
                    self.log_message("active-audit event=end req_id=%s elapsed_ms=%s status=%s", req_id, elapsed_ms, status_kind)
                    if elapsed_ms >= CURSOR_SLOW_AUDIT_MS:
                        slow = {
                            "req_id": req_id,
                            "client": client_ip,
                            "path": self.path,
                            "upath": upath,
                            "mode": mode,
                            "upstream_status": getattr(resp, "status", ""),
                            "upstream_request_id": upstream_request_id,
                            "raw_len": request_raw_len,
                            "model": request_model,
                            "reasoning": request_reasoning,
                            "tools": request_tools_count,
                            "tool_names": tool_names,
                            "finish_seen": finish_seen,
                            "has_tool_calls": saw_tool,
                            "saw_text": saw_text,
                            "chunks": chunk_count,
                            "bytes": len(buf),
                            "upstream_open_ms": upstream_open_ms,
                            "first_chunk_ms": first_chunk_ms,
                            "first_output_ms": first_output_ms,
                            "elapsed_ms": elapsed_ms,
                            "empty_upstream": empty_upstream_completion,
                            "retried_empty": retried_empty_upstream,
                            "write_broken": write_broken,
                            "write_broken_after_finish": write_broken_after_finish,
                            "status": status_kind,
                        }
                        self.log_message("slow-audit %s", json.dumps(slow, ensure_ascii=False, separators=(",", ":")))
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
                    elapsed_ms = int((time.monotonic() - req_start) * 1000)
                    if elapsed_ms >= CURSOR_SLOW_AUDIT_MS:
                        self.log_message("slow-audit %s", json.dumps({"req_id": req_id, "client": client_ip, "path": self.path, "upath": upath, "mode": mode, "raw_len": request_raw_len, "model": request_model, "reasoning": request_reasoning, "tools": request_tools_count, "elapsed_ms": elapsed_ms, "status": "passthrough", "upstream_status": getattr(resp, "status", ""), "upstream_request_id": upstream_request_id, "upstream_open_ms": upstream_open_ms}, ensure_ascii=False, separators=(",", ":")))
                        self.log_message("active-audit event=end req_id=%s elapsed_ms=%s status=passthrough", req_id, elapsed_ms)
        except HTTPError as e:
            payload = e.read()
            elapsed_ms = int((time.monotonic() - req_start) * 1000)
            upstream_request_id = e.headers.get("X-Oneapi-Request-Id") or e.headers.get("X-Request-Id") or e.headers.get("Request-Id") or ""
            self.log_message("error-audit req_id=%s client=%s mode=%s path=%s upath=%s raw_len=%s model=%s reasoning=%s tools=%s upstream_status=%s upstream_request_id=%s elapsed_ms=%s bytes=%s", req_id, client_ip, mode, self.path, upath, request_raw_len, request_model, request_reasoning, request_tools_count, e.code, upstream_request_id, elapsed_ms, len(payload))
            self.log_message("active-audit event=end req_id=%s elapsed_ms=%s status=http_error_%s", req_id, elapsed_ms, e.code)
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() not in HOP:
                    self.send_header(k, v)
            self.add_bridge_headers(changed, mode)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:
            elapsed_ms = int((time.monotonic() - req_start) * 1000)
            self.log_message("exception-audit req_id=%s client=%s mode=%s path=%s upath=%s raw_len=%s model=%s reasoning=%s tools=%s elapsed_ms=%s error=%r", req_id, client_ip, mode, self.path, upath, request_raw_len, request_model, request_reasoning, request_tools_count, elapsed_ms, e)
            self.log_message("active-audit event=end req_id=%s elapsed_ms=%s status=exception", req_id, elapsed_ms)
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

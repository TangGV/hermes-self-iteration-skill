#!/usr/bin/env python3
"""SubAPI gpt-image-2 gateway: wrong /responses or /chat/completions -> Images API -> protocol-shaped JSON/SSE only (no extra copy)."""
import base64
import hashlib
import json
import re
import sys
import time
import uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from pathlib import Path

UPSTREAM = "http://127.0.0.1:3000"
LISTEN = ("127.0.0.1", 8328)
ARTIFACT_DIR = Path("/root/subapi-image-compat/artifacts")
PUBLIC_IMAGE_PREFIX = "https://subapi.aigcfast.com/subapi-image-artifacts/"
HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-length", "host",
    "accept-encoding",
}
IMAGE_RE = re.compile(r"^gpt-image", re.I)


def normalize_call_id(call_id, fallback_seed=""):
    s = str(call_id or "").strip()
    if not s:
        s = "call_" + hashlib.sha256(str(fallback_seed).encode()).hexdigest()[:32]
    if len(s) <= 64:
        return s
    return "call_" + hashlib.sha256(s.encode()).hexdigest()[:58]


def normalize_responses_input(items):
    if not isinstance(items, list):
        return items
    out = []
    for it in items:
        if not isinstance(it, dict):
            out.append(it)
            continue
        it = dict(it)
        typ = it.get("type")
        if typ == "function_call":
            seed = str(it.get("name") or "") + str(it.get("arguments") or "")[:80]
            it["call_id"] = normalize_call_id(
                it.get("call_id") or it.get("id") or it.get("tool_call_id"), seed
            )
        elif typ in ("function_call_output", "tool_result"):
            seed = str(it.get("output") or it.get("content") or "")[:80]
            it["call_id"] = normalize_call_id(
                it.get("call_id") or it.get("id") or it.get("tool_call_id"), seed
            )
        elif typ in (None, "message") and it.get("role") == "tool" and it.get("tool_call_id"):
            it["tool_call_id"] = normalize_call_id(it.get("tool_call_id"), str(it.get("content"))[:80])
        else:
            for key in ("call_id", "tool_call_id"):
                if key in it and it[key] is not None and len(str(it[key])) > 64:
                    it[key] = normalize_call_id(it[key], str(typ) + str(it.get("role") or ""))
        out.append(it)
    return out


def normalize_request_body(data):
    if not isinstance(data, dict):
        return data, False
    changed = False
    if isinstance(data.get("input"), list):
        data = dict(data)
        data["input"] = normalize_responses_input(data["input"])
        changed = True
    if isinstance(data.get("messages"), list):
        data = dict(data) if not changed else data
        msgs = []
        for m in data["messages"]:
            if not isinstance(m, dict):
                msgs.append(m)
                continue
            m = dict(m)
            if m.get("tool_call_id") and len(str(m["tool_call_id"])) > 64:
                m["tool_call_id"] = normalize_call_id(m["tool_call_id"], str(m.get("content"))[:80])
                changed = True
            if m.get("tool_calls"):
                tcs = []
                for tc in m["tool_calls"]:
                    if not isinstance(tc, dict):
                        tcs.append(tc)
                        continue
                    tc = dict(tc)
                    if tc.get("id") and len(str(tc["id"])) > 64:
                        tc["id"] = normalize_call_id(tc["id"], str(tc.get("function"))[:80])
                        changed = True
                    tcs.append(tc)
                m["tool_calls"] = tcs
            msgs.append(m)
        if changed:
            data["messages"] = msgs
    return data, changed


def is_image_model(model):
    return bool(model and IMAGE_RE.match(str(model).strip()))


def last_user_text_from_messages(messages):
    if not isinstance(messages, list):
        return ""
    for m in reversed(messages):
        if not isinstance(m, dict):
            continue
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            return c.strip()
        if isinstance(c, list):
            parts = []
            for it in c:
                if isinstance(it, dict) and it.get("type") in ("text", "input_text"):
                    parts.append(str(it.get("text", "")))
                elif isinstance(it, str):
                    parts.append(it)
            return " ".join(parts).strip()
    return ""


def prompt_from_body(data):
    if not isinstance(data, dict):
        return ""
    if "prompt" in data and isinstance(data["prompt"], str):
        return data["prompt"].strip()
    inp = data.get("input")
    if isinstance(inp, str):
        return inp.strip()
    if isinstance(inp, list):
        for it in reversed(inp):
            if isinstance(it, str) and it.strip():
                return it.strip()
            if isinstance(it, dict):
                if it.get("type") in ("input_text", "text") and it.get("text"):
                    return str(it["text"]).strip()
                if it.get("role") == "user":
                    t = prompt_from_body({"input": it.get("content")})
                    if t:
                        return t
    if "messages" in data:
        return last_user_text_from_messages(data.get("messages"))
    return ""


def forward_raw(method, path, body, headers):
    hdrs = {k: v for k, v in headers.items() if k.lower() not in HOP}
    req = Request(UPSTREAM + path, data=body, headers=hdrs, method=method)
    try:
        with urlopen(req, timeout=3600) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except HTTPError as e:
        return e.code, dict(e.headers), e.read()


def send_stream_passthrough(handler, method, path, body, headers):
    """Proxy upstream SSE without buffering the full response.

    This sidecar exists mainly for gpt-image compatibility, but nginx routes plain
    /v1/responses and /v1/chat/completions through it too. For non-image streamed
    Codex/Cursor requests, reading resp.read() first destroys typewriter output and
    makes clients see one big chunk at the end. Preserve SSE line boundaries here.
    """
    hdrs = {k: v for k, v in headers.items() if k.lower() not in HOP}
    req = Request(UPSTREAM + path, data=body, headers=hdrs, method=method)
    try:
        resp = urlopen(req, timeout=3600)
    except HTTPError as e:
        body = e.read()
        handler._respond_raw(e.code, dict(e.headers), body)
        return
    with resp:
        handler.send_response(resp.status)
        for k, v in resp.headers.items():
            if k.lower() in HOP or k.lower() == "content-length":
                continue
            handler.send_header(k, v)
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("X-Accel-Buffering", "no")
        handler.send_header("Connection", "close")
        handler.end_headers()
        while True:
            chunk = resp.readline()
            if not chunk:
                break
            try:
                handler.wfile.write(chunk)
                handler.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                break


def call_images(auth, model, prompt, size="1024x1024", quality="low"):
    payload = json.dumps(
        {"model": model, "prompt": prompt, "size": size, "n": 1, "quality": quality},
        ensure_ascii=False,
    ).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "Authorization": auth}
    req = Request(UPSTREAM + "/v1/images/generations", data=payload, headers=hdrs, method="POST")
    with urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def persist_b64_png(b64):
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.png"
    ARTIFACT_DIR.joinpath(name).write_bytes(base64.b64decode(b64))
    return PUBLIC_IMAGE_PREFIX + name


def client_wants_stream(data, headers):
    if isinstance(data, dict) and data.get("stream") is True:
        return True
    accept = (headers.get("Accept") or "").lower()
    return "text/event-stream" in accept


def image_result_from_official(img_json):
    """Map official Images API body only: data[0].url or hosted b64_json -> result URL."""
    data = img_json.get("data") or []
    if not data or not isinstance(data[0], dict):
        return None, None, None
    item = data[0]
    b64 = item.get("b64_json")
    url = item.get("url")
    if url:
        return url, b64, url
    if b64:
        try:
            public = persist_b64_png(b64)
        except Exception as ex:
            sys.stderr.write(f"artifact save failed: {ex}\n")
            return None, b64, None
        return public, b64, public
    return None, None, None


def image_generation_output_item(result_url, ig_id=None):
    return {
        "type": "image_generation_call",
        "id": ig_id or f"ig_{uuid.uuid4().hex[:12]}",
        "status": "completed",
        "result": result_url,
    }


def responses_body_from_official(model, img_json, result_url):
    created = img_json.get("created")
    if created is not None:
        try:
            created_at = int(created)
        except (TypeError, ValueError):
            created_at = int(time.time())
    else:
        created_at = int(time.time())
    ig = image_generation_output_item(result_url)
    return {
        "id": f"resp_{uuid.uuid4().hex[:24]}",
        "object": "response",
        "created_at": created_at,
        "status": "completed",
        "model": model,
        "output": [ig],
    }


def responses_api_response_bytes(model, img_json, result_url):
    return json.dumps(responses_body_from_official(model, img_json, result_url), ensure_ascii=False).encode("utf-8")


def _sse_data(obj):
    return ("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8")


def responses_stream_sse(model, img_json, result_url):
    """Responses SSE with response.completed; payload from official image result only."""
    ig_id = f"ig_{uuid.uuid4().hex[:12]}"
    completed = responses_body_from_official(model, img_json, result_url)
    resp_id = completed["id"]
    base = {
        "id": resp_id,
        "object": "response",
        "created_at": completed["created_at"],
        "status": "in_progress",
        "model": model,
        "output": [],
    }
    chunks = [
        _sse_data({"type": "response.created", "response": {**base}}),
        _sse_data({"type": "response.in_progress", "response": {**base}}),
        _sse_data(
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    **image_generation_output_item(result_url, ig_id),
                    "status": "in_progress",
                },
            }
        ),
        _sse_data(
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": image_generation_output_item(result_url, ig_id),
            }
        ),
        _sse_data({"type": "response.completed", "response": completed}),
        b"data: [DONE]\n\n",
    ]
    return b"".join(chunks)


def chat_completion_response(model, img_json, result_url):
    # Chat has no official image object; expose only official URL string if any (no wrapper text).
    content = result_url or ""
    created = img_json.get("created")
    try:
        created_i = int(created) if created is not None else int(time.time())
    except (TypeError, ValueError):
        created_i = int(time.time())
    body = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": created_i,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def chat_stream_sse(model, result_url):
    content = result_url or ""
    cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    chunk = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {"content": content} if content else {}, "finish_reason": None}],
    }
    lines = [
        f"data: {json.dumps(chunk, ensure_ascii=False)}",
        "data: "
        + json.dumps(
            {
                "id": cid,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            },
            ensure_ascii=False,
        ),
        "data: [DONE]",
        "",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                self.send_error(500, str(e))
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_GET(self):
        p = self.path.split("?", 1)[0]
        if p.startswith("/subapi-image-artifacts/"):
            name = p.split("/")[-1]
            if not name or ".." in name or "/" in name:
                self.send_error(400)
                return
            fp = ARTIFACT_DIR / name
            if not fp.is_file():
                self.send_error(404)
                return
            data = fp.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(data)
            return
        self._proxy_passthrough()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        auth = self.headers.get("Authorization") or ""

        if path not in ("/v1/responses", "/v1/chat/completions"):
            body2 = body
            if body:
                try:
                    d = json.loads(body.decode("utf-8"))
                    d, ch = normalize_request_body(d)
                    if ch:
                        body2 = json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode()
                except Exception:
                    body2 = body
            status, rh, out = forward_raw("POST", self.path, body2, dict(self.headers))
            self._respond_raw(status, rh, out)
            return

        try:
            data = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            self._json_error(400, "invalid json")
            return
        data, _ = normalize_request_body(data)
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()

        model = (data.get("model") or "").strip()
        if not is_image_model(model):
            if client_wants_stream(data, dict(self.headers)):
                send_stream_passthrough(self, "POST", self.path, body, dict(self.headers))
            else:
                status, rh, out = forward_raw("POST", self.path, body, dict(self.headers))
                self._respond_raw(status, rh, out)
            return

        prompt = prompt_from_body(data)
        if not prompt:
            self._json_error(400, "prompt required (from input/messages/prompt)")
            return
        size = data.get("size") or "1024x1024"
        quality = data.get("quality") or "low"
        if not auth:
            self._json_error(401, "Missing Authorization")
            return

        try:
            img = call_images(auth, model, prompt, size=size, quality=quality)
        except HTTPError as e:
            err_body = e.read()
            self._respond_raw(e.code, {"Content-Type": "application/json"}, err_body)
            return

        result_url, _b64, _ = image_result_from_official(img)
        if not result_url:
            self._respond_raw(502, {"Content-Type": "application/json"}, json.dumps(img, ensure_ascii=False).encode())
            return

        stream = client_wants_stream(data, dict(self.headers))

        if path == "/v1/chat/completions":
            if stream:
                out = chat_stream_sse(model, result_url)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.send_header("X-SubAPI-Image-Compat", "chat-sse")
                self.end_headers()
                self.wfile.write(out)
                return
            out = chat_completion_response(model, img, result_url)
            mode = "chat-json"
        elif path == "/v1/responses" and stream:
            out = responses_stream_sse(model, img, result_url)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("X-SubAPI-Image-Compat", "responses-sse")
            self.end_headers()
            self.wfile.write(out)
            return
        else:
            out = responses_api_response_bytes(model, img, result_url)
            mode = "responses-json"

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.send_header("Connection", "close")
        self.send_header("X-SubAPI-Image-Compat", mode)
        self.end_headers()
        self.wfile.write(out)

    def _proxy_passthrough(self):
        status, rh, out = forward_raw(self.command, self.path, None, dict(self.headers))
        self._respond_raw(status, rh, out)

    def _respond_raw(self, status, resp_headers, body):
        self.send_response(status)
        for k, v in resp_headers.items():
            if k.lower() in HOP:
                continue
            self.send_header(k, v)
        if body is not None:
            self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json_error(self, code, msg):
        out = json.dumps({"error": {"message": msg, "type": "invalid_request_error"}}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


if __name__ == "__main__":
    print(f"subapi-image-compat listening {LISTEN} -> {UPSTREAM}", flush=True)
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
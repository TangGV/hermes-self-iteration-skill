"""Self-test: plan follow-up must strip CreatePlan from upstream tools (official edit-in-place)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Load server module without running as __main__
import importlib.util

spec = importlib.util.spec_from_file_location("subapi_server", ROOT / "subapi-server.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def plan_fn_names(tools):
    out = []
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        if t.get("name"):
            out.append(t.get("name"))
            continue
        fn = t.get("function") if isinstance(t.get("function"), dict) else {}
        out.append(fn.get("name"))
    return out


def test_capture(path: Path, label: str) -> None:
    wrap = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    body = wrap.get("body")
    if isinstance(body, str):
        body = json.loads(body)
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    before = plan_fn_names(body.get("tools"))
    assert "CreatePlan" in before, f"{label}: capture should include CreatePlan before bridge"

    out_bytes, changed, robj, lock = mod.build_response_request_from_chat(raw)
    assert lock == "short-plan", f"{label}: lock={lock!r}"
    upstream_tools = robj.get("tools") or []
    names = plan_fn_names(upstream_tools)
    assert "CreatePlan" not in names, f"{label}: CreatePlan still in upstream tools: {names}"
    assert len(names) < len(before), f"{label}: expected fewer tools after strip, before={len(before)} after={len(names)}"

    msgs = robj.get("input") or []
    nudge = any(
        isinstance(m, dict)
        and m.get("role") == "system"
        and "Do NOT call CreatePlan again" in str(m.get("content") or "")
        for m in msgs
    )
    assert nudge, f"{label}: missing official update nudge in input"

    print(f"PASS {label}: lock={lock} upstream_tools={len(names)} createplan=False nudge=True changed={changed}")


def test_first_plan_keeps_createplan() -> None:
    body = {
        "model": "gpt-5.5",
        "stream": True,
        "messages": [{"role": "user", "content": "<user_query>随便做个计划短点的</user_query>"}],
        "tools": [
            {"type": "function", "function": {"name": "CreatePlan", "parameters": {}}},
            {"type": "function", "function": {"name": "ReadFile", "parameters": {}}},
        ],
    }
    raw = json.dumps(body).encode()
    _, _, robj, lock = mod.build_response_request_from_chat(raw)
    assert lock == "", f"first turn lock should be empty, got {lock!r}"
    names = plan_fn_names(robj.get("tools"))
    assert "CreatePlan" in names, f"first turn must keep CreatePlan: {names}"
    print("PASS first_plan: CreatePlan kept, lock empty")


def test_interrupted_createplan_no_lock() -> None:
    body = {
        "model": "gpt-5.5",
        "stream": True,
        "messages": [
            {"role": "user", "content": "<user_query>内容太少了</user_query>"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "cp1",
                        "type": "function",
                        "function": {
                            "name": "CreatePlan",
                            "arguments": json.dumps({"name": "通用执行计划"}, ensure_ascii=False),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "cp1",
                "name": "CreatePlan",
                "content": [{"type": "text", "text": "Error: CreatePlan was interrupted by the user after 9418ms"}],
            },
        ],
        "tools": [
            {"type": "function", "function": {"name": "CreatePlan", "parameters": {}}},
            {"type": "function", "function": {"name": "ReadFile", "parameters": {}}},
        ],
    }
    raw = json.dumps(body).encode()
    _, _, robj, lock = mod.build_response_request_from_chat(raw)
    assert lock == "", f"interrupted CreatePlan must not lock, got {lock!r}"
    names = plan_fn_names(robj.get("tools"))
    assert "CreatePlan" in names, f"retry turn should still expose CreatePlan: {names}"
    print("PASS interrupted_createplan: no lock, CreatePlan kept for retry")


def main() -> int:
    cap = Path(r"C:/Users/t/AppData/Local/Temp/vps3_cap/subapi-20260707-210001.json")
    if not cap.is_file():
        print("SKIP capture missing:", cap)
        return 2
    test_first_plan_keeps_createplan()
    test_interrupted_createplan_no_lock()
    test_capture(cap, "user_210001_simplify")
    test_capture(Path(r"C:/Users/t/AppData/Local/Temp/vps3_cap/subapi-latest.json"), "latest")
    print("OK all self-tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
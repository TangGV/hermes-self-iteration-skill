#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("subapi_server", HERE / "subapi-server.py")
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)  # type: ignore[union-attr]


def tools():
    return [
        {"type":"function","function":{"name":"ReadFile","parameters":{"type":"object"}}},
        {"type":"function","function":{"type":"custom","name":"ApplyPatch","format":{"type":"grammar"}}},
        {"type":"function","function":{"name":"Shell","parameters":{"type":"object"}}},
    ]


def test_comment_task_read_then_requires_edit_tool():
    obj={"model":"gpt-5.5","stream":True,"messages":[
        {"role":"user","content":"给当前代码加上必要的注释"},
        {"role":"assistant","tool_calls":[{"id":"r1","type":"function","function":{"name":"ReadFile","arguments":"{}"}}]},
        {"role":"tool","name":"ReadFile","tool_call_id":"r1","content":"Read BigWorldSubSceneSandboxWindow.cs L730-859"},
    ],"tools":tools(),"tool_choice":"auto"}
    resp, changed, lock = mod.chat_to_responses_payload(obj)
    assert resp["tool_choice"] == "required"


def test_comment_task_after_applypatch_may_finish():
    obj={"model":"gpt-5.5","stream":True,"messages":[
        {"role":"user","content":"给当前代码加上必要的注释"},
        {"role":"tool","name":"ReadFile","tool_call_id":"r1","content":"Read BigWorldSubSceneSandboxWindow.cs L730-859"},
        {"role":"tool","name":"ApplyPatch","tool_call_id":"p1","content":"Edited BigWorldSubSceneSandboxWindow.cs"},
    ],"tools":tools(),"tool_choice":"auto"}
    resp, changed, lock = mod.chat_to_responses_payload(obj)
    assert resp.get("tool_choice") == "auto"


if __name__ == "__main__":
    test_comment_task_read_then_requires_edit_tool()
    test_comment_task_after_applypatch_may_finish()
    print("ok")

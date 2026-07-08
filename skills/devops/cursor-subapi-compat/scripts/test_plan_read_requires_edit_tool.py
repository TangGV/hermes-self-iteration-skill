#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("subapi_server", HERE / "subapi-server.py")
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)  # type: ignore[union-attr]


def base_messages(extra):
    return [
        {"role":"user","content":"Plan mode is active\n优化计划"},
        {"role":"assistant","tool_calls":[{"id":"c1","type":"function","function":{"name":"CreatePlan","arguments":"{\"name\":\"fishing-minigame-entry\"}"}}]},
        {"role":"tool","name":"CreatePlan","tool_call_id":"c1","content":"{\"name\":\"fishing-minigame-entry\"}"},
    ] + extra


def tools():
    return [
        {"type":"function","function":{"name":"ReadFile","parameters":{"type":"object"}}},
        {"type":"function","function":{"type":"custom","name":"ApplyPatch","format":{"type":"grammar"}}},
        {"type":"function","function":{"name":"CreatePlan","parameters":{"type":"object"}}},
    ]


def test_plan_read_without_write_forces_required():
    obj={"model":"gpt-5.5","stream":True,"messages":base_messages([
        {"role":"assistant","tool_calls":[{"id":"r1","type":"function","function":{"name":"ReadFile","arguments":"{}"}}]},
        {"role":"tool","name":"ReadFile","tool_call_id":"r1","content":"Read fishing-minigame-entry_d42746e8.plan.md L1-45"},
    ]),"tools":tools(),"tool_choice":"auto"}
    resp, changed, lock = mod.chat_to_responses_payload(obj)
    assert lock == "fishing-minigame-entry"
    assert resp["tool_choice"] == "required"
    assert all(t.get("name") != "CreatePlan" for t in resp["tools"])


def test_plan_after_write_does_not_force_required():
    obj={"model":"gpt-5.5","stream":True,"messages":base_messages([
        {"role":"tool","name":"ReadFile","tool_call_id":"r1","content":"Read fishing-minigame-entry_d42746e8.plan.md L1-45"},
        {"role":"tool","name":"ApplyPatch","tool_call_id":"p1","content":"Edited fishing-minigame-entry_d42746e8.plan.md"},
    ]),"tools":tools(),"tool_choice":"auto"}
    resp, changed, lock = mod.chat_to_responses_payload(obj)
    assert lock == "fishing-minigame-entry"
    assert resp.get("tool_choice") == "auto"


if __name__ == "__main__":
    test_plan_read_without_write_forces_required()
    test_plan_after_write_does_not_force_required()
    print("ok")

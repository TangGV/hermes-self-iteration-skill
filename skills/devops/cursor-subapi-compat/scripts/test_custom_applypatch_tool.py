#!/usr/bin/env python3
"""Regression test: preserve Cursor ApplyPatch custom grammar tools.

Cursor sends ApplyPatch inside a ChatCompletions `type:function` wrapper, but the
inner function is actually a custom grammar tool.  The bridge must forward it to
Responses as `type: custom` with `format`, not flatten it to a JSON function.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("subapi_server", HERE / "subapi-server.py")
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)  # type: ignore[union-attr]


def test_applypatch_custom_grammar_preserved():
    tools = [
        {
            "type": "function",
            "function": {
                "type": "custom",
                "name": "ApplyPatch",
                "description": "Use this tool to edit files.",
                "format": {"type": "grammar", "syntax": "lark", "definition": "start: patch"},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ReadFile",
                "description": "read",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        },
    ]
    converted = mod.chat_tools_to_responses_tools(tools)
    assert converted[0]["type"] == "custom"
    assert converted[0]["name"] == "ApplyPatch"
    assert converted[0]["format"]["type"] == "grammar"
    assert converted[1]["type"] == "function"
    assert converted[1]["name"] == "ReadFile"
    inbound_names, inbound_custom = mod._tool_names_from_chat_tools(tools)
    outbound_names, outbound_custom = mod._tool_names_from_responses_tools(converted)
    assert "ApplyPatch" in inbound_names
    assert "ApplyPatch" in outbound_names
    assert inbound_custom == ["ApplyPatch"]
    assert outbound_custom == ["ApplyPatch"]


if __name__ == "__main__":
    test_applypatch_custom_grammar_preserved()
    print("ok")

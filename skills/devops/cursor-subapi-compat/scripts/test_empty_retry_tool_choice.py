#!/usr/bin/env python3
"""Regression test: empty upstream retry stays same model/effort but forces a tool call."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("subapi_server", HERE / "subapi-server.py")
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)  # type: ignore[union-attr]


def test_empty_retry_forces_tools_without_model_downgrade():
    original = {
        "model": "gpt-5.5",
        "reasoning": {"effort": "high"},
        "stream": True,
        "prompt_cache_key": "cursor:abc",
        "input": [{"role": "user", "content": "add comments"}],
        "tools": [
            {"type": "custom", "name": "ApplyPatch", "format": {"type": "grammar", "syntax": "lark", "definition": "start: patch"}},
            {"type": "function", "name": "ReadFile", "parameters": {"type": "object"}},
        ],
        "tool_choice": "auto",
    }
    out = json.loads(mod.empty_retry_body(json.dumps(original).encode("utf-8")).decode("utf-8"))
    assert out["model"] == "gpt-5.5"
    assert out["reasoning"] == {"effort": "high"}
    assert out["tool_choice"] == "required"
    assert out["prompt_cache_key"].startswith("cursor:abc:retry-empty:")
    assert out["input"][0]["role"] == "system"
    assert "empty-stream retry" in out["input"][0]["content"]
    assert out["tools"][0]["type"] == "custom"
    assert out["tools"][0]["name"] == "ApplyPatch"


if __name__ == "__main__":
    test_empty_retry_forces_tools_without_model_downgrade()
    print("ok")

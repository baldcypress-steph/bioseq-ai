"""Backend-agnostic client for open-weight models.

Talks to any OpenAI-compatible chat endpoint: Ollama (default), llama.cpp
server, vLLM, LM Studio, or a hosted open-weight model. Switching backends is
a change of base URL and model name, set by environment variables or the UI.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field


@dataclass
class LLMConfig:
    model: str = field(default_factory=lambda: os.getenv("BIOSEQ_MODEL", "qwen3:4b"))
    base_url: str = field(default_factory=lambda: os.getenv("BIOSEQ_BASE_URL", "http://localhost:11434/v1"))
    api_key: str = field(default_factory=lambda: os.getenv("BIOSEQ_API_KEY", "ollama"))
    temperature: float = 0.0  # deterministic as possible, for reproducibility
    timeout: float = 120.0


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON text exactly as the model produced it


@dataclass
class ModelReply:
    content: str
    tool_calls: list[ToolCall]


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_TEXT_TOOL_CALL = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def strip_thinking(text: str) -> str:
    """Remove <think>...</think> reasoning blocks emitted by models such as Qwen3."""
    return _THINK.sub("", text or "").strip()


def parse_text_tool_calls(text: str) -> list[ToolCall]:
    """Recover tool calls a model wrote as text (<tool_call>{...}</tool_call>) instead of structured calls.

    Small open-weight models sometimes do this; recovering them makes the
    harness robust across models and backends.
    """
    calls = []
    for match in _TEXT_TOOL_CALL.finditer(text or ""):
        try:
            obj = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "name" in obj:
            args = obj.get("arguments", obj.get("parameters", {}))
            calls.append(ToolCall(f"text_{uuid.uuid4().hex[:8]}", obj["name"], json.dumps(args)))
    return calls


class OpenAICompatibleLLM:
    def __init__(self, config: LLMConfig | None = None):
        from openai import OpenAI  # imported lazily so tools-only mode has no dependency

        self.config = config or LLMConfig()
        self.client = OpenAI(base_url=self.config.base_url, api_key=self.config.api_key, timeout=self.config.timeout)

    @property
    def name(self) -> str:
        return self.config.model

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ModelReply:
        kwargs = dict(model=self.config.model, messages=messages, temperature=self.config.temperature)
        if tools:
            kwargs["tools"] = tools
        msg = self.client.chat.completions.create(**kwargs).choices[0].message
        calls = [ToolCall(c.id, c.function.name, c.function.arguments or "{}") for c in (msg.tool_calls or [])]
        raw = msg.content or ""
        if not calls:
            calls = parse_text_tool_calls(strip_thinking(raw))
            raw = _TEXT_TOOL_CALL.sub("", raw)
        return ModelReply(content=strip_thinking(raw), tool_calls=calls)

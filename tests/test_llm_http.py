"""End-to-end test of the real OpenAI-compatible client against a local mock server
that speaks the same wire format as Ollama's /v1/chat/completions."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from bioseq_ai.agent import Agent
from bioseq_ai.llm import LLMConfig, OpenAICompatibleLLM

TOY = ">toy\nATGAAATTTGGGTAA\n"


def completion(message):
    return {"id": "x", "object": "chat.completion", "created": 0, "model": "mock",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", **message}}]}


class Handler(BaseHTTPRequestHandler):
    requests: list = []
    replies: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Handler.requests.append(body)
        data = json.dumps(completion(Handler.replies.pop(0))).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    Handler.requests, Handler.replies = [], []
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def test_structured_tool_calls_over_http(server):
    Handler.replies = [
        {"content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {
            "name": "translate_sequence", "arguments": '{"sequence_id": "toy", "to_stop": true}'}}]},
        {"content": "<think>easy</think>The toy sequence encodes `MKFGWWWWLL` or MKFG (4 aa)."},
    ]
    llm = OpenAICompatibleLLM(LLMConfig(model="mock", base_url=server))
    res = Agent(llm).run("What protein does toy encode?", TOY)
    assert res.trace[0].ok and res.trace[0].output["protein"]["value"] == "MKFG"
    assert "<think>" not in res.answer
    # The invented sequence in backticks is caught; the real one is not.
    assert res.faithfulness["unsupported_sequences"] == ["MKFGWWWWLL"]
    first = Handler.requests[0]
    assert first["model"] == "mock" and first["temperature"] == 0.0 and len(first["tools"]) == 4
    assert Handler.requests[1]["messages"][-1]["role"] == "tool"
    assert "api_key" not in json.dumps(res.manifest)


def test_text_tool_calls_over_http(server):
    Handler.replies = [
        {"content": '<tool_call>{"name": "analyze_sequence", "arguments": {"sequence_id": "toy"}}</tool_call>'},
        {"content": "GC content is 26.67%."},
    ]
    res = Agent(OpenAICompatibleLLM(LLMConfig(model="mock", base_url=server))).run("GC?", TOY)
    assert res.trace[0].ok and res.faithfulness["passed"]


def test_qwen3_gets_no_think_switch_and_progress_is_reported(server):
    Handler.replies = [
        {"content": None, "tool_calls": [{"id": "c", "type": "function", "function": {
            "name": "analyze_sequence", "arguments": '{"sequence_id": "toy"}'}}]},
        {"content": "GC content is 26.67%."},
    ]
    events = []
    llm = OpenAICompatibleLLM(LLMConfig(model="qwen3:4b", base_url=server, disable_thinking=True))
    Agent(llm).run("GC?", TOY, on_event=events.append)
    assert Handler.requests[0]["messages"][0]["content"].endswith("/no_think")
    assert any("ran analyze_sequence" in e for e in events) and any("with its answer" in e for e in events)
    assert llm.client.max_retries == 0

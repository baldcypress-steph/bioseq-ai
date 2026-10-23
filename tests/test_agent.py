"""Agent-loop tests use a scripted fake model, so no LLM is needed in CI."""

import json
from pathlib import Path

from bioseq_ai.agent import Agent, plan_without_llm, replay, run_tools_only
from bioseq_ai.llm import ModelReply, ToolCall, parse_text_tool_calls, strip_thinking

SAMPLE = (Path(__file__).parents[1] / "examples" / "sample.fasta").read_text()
TOY = ">toy\nATGAAATTTGGGTAA\n"


class FakeModel:
    name = "fake-model"

    def __init__(self, script):
        self.script = list(script)
        self.seen = []

    def chat(self, messages, tools=None):
        self.seen.append((messages, tools))
        step = self.script.pop(0)
        return step(messages) if callable(step) else step


def call(name, args, cid="c1"):
    return ModelReply("", [ToolCall(cid, name, json.dumps(args) if not isinstance(args, str) else args)])


def test_agent_calls_tool_then_answers():
    model = FakeModel([
        call("analyze_sequence", {"sequence_id": "toy"}),
        ModelReply("The GC content of toy is 26.67% over 15 nt.", []),
    ])
    res = Agent(model).run("What is the GC content?", TOY)
    assert res.stopped_reason == "answered"
    assert [t.tool for t in res.trace] == ["analyze_sequence"]
    assert res.trace[0].output["gc_percent"] == 26.67
    assert res.faithfulness["passed"] is True
    # The model was offered all four tools, with sequence_id restricted to loaded IDs.
    tools = model.seen[0][1]
    assert {t["function"]["name"] for t in tools} == {
        "analyze_sequence", "transcribe_sequence", "translate_sequence", "find_orfs"}
    assert tools[0]["function"]["parameters"]["properties"]["sequence_id"]["enum"] == ["toy"]


def test_tool_result_is_returned_to_model():
    model = FakeModel([call("translate_sequence", {"sequence_id": "toy"}), ModelReply("Protein MKFG.", [])])
    Agent(model).run("translate", TOY)
    tool_msg = model.seen[1][0][-1]
    assert tool_msg["role"] == "tool" and json.loads(tool_msg["content"])["protein"]["value"] == "MKFG*"


def test_hallucinated_number_is_flagged():
    model = FakeModel([
        call("analyze_sequence", {"sequence_id": "toy"}),
        ModelReply("GC content is 48.5% and the melting temperature is 61.2 C.", []),
    ])
    res = Agent(model).run("GC?", TOY)
    assert res.faithfulness["passed"] is False
    assert set(res.faithfulness["unsupported"]) == {"48.5", "61.2"}


def test_unknown_tool_and_bad_json_are_reported_back_and_recovered():
    model = FakeModel([
        call("delete_files", {}),
        call("analyze_sequence", "{not json"),
        call("analyze_sequence", {"sequence_id": "nope"}),
        call("analyze_sequence", {"sequence_id": "toy"}),
        ModelReply("Length is 15 nt.", []),
    ])
    res = Agent(model).run("length?", TOY)
    assert [t.ok for t in res.trace] == [False, False, False, True]
    assert "Unknown tool" in res.trace[0].error
    assert "not valid JSON" in res.trace[1].error
    assert "Unknown sequence_id" in res.trace[2].error
    assert res.stopped_reason == "answered"


def test_unexpected_argument_rejected():
    model = FakeModel([call("find_orfs", {"sequence_id": "toy", "rm": "-rf"}), ModelReply("ok", [])])
    res = Agent(model).run("orfs", TOY)
    assert not res.trace[0].ok and "Unexpected argument" in res.trace[0].error


def test_step_limit_forces_final_answer():
    loop = call("analyze_sequence", {"sequence_id": "toy"})
    model = FakeModel([loop, loop, ModelReply("Stopped: length 15 nt.", [])])
    res = Agent(model, max_steps=2).run("loop forever", TOY)
    assert res.stopped_reason == "max_steps"
    assert res.answer.startswith("Stopped")
    assert model.seen[-1][1] is None  # tools disabled on the forced final turn


def test_multiple_tool_calls_in_one_turn():
    reply = ModelReply("", [
        ToolCall("a", "analyze_sequence", '{"sequence_id": "demo_construct"}'),
        ToolCall("b", "find_orfs", '{"sequence_id": "demo_construct", "min_aa_length": 30}'),
    ])
    model = FakeModel([reply, ModelReply("done", [])])
    res = Agent(model).run("GC and ORFs", SAMPLE)
    assert [t.tool for t in res.trace] == ["analyze_sequence", "find_orfs"] and all(t.ok for t in res.trace)


def test_manifest_replays_identically():
    model = FakeModel([call("find_orfs", {"sequence_id": "demo_construct"}), ModelReply("done", [])])
    res = Agent(model).run("orfs", SAMPLE)
    m = json.loads(json.dumps(res.manifest))  # must survive a JSON round trip
    assert m["model"] == "fake-model" and len(m["input_sha256"]) == 64
    assert replay(m, SAMPLE) == [{"step": 1, "tool": "find_orfs", "identical": True}]


def test_text_tool_call_recovery_and_think_stripping():
    text = '<think>hmm</think><tool_call>{"name": "find_orfs", "arguments": {"sequence_id": "toy"}}</tool_call>'
    calls = parse_text_tool_calls(strip_thinking(text))
    assert calls[0].name == "find_orfs" and json.loads(calls[0].arguments) == {"sequence_id": "toy"}
    assert strip_thinking("<think>a\nb</think>Answer") == "Answer"


def test_keyword_planner_and_tools_only_mode():
    assert plan_without_llm("Translate this and find ORFs") == ["translate_sequence", "find_orfs"]
    assert plan_without_llm("hello") == ["analyze_sequence"]
    res = run_tools_only("GC content please", TOY)
    assert res.mode == "tools-only" and "26.67%" in res.answer and res.faithfulness["passed"]

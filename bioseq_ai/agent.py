"""The BioSeq AI agent loop.

ask model -> model requests tool(s) -> validate -> run -> return result -> repeat,
until the model writes a final answer or the step limit is reached. The final
answer is then checked for faithfulness against the tool outputs, and the whole
run is recorded as a replayable manifest.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from . import __version__
from .faithfulness import check_answer
from .llm import ModelReply
from .registry import TOOLS, SequenceStore, ToolError, run_tool, tool_schemas

SYSTEM_PROMPT = """You are BioSeq AI, a careful bioinformatics assistant.

You have tools that compute sequence statistics exactly. Rules:
1. Never compute or estimate numbers yourself. Every number, sequence or coordinate in your answer must come from a tool result.
2. Refer to sequences only by their sequence_id. Never copy DNA into a tool call.
3. Call every tool needed to answer the whole question, then write the answer.
4. In the answer: state the results with units, then a short plain-language interpretation.
5. Be cautious: a candidate ORF is not proof that a protein is made; sequence statistics are not a clinical or diagnostic interpretation.
6. If a tool returns an error, read it, fix the arguments and try again, or explain the problem to the user.

Loaded sequences:
{sequences}
"""


class ChatModel(Protocol):
    name: str

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ModelReply: ...


@dataclass
class TraceStep:
    step: int
    tool: str
    arguments: dict | str
    ok: bool
    output: dict | None = None
    error: str | None = None
    seconds: float = 0.0


@dataclass
class AgentResult:
    question: str
    answer: str
    trace: list[TraceStep]
    model: str
    mode: str
    faithfulness: dict
    stopped_reason: str
    seconds: float
    manifest: dict = field(default_factory=dict)

    @property
    def tool_outputs(self) -> list[dict]:
        return [t.output for t in self.trace if t.ok and t.output]


def _manifest(question: str, fasta_text: str, model: str, mode: str, trace, answer, faith, params) -> dict:
    try:
        import Bio

        bio_version = Bio.__version__
    except Exception:  # pragma: no cover
        bio_version = "unknown"
    return {
        "bioseq_ai_version": __version__,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "question": question,
        "input_sha256": hashlib.sha256(fasta_text.encode()).hexdigest(),
        "mode": mode,
        "model": model,
        "parameters": params,
        "tool_calls": [asdict(t) for t in trace],
        "answer": answer,
        "faithfulness": faith,
        "environment": {"python": platform.python_version(), "biopython": bio_version},
    }


def replay(manifest: dict, fasta_text: str) -> list[dict]:
    """Re-run every tool call in a manifest and report whether outputs are identical."""
    if hashlib.sha256(fasta_text.encode()).hexdigest() != manifest["input_sha256"]:
        raise ValueError("Input FASTA does not match the manifest's SHA-256; cannot replay faithfully.")
    store = SequenceStore.from_text(fasta_text)
    results = []
    for call in manifest["tool_calls"]:
        if not call["ok"]:
            continue
        new = run_tool(call["tool"], call["arguments"], store)
        results.append({"step": call["step"], "tool": call["tool"], "identical": new == call["output"]})
    return results


class Agent:
    def __init__(self, model: ChatModel, max_steps: int = 6):
        self.model = model
        self.max_steps = max_steps

    def run(self, question: str, fasta_text: str, on_event=None) -> AgentResult:
        """on_event(message: str) is called as the run progresses, for live progress display."""
        say = on_event or (lambda msg: None)
        t0 = time.time()
        store = SequenceStore.from_text(fasta_text)
        seq_lines = "\n".join(
            f"- {s['sequence_id']}: {s['length']} nt" + (f" ({s['description']})" if s["description"] else "")
            for s in store.summary()
        )
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT.format(sequences=seq_lines)},
            {"role": "user", "content": question},
        ]
        schemas = tool_schemas(store)
        trace: list[TraceStep] = []
        answer, reason = "", "max_steps"

        for step in range(1, self.max_steps + 1):
            say(f"Step {step}: asking {self.model.name} what to do next…")
            ts_model = time.time()
            reply = self.model.chat(messages, schemas)
            say(f"Step {step}: model replied in {time.time() - ts_model:.1f}s"
                + (f" and requested {', '.join(c.name for c in reply.tool_calls)}" if reply.tool_calls else " with its answer"))
            if not reply.tool_calls:
                answer, reason = reply.content, "answered"
                break
            messages.append({
                "role": "assistant",
                "content": reply.content or "",
                "tool_calls": [
                    {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                    for c in reply.tool_calls
                ],
            })
            for call in reply.tool_calls:
                ts = time.time()
                try:
                    args = json.loads(call.arguments) if isinstance(call.arguments, str) else call.arguments
                    if args is None:
                        args = {}
                except json.JSONDecodeError as exc:
                    args = call.arguments
                    out = {"error": f"Arguments were not valid JSON ({exc.msg}). Send a JSON object."}
                    trace.append(TraceStep(step, call.name, args, False, error=out["error"], seconds=time.time() - ts))
                else:
                    try:
                        out = run_tool(call.name, args, store)
                        trace.append(TraceStep(step, call.name, args, True, output=out, seconds=time.time() - ts))
                    except ToolError as exc:
                        out = {"error": str(exc)}
                        trace.append(TraceStep(step, call.name, args, False, error=str(exc), seconds=time.time() - ts))
                last = trace[-1]
                say(f"Step {step}: ran {last.tool} → {'ok' if last.ok else 'error: ' + str(last.error)}")
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(out)})
        else:
            # Step limit reached: ask once more for an answer with tools disabled.
            say("Step limit reached; asking the model for a final answer…")
            reply = self.model.chat(messages + [{
                "role": "user",
                "content": "Tool budget reached. Answer now using only the tool results above.",
            }], None)
            answer = reply.content

        if not answer.strip():
            answer = "The model did not produce an answer. See the tool calls below for the computed results."
        outputs = [t.output for t in trace if t.ok and t.output]
        faith = check_answer(answer, outputs, question).to_dict()
        params = {"max_steps": self.max_steps, **getattr(getattr(self.model, "config", None), "__dict__", {})}
        params.pop("api_key", None)
        result = AgentResult(question, answer, trace, self.model.name, "agent", faith, reason, round(time.time() - t0, 2))
        result.manifest = _manifest(question, fasta_text, self.model.name, "agent", trace, answer, faith, params)
        return result


# --------------------------------------------------------------------------- #
# Tools-only mode: no LLM. Used for CPU-only hosted demos and as a baseline.
# --------------------------------------------------------------------------- #
_KEYWORDS = {
    "analyze_sequence": r"\b(gc|at content|composition|length|analy[sz]e|stats?|statistics|count)",
    "transcribe_sequence": r"\b(transcri|mrna|rna)",
    "translate_sequence": r"\b(translat|protein|amino|peptide|codon|reverse strand|frame -)",
    "find_orfs": r"\b(orfs?|open reading|reading frames?|genes?|coding region|cds)\b",
}


def plan_without_llm(question: str) -> list[str]:
    """Keyword baseline planner. The benchmark compares the LLM agent against this."""
    q = question.lower()
    picked = [name for name, pat in _KEYWORDS.items() if re.search(pat, q)]
    return picked or ["analyze_sequence"]


def run_tools_only(question: str, fasta_text: str) -> AgentResult:
    t0 = time.time()
    store = SequenceStore.from_text(fasta_text)
    trace = []
    lines = []
    step = 0
    for sid in store.records:
        for name in plan_without_llm(question):
            step += 1
            try:
                out = run_tool(name, {"sequence_id": sid}, store)
                trace.append(TraceStep(step, name, {"sequence_id": sid}, True, output=out))
                lines.append(_summarize(name, out))
            except ToolError as exc:
                trace.append(TraceStep(step, name, {"sequence_id": sid}, False, error=str(exc)))
                lines.append(f"**{sid}** – {name} failed: {exc}")
    answer = "\n".join(f"- {line}" for line in lines)
    faith = check_answer(answer, [t.output for t in trace if t.ok], question).to_dict()
    res = AgentResult(question, answer, trace, "none (keyword planner)", "tools-only", faith, "answered", round(time.time() - t0, 2))
    res.manifest = _manifest(question, fasta_text, res.model, "tools-only", trace, answer, faith, {})
    return res


def _summarize(name: str, o: dict) -> str:
    sid = o["sequence_id"]
    if name == "analyze_sequence":
        gc = "unknown (only N bases)" if o["gc_percent"] is None else f"{o['gc_percent']}%"
        return f"**{sid}**: {o['length']} nt, GC content {gc}"
    if name == "transcribe_sequence":
        r = o["rna"]["value"]
        return f"**{sid}** RNA ({o['rna_length']} nt): `{r[:60]}{'...' if o['rna_length'] > 60 else ''}`"
    if name == "translate_sequence":
        p = o["protein"]["value"]
        return (f"**{sid}** frame {o['frame']:+d}: {o['protein_length']} aa, {o['stop_codon_count']} stop codon(s): "
                f"`{p[:60]}{'...' if len(p) > 60 else ''}`")
    if name == "find_orfs":
        if not o["orf_count"]:
            return f"**{sid}**: no ORFs of at least {o['min_aa_length']} aa"
        best = o["orfs_longest_first"][0]
        return (f"**{sid}**: {o['orf_count']} candidate ORF(s); longest is {best['length_aa']} aa on strand "
                f"{best['strand']} ({best['start']}-{best['end']})")
    return f"{name}: done"


__all__ = ["Agent", "AgentResult", "TraceStep", "run_tools_only", "plan_without_llm", "replay", "SYSTEM_PROMPT", "TOOLS"]

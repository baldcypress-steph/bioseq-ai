"""Benchmark BioSeq AI: open-weight model(s) vs. the keyword baseline.

    python benchmark/run_benchmark.py                          # baseline only
    python benchmark/run_benchmark.py --models qwen3:4b llama3.2:3b

Metrics per system (averaged over tasks):
  tool_recall      expected tools that were actually called successfully
  extra_tools      calls to tools the task did not need
  call_errors      tool calls that failed validation
  answer_has_facts expected values present in the final answer
  faithful         answers whose numbers all trace to tool outputs
  seconds          mean wall-clock time per task
Writes benchmark/results.md and benchmark/results.json.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bioseq_ai.agent import Agent, run_tools_only  # noqa: E402
from bioseq_ai.llm import LLMConfig, OpenAICompatibleLLM  # noqa: E402

FASTA = (ROOT / "examples" / "sample.fasta").read_text()
TASKS = json.loads((ROOT / "benchmark" / "tasks.json").read_text())


def score(task: dict, res) -> dict:
    called_ok = {t.tool for t in res.trace if t.ok}
    expected = set(task["tools"])
    facts = task["expect"]
    norm = res.answer.replace(",", "")
    return {
        "id": task["id"],
        "tool_recall": len(expected & called_ok) / len(expected),
        "extra_tools": len(called_ok - expected),
        "call_errors": sum(not t.ok for t in res.trace),
        "answer_has_facts": (sum(f in norm for f in facts) / len(facts)) if facts else 1.0,
        "faithful": float(res.faithfulness["passed"]),
        "seconds": res.seconds,
        "tools_called": [t.tool for t in res.trace],
    }


def evaluate(name: str, runner) -> dict:
    rows = []
    for task in TASKS:
        try:
            rows.append(score(task, runner(task["question"])))
        except Exception as exc:  # a crashed task scores zero rather than aborting the run
            rows.append({"id": task["id"], "tool_recall": 0, "extra_tools": 0, "call_errors": 1,
                         "answer_has_facts": 0, "faithful": 0, "seconds": 0, "error": str(exc)})
        print(f"  {name:28s} {task['id']:8s} recall={rows[-1]['tool_recall']:.2f} "
              f"facts={rows[-1]['answer_has_facts']:.2f} faithful={rows[-1]['faithful']:.0f}")
    keys = ["tool_recall", "extra_tools", "call_errors", "answer_has_facts", "faithful", "seconds"]
    return {"system": name, **{k: round(statistics.mean(r[k] for r in rows), 3) for k in keys}, "tasks": rows}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--models", nargs="*", default=[], help="Ollama/OpenAI-compatible model names")
    p.add_argument("--base-url", default=None)
    a = p.parse_args(argv)

    results = [evaluate("keyword baseline (no LLM)", lambda q: run_tools_only(q, FASTA))]
    for m in a.models:
        cfg = LLMConfig(model=m)
        if a.base_url:
            cfg.base_url = a.base_url
        agent = Agent(OpenAICompatibleLLM(cfg))
        results.append(evaluate(m, lambda q, agent=agent: agent.run(q, FASTA)))

    header = "| System | Tool recall | Extra tools / task | Failed calls / task | Facts in answer | Faithful answers | Sec / task |\n|---|---|---|---|---|---|---|\n"
    table = header + "".join(
        f"| {r['system']} | {r['tool_recall']:.0%} | {r['extra_tools']:.2f} | {r['call_errors']:.2f} | "
        f"{r['answer_has_facts']:.0%} | {r['faithful']:.0%} | {r['seconds']:.1f} |\n" for r in results)
    out = ROOT / "benchmark"
    (out / "results.md").write_text(f"# Benchmark results ({len(TASKS)} tasks)\n\n{table}")
    (out / "results.json").write_text(json.dumps(results, indent=2))
    print("\n" + table)
    return 0


if __name__ == "__main__":
    sys.exit(main())

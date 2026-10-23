"""Command line: bioseq ask FASTA "question"   |   bioseq replay manifest.json FASTA"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import Agent, replay, run_tools_only
from .llm import LLMConfig, OpenAICompatibleLLM


def _print_result(res) -> None:
    print(f"\n[{res.mode}] model: {res.model}  ({res.seconds}s, stop: {res.stopped_reason})\n")
    for t in res.trace:
        status = "ok" if t.ok else f"ERROR: {t.error}"
        print(f"  step {t.step}: {t.tool}({json.dumps(t.arguments)}) -> {status}")
    print("\n" + res.answer + "\n")
    f = res.faithfulness
    if f["passed"]:
        print(f"Faithfulness: PASS ({f['numbers_checked']} numbers traced to tool outputs)")
    else:
        print(f"Faithfulness: WARNING unsupported numbers {f['unsupported']} sequences {f['unsupported_sequences']}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bioseq", description="BioSeq AI: open-weight sequence analysis agent")
    sub = p.add_subparsers(dest="cmd", required=True)

    ask = sub.add_parser("ask", help="Ask a question about the sequences in a FASTA file")
    ask.add_argument("fasta", type=Path)
    ask.add_argument("question")
    ask.add_argument("--model", help="Model name (default: $BIOSEQ_MODEL or qwen3:4b)")
    ask.add_argument("--base-url", help="OpenAI-compatible endpoint (default: Ollama on localhost)")
    ask.add_argument("--max-steps", type=int, default=6)
    ask.add_argument("--tools-only", action="store_true", help="Skip the LLM; use the keyword baseline")
    ask.add_argument("--save", type=Path, help="Write the run manifest JSON here")

    rp = sub.add_parser("replay", help="Re-run the tool calls in a saved manifest and check they match")
    rp.add_argument("manifest", type=Path)
    rp.add_argument("fasta", type=Path)

    a = p.parse_args(argv)
    if a.cmd == "replay":
        rows = replay(json.loads(a.manifest.read_text()), a.fasta.read_text())
        for r in rows:
            print(f"step {r['step']} {r['tool']}: {'identical' if r['identical'] else 'DIFFERENT'}")
        return 0 if all(r["identical"] for r in rows) else 1

    fasta = a.fasta.read_text()
    if a.tools_only:
        res = run_tools_only(a.question, fasta)
    else:
        cfg = LLMConfig()
        if a.model:
            cfg.model = a.model
        if a.base_url:
            cfg.base_url = a.base_url
        try:
            res = Agent(OpenAICompatibleLLM(cfg), max_steps=a.max_steps).run(a.question, fasta)
        except Exception as exc:  # connection errors etc.
            print(f"Could not reach the model at {cfg.base_url} ({exc}).\n"
                  f"Is Ollama running? Try: ollama serve  and  ollama pull {cfg.model}\n"
                  "Or run with --tools-only.", file=sys.stderr)
            return 2
    _print_result(res)
    if a.save:
        a.save.write_text(json.dumps(res.manifest, indent=2))
        print(f"Manifest saved to {a.save}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

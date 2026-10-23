#!/usr/bin/env python3
"""Command-line entry point for the bioseq-analysis Agent Skill. Prints JSON."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from bioseq_tools import (  # noqa: E402  (vendored copy of bioseq_ai/tools.py)
        SequenceError, analyze_sequence, find_orfs, parse_fasta, transcribe_sequence, translate_sequence)
except ImportError as exc:  # Biopython missing
    print(json.dumps({"error": f"{exc}. Install Biopython with: pip install biopython"}))
    sys.exit(1)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Tested DNA/RNA sequence analysis (BioSeq AI skill)")
    p.add_argument("command", choices=["analyze", "transcribe", "translate", "orfs"])
    p.add_argument("fasta", nargs="?", help="FASTA file path")
    p.add_argument("--seq", help="A bare sequence instead of a file")
    p.add_argument("--frame", type=int, default=1)
    p.add_argument("--strand", default="+", choices=["+", "-"])
    p.add_argument("--table", type=int, default=1, help="NCBI genetic code ID")
    p.add_argument("--to-stop", action="store_true")
    p.add_argument("--min-aa", type=int, default=30)
    p.add_argument("--forward-only", action="store_true")
    a = p.parse_args(argv)

    try:
        if a.seq:
            text = a.seq
        elif a.fasta:
            text = Path(a.fasta).read_text()
        else:
            raise SequenceError("Give a FASTA file path or --seq SEQUENCE.")
        results = []
        for rec in parse_fasta(text):
            s = rec["sequence"]
            if a.command == "analyze":
                out = analyze_sequence(s)
            elif a.command == "transcribe":
                out = transcribe_sequence(s)
            elif a.command == "translate":
                out = translate_sequence(s, frame=a.frame, strand=a.strand, table=a.table, to_stop=a.to_stop)
            else:
                out = find_orfs(s, min_protein_length=a.min_aa, table=a.table, both_strands=not a.forward_only)
            results.append({"id": rec["id"], **out})
    except (SequenceError, OSError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps({"command": a.command, "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Tool registry: the allowlist of functions the model may call.

The model never retypes DNA. Sequences are loaded into a SequenceStore and the
model refers to them by ID (e.g. "seq1"). This removes a whole class of error
where a small model drops or alters bases when copying a long sequence into a
tool call, and it keeps prompts short.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

from . import bioinformatics_tools as bt


class SequenceError(ValueError):
    """Raised when input text is not a usable FASTA file or sequence."""


def parse_fasta(text: str) -> list[dict]:
    """Parse FASTA text (one or more records, or a bare sequence) into [{"id", "description", "sequence"}].

    The app accepts multi-record files; each record is then analyzed with the
    single-sequence functions in bioinformatics_tools. Whitespace and digits
    (GenBank-style numbering) are removed; validation happens in the tools.
    """
    if not text or not text.strip():
        raise SequenceError("No sequence provided.")
    records: list[dict] = []
    header, chunks = None, []

    def flush():
        if header is None and not chunks:
            return
        rid, _, desc = (header if header is not None else f"seq{len(records) + 1}").partition(" ")
        records.append({"id": rid or f"seq{len(records) + 1}", "description": desc.strip(), "sequence": "".join(chunks)})

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith(">"):
            flush()
            header, chunks = line[1:].strip(), []
        else:
            chunks.append("".join(ch for ch in line if not ch.isspace() and not ch.isdigit()))
    flush()
    records = [r for r in records if r["sequence"]]
    if not records:
        raise SequenceError("FASTA contained headers but no sequence data.")
    return records


# Long strings are shortened in what the model sees, so a small model's context isn't flooded.
PREVIEW_LIMIT = 300


def _preview(s: str) -> dict:
    if len(s) <= PREVIEW_LIMIT:
        return {"value": s, "truncated": False}
    return {"value": s[:PREVIEW_LIMIT] + "...", "truncated": True, "full_length": len(s)}


# ---- Adapters: call the bioinformatics_tools functions unchanged and label their results. ---- #
def analyze(sequence: str) -> dict:
    return bt.analyze_sequence(sequence)


def transcribe(sequence: str) -> dict:
    rna = bt.transcribe_sequence(sequence)
    return {"rna_length": len(rna), "rna": _preview(rna),
            "note": "Input treated as the coding (sense) strand, 5'->3'."}


def translate(sequence: str, frame: int = 1, to_stop: bool = False) -> dict:
    protein = bt.translate_sequence(sequence, frame, to_stop=bool(to_stop))
    return {"frame": frame, "protein": _preview(protein), "protein_length": len(protein),
            "stop_codon_count": protein.count("*"), "genetic_code": 1,
            "note": "'*' marks a stop codon; frames -1..-3 read the reverse complement."}


MAX_ORFS_SHOWN = 10


def orfs(sequence: str, min_aa_length: int = 30) -> dict:
    found = bt.find_orfs(sequence, min_aa_length=min_aa_length)
    longest = sorted(found, key=lambda o: (-o["length_aa"], o["start"]))
    shown = [{**o, "protein_sequence": _preview(o["protein_sequence"])} for o in longest[:MAX_ORFS_SHOWN]]
    return {"min_aa_length": min_aa_length, "orf_count": len(found),
            "longest_orf_aa": longest[0]["length_aa"] if longest else 0,
            "orfs_longest_first": shown, "orfs_truncated": len(found) > MAX_ORFS_SHOWN,
            "note": "Coordinates are 1-based inclusive on the input sequence. Every in-frame ATG is a separate "
                    "candidate, so nested ORFs share a stop codon. Candidates only, not evidence of expression."}


class ToolError(Exception):
    """A tool call the agent should report back to the model (bad name/arguments)."""


@dataclass
class SequenceStore:
    records: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def from_text(cls, text: str) -> "SequenceStore":
        store = cls()
        for rec in parse_fasta(text):
            rid = rec["id"]
            while rid in store.records:  # de-duplicate repeated headers
                rid += "_dup"
            store.records[rid] = {**rec, "id": rid}
        return store

    def get(self, sequence_id: str) -> str:
        if sequence_id not in self.records:
            raise ToolError(
                f"Unknown sequence_id {sequence_id!r}. Available: {', '.join(self.records) or 'none'}."
            )
        return self.records[sequence_id]["sequence"]

    def summary(self) -> list[dict]:
        return [
            {"sequence_id": r["id"], "description": r["description"], "length": len(r["sequence"])}
            for r in self.records.values()
        ]


@dataclass
class Tool:
    name: str
    func: Callable[..., dict]
    description: str
    parameters: dict  # JSON Schema for arguments other than the sequence

    def schema(self, sequence_ids: list[str]) -> dict:
        props = {
            "sequence_id": {
                "type": "string",
                "description": "ID of a loaded sequence.",
                **({"enum": sequence_ids} if sequence_ids else {}),
            },
            **self.parameters,
        }
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": props, "required": ["sequence_id"]},
            },
        }


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "analyze_sequence",
            analyze,
            "Length, nucleotide composition (A, C, G, T, N counts) and GC percentage of a DNA sequence.",
            {},
        ),
        Tool(
            "transcribe_sequence",
            transcribe,
            "Transcribe a DNA coding strand into RNA (T becomes U).",
            {},
        ),
        Tool(
            "translate_sequence",
            translate,
            "Translate DNA into protein in one of six reading frames (standard genetic code).",
            {
                "frame": {"type": "integer", "enum": [1, 2, 3, -1, -2, -3],
                          "description": "Reading frame: 1-3 forward, -1 to -3 reverse complement. Default 1."},
                "to_stop": {"type": "boolean", "description": "Stop at the first stop codon. Default false."},
            },
        ),
        Tool(
            "find_orfs",
            orfs,
            "Find candidate open reading frames (ATG to stop codon) in all six frames, longest first.",
            {
                "min_aa_length": {"type": "integer",
                                  "description": "Minimum ORF length in amino acids, excluding the stop. Default 30."},
            },
        ),
    ]
}


def tool_schemas(store: SequenceStore) -> list[dict]:
    ids = list(store.records)
    return [t.schema(ids) for t in TOOLS.values()]


def run_tool(name: str, arguments: dict[str, Any], store: SequenceStore) -> dict:
    """Validate and execute one tool call. Raises ToolError for anything the model got wrong."""
    if name not in TOOLS:
        raise ToolError(f"Unknown tool {name!r}. Available tools: {', '.join(TOOLS)}.")
    if not isinstance(arguments, dict):
        raise ToolError("Tool arguments must be a JSON object.")
    tool = TOOLS[name]
    args = dict(arguments)
    seq_id = args.pop("sequence_id", None)
    if seq_id is None:
        if len(store.records) == 1:  # forgiving default when there is only one sequence
            seq_id = next(iter(store.records))
        else:
            raise ToolError("Missing required argument 'sequence_id'.")
    sequence = store.get(str(seq_id))
    allowed = set(inspect.signature(tool.func).parameters) - {"sequence"}
    unknown = set(args) - allowed
    if unknown:
        raise ToolError(f"Unexpected argument(s) for {name}: {sorted(unknown)}. Allowed: {sorted(allowed)}.")
    try:
        result = tool.func(sequence, **args)
    except (ValueError, TypeError) as exc:  # the tools raise ValueError for bad input
        raise ToolError(str(exc)) from exc
    return {"sequence_id": seq_id, **result}

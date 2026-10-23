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

from . import tools
from .tools import SequenceError, parse_fasta


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
            tools.analyze_sequence,
            "Length, base counts and percentages, GC content (%), AT content (%) and reverse complement "
            "of a DNA or RNA sequence.",
            {},
        ),
        Tool(
            "transcribe_sequence",
            tools.transcribe_sequence,
            "Transcribe a DNA coding strand into mRNA (T becomes U).",
            {},
        ),
        Tool(
            "translate_sequence",
            tools.translate_sequence,
            "Translate one reading frame of DNA/RNA into a protein sequence using an NCBI codon table.",
            {
                "frame": {"type": "integer", "enum": [1, 2, 3], "description": "Reading frame, default 1."},
                "strand": {"type": "string", "enum": ["+", "-"], "description": "Strand, default '+'."},
                "table": {"type": "integer", "description": "NCBI genetic code ID, default 1 (standard)."},
                "to_stop": {"type": "boolean", "description": "Stop at the first stop codon, default false."},
            },
        ),
        Tool(
            "find_orfs",
            tools.find_orfs,
            "Find candidate open reading frames (ATG to stop codon) in all six frames, longest first.",
            {
                "min_protein_length": {
                    "type": "integer",
                    "description": "Minimum ORF length in amino acids, default 30.",
                },
                "table": {"type": "integer", "description": "NCBI genetic code ID, default 1."},
                "both_strands": {"type": "boolean", "description": "Search the reverse strand too, default true."},
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
    except SequenceError as exc:
        raise ToolError(str(exc)) from exc
    return {"sequence_id": seq_id, **result}

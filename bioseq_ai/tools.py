"""Deterministic bioinformatics tools used by the BioSeq AI agent.

Design rule: the language model plans and explains; these functions compute.
Every function takes plain strings/ints and returns a JSON-serializable dict,
so the same code works as an agent tool, a CLI command and a test target.

This module depends only on the Python standard library and Biopython, so it
can also be copied verbatim into the Agent Skill (see scripts/sync_skill.py).
"""

from __future__ import annotations

from Bio.Seq import Seq
from Bio.Data import CodonTable

__all__ = [
    "SequenceError",
    "parse_fasta",
    "clean_sequence",
    "analyze_sequence",
    "transcribe_sequence",
    "translate_sequence",
    "find_orfs",
]

DNA_ALPHABET = set("ACGTN")
RNA_ALPHABET = set("ACGUN")
# Long strings are truncated in tool output so a small model's context isn't flooded.
PREVIEW_LIMIT = 300


class SequenceError(ValueError):
    """Raised when input is not a valid nucleotide sequence."""


# --------------------------------------------------------------------------- #
# Input handling
# --------------------------------------------------------------------------- #
def parse_fasta(text: str) -> list[dict]:
    """Parse FASTA text (or a bare sequence) into [{"id", "description", "sequence"}].

    A bare sequence with no ">" header is returned as one record with id "seq1".
    Whitespace and digits (as in GenBank-style numbered lines) are removed.
    """
    if not text or not text.strip():
        raise SequenceError("No sequence provided.")
    records: list[dict] = []
    header = None
    chunks: list[str] = []

    def flush():
        if header is None and not chunks:
            return
        seq = "".join(chunks)
        hdr = header if header is not None else f"seq{len(records) + 1}"
        rid, _, desc = hdr.partition(" ")
        records.append({"id": rid or f"seq{len(records) + 1}", "description": desc.strip(), "sequence": seq})

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


def clean_sequence(sequence: str, allow_rna: bool = True) -> tuple[str, str]:
    """Return (uppercase sequence, molecule type) or raise SequenceError.

    Molecule type is "DNA" or "RNA". Error messages give 1-based positions so a
    researcher can find the bad character.
    """
    if sequence is None:
        raise SequenceError("No sequence provided.")
    if sequence.lstrip().startswith(">"):
        sequence = parse_fasta(sequence)[0]["sequence"]
    seq = "".join(sequence.split()).upper()
    if not seq:
        raise SequenceError("Sequence is empty.")
    has_u, has_t = "U" in seq, "T" in seq
    if has_u and has_t:
        raise SequenceError("Sequence contains both T and U; it cannot be both DNA and RNA.")
    if has_u and not allow_rna:
        raise SequenceError("This tool needs DNA (T, not U). The input looks like RNA.")
    alphabet = RNA_ALPHABET if has_u else DNA_ALPHABET
    bad = [(i + 1, ch) for i, ch in enumerate(seq) if ch not in alphabet]
    if bad:
        shown = ", ".join(f"'{c}' at position {p}" for p, c in bad[:5])
        more = f" (and {len(bad) - 5} more)" if len(bad) > 5 else ""
        raise SequenceError(
            f"Invalid nucleotide character(s): {shown}{more}. Allowed: {''.join(sorted(alphabet))}. "
            "Protein sequences are not supported by this tool."
        )
    return seq, ("RNA" if has_u else "DNA")


def _preview(s: str) -> dict:
    if len(s) <= PREVIEW_LIMIT:
        return {"value": s, "truncated": False}
    return {"value": s[:PREVIEW_LIMIT] + "...", "truncated": True, "full_length": len(s)}


def _table(table_id: int) -> CodonTable.CodonTable:
    try:
        return CodonTable.unambiguous_dna_by_id[int(table_id)]
    except (KeyError, ValueError, TypeError):
        valid = sorted(CodonTable.unambiguous_dna_by_id)
        raise SequenceError(f"Unknown NCBI codon table {table_id!r}. Valid tables: {valid}.")


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
def analyze_sequence(sequence: str) -> dict:
    """Length, nucleotide composition, GC/AT content and reverse complement."""
    seq, mol = clean_sequence(sequence)
    length = len(seq)
    bases = "ACGUN" if mol == "RNA" else "ACGTN"
    counts = {b: seq.count(b) for b in bases}
    # GC is computed over unambiguous bases only, so N's don't dilute it.
    unambiguous = length - counts["N"]
    gc = counts["G"] + counts["C"]
    gc_pct = round(100 * gc / unambiguous, 2) if unambiguous else 0.0
    at_pct = round(100 - gc_pct, 2) if unambiguous else 0.0
    rc = str(Seq(seq).reverse_complement_rna() if mol == "RNA" else Seq(seq).reverse_complement())
    return {
        "molecule_type": mol,
        "length": length,
        "base_counts": counts,
        "base_percentages": {b: round(100 * c / length, 2) for b, c in counts.items()},
        "gc_count": gc,
        "gc_content_percent": gc_pct,
        "at_content_percent" if mol == "DNA" else "au_content_percent": at_pct,
        "ambiguous_N_count": counts["N"],
        "reverse_complement": _preview(rc),
    }


def transcribe_sequence(sequence: str) -> dict:
    """Transcribe a DNA coding strand into mRNA (T -> U)."""
    seq, _ = clean_sequence(sequence, allow_rna=False)
    rna = str(Seq(seq).transcribe())
    return {
        "input_length": len(seq),
        "rna_length": len(rna),
        "rna": _preview(rna),
        "note": "Assumes the input is the coding (sense) strand, so mRNA equals the input with T replaced by U.",
    }


def translate_sequence(
    sequence: str, frame: int = 1, strand: str = "+", table: int = 1, to_stop: bool = False
) -> dict:
    """Translate one reading frame (1, 2 or 3) on the + or - strand into protein."""
    seq, mol = clean_sequence(sequence)
    try:
        frame = int(frame)
    except (TypeError, ValueError):
        raise SequenceError("frame must be 1, 2 or 3.")
    if frame not in (1, 2, 3):
        raise SequenceError("frame must be 1, 2 or 3.")
    if strand not in ("+", "-"):
        raise SequenceError("strand must be '+' or '-'.")
    codon_table = _table(table)
    s = Seq(seq.replace("U", "T"))
    if strand == "-":
        s = s.reverse_complement()
    sub = s[frame - 1 :]
    usable = len(sub) - len(sub) % 3
    trailing = len(sub) - usable
    protein = str(sub[:usable].translate(table=codon_table, to_stop=bool(to_stop)))
    return {
        "input_molecule_type": mol,
        "strand": strand,
        "frame": frame,
        "codon_table": {"id": codon_table.id, "name": ", ".join(codon_table.names[:1])},
        "codons_translated": usable // 3,
        "trailing_bases_ignored": trailing,
        "protein": _preview(protein),
        "protein_length": len(protein),
        "stop_codon_count": protein.count("*"),
        "starts_with_methionine": protein.startswith("M"),
        "note": "'*' marks a stop codon; 'X' marks a codon containing N.",
    }


def find_orfs(sequence: str, min_protein_length: int = 30, table: int = 1, both_strands: bool = True) -> dict:
    """Find ATG-initiated open reading frames that end in a stop codon.

    Scans 3 frames on the + strand (and 3 on the - strand by default). Nested
    ATGs inside an open ORF are not reported separately (longest ORF per stop).
    Coordinates are 1-based, inclusive, on the + strand, and include the stop codon.
    """
    seq, _ = clean_sequence(sequence)
    try:
        min_len = int(min_protein_length)
    except (TypeError, ValueError):
        raise SequenceError("min_protein_length must be an integer.")
    if min_len < 1:
        raise SequenceError("min_protein_length must be at least 1.")
    codon_table = _table(table)
    stops = set(codon_table.stop_codons)
    dna = seq.replace("U", "T")
    n = len(dna)
    strands = [("+", dna)]
    if both_strands:
        strands.append(("-", str(Seq(dna).reverse_complement())))

    orfs = []
    for strand, s in strands:
        for f in range(3):
            start = None
            for i in range(f, n - 2, 3):
                codon = s[i : i + 3]
                if start is None and codon == "ATG":
                    start = i
                elif start is not None and codon in stops:
                    end = i + 3  # exclusive, includes stop codon
                    aa_len = (end - start) // 3 - 1
                    if aa_len >= min_len:
                        protein = str(Seq(s[start:end]).translate(table=codon_table, to_stop=True))
                        if strand == "+":
                            g_start, g_end = start + 1, end
                        else:
                            g_start, g_end = n - end + 1, n - start
                        orfs.append({
                            "strand": strand,
                            "frame": f + 1,
                            "start": g_start,
                            "end": g_end,
                            "length_nt": end - start,
                            "protein_length_aa": aa_len,
                            "stop_codon": codon,
                            "protein": _preview(protein),
                        })
                    start = None
    orfs.sort(key=lambda o: (-o["length_nt"], o["start"]))
    for rank, o in enumerate(orfs, 1):
        o["rank"] = rank
    return {
        "sequence_length": n,
        "min_protein_length_aa": min_len,
        "strands_searched": [s for s, _ in strands],
        "orf_count": len(orfs),
        "longest_orf_aa": orfs[0]["protein_length_aa"] if orfs else 0,
        "orfs": orfs[:20],
        "orfs_truncated": len(orfs) > 20,
        "note": "Candidate ORFs only: an ORF is not evidence that a protein is expressed or functional.",
    }

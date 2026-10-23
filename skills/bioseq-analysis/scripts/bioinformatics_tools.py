"""BioSeq AI: validated DNA analysis tools for an open-weight AI agent.

Install the dependency with: pip install -r requirements.txt
Run the example with:
    python bioinformatics_tools.py --fasta examples/demo_construct.fasta --action all

Coordinates in find_orfs are 1-based and inclusive on the input DNA sequence.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from Bio import SeqIO
from Bio.Seq import Seq


VALID_DNA = set("ACGTN")
STOP_CODONS = {"TAA", "TAG", "TGA"}


def _normalize_dna(sequence: str) -> str:
    """Normalize a raw DNA string and reject invalid characters.

    Only A/C/G/T/N are supported; N denotes an unknown base. The sequence
    must not include a FASTA header (use read_fasta for FASTA files).
    """
    if not isinstance(sequence, str):
        raise ValueError("DNA sequence must be a string.")
    dna = "".join(sequence.split()).upper()
    if not dna:
        raise ValueError("DNA sequence cannot be empty.")
    invalid = sorted(set(dna) - VALID_DNA)
    if invalid:
        raise ValueError(
            f"Invalid DNA character(s): {', '.join(invalid)}. "
            "Only A, C, G, T, and N are accepted."
        )
    return dna


def read_fasta(path: str | Path) -> str:
    """Read exactly one DNA record from a FASTA file."""
    with open(path, encoding="utf-8") as handle:
        records = SeqIO.parse(handle, "fasta")
        first = next(records, None)
        if first is None:
            raise ValueError("FASTA file contains no sequences.")
        if next(records, None) is not None:
            raise ValueError("FASTA file must contain exactly one sequence.")
        return _normalize_dna(str(first.seq))


def analyze_sequence(sequence: str) -> dict:
    """Calculate DNA length, nucleotide counts, and GC percentage.

    N (unknown base) is excluded from the GC percentage denominator. If no
    A/C/G/T bases are present, gc_percent is None (unknown), not 0 percent.
    """
    dna = _normalize_dna(sequence)
    counts = Counter(dna)
    composition = {base: counts[base] for base in "ACGTN"}
    known_bases = len(dna) - counts["N"]
    gc_percent = (
        round(100 * (counts["G"] + counts["C"]) / known_bases, 2)
        if known_bases
        else None
    )
    return {
        "length": len(dna),
        "gc_percent": gc_percent,
        "gc_denominator": "non-N bases",
        "known_bases": known_bases,
        "nucleotide_composition": composition,
    }


def transcribe_sequence(sequence: str) -> str:
    """Transcribe the provided DNA coding strand (5'→3') to RNA (5'→3')."""
    dna = _normalize_dna(sequence)
    return dna.replace("T", "U")


def translate_sequence(
    sequence: str, frame: int = 1, *, to_stop: bool = False
) -> str:
    """Translate DNA in any of six reading frames using genetic code 1.

    frame +1, +2, +3: forward sequence starting at offsets 0, 1, 2.
    frame -1, -2, -3: reverse complement starting at offsets 0, 1, 2.
    Incomplete trailing codons are ignored. By default '*' marks stop codons.
    If to_stop=True, translation stops before the first stop codon.
    """
    if type(frame) is not int or frame not in (-3, -2, -1, 1, 2, 3):
        raise ValueError("frame must be one of +1, +2, +3, -1, -2, -3.")
    dna = _normalize_dna(sequence)
    oriented_dna = dna if frame > 0 else str(Seq(dna).reverse_complement())
    offset = abs(frame) - 1
    coding = oriented_dna[offset:]
    complete_codons_length = (len(coding) // 3) * 3
    if complete_codons_length == 0:
        return ""
    return str(
        Seq(coding[:complete_codons_length]).translate(table=1, to_stop=to_stop)
    )


def find_orfs(sequence: str, min_aa_length: int = 1) -> list[dict]:
    """Find complete ATG-to-stop ORFs in all six frames (genetic code 1).

    Reports every in-frame ATG followed by the next in-frame stop (TAA, TAG,
    TGA). Stop codons count toward nucleotide span but not protein length.
    Overlapping/nested starts generate separate candidates. Coordinates are
    1-based inclusive on the ORIGINAL input sequence, even on the - strand.
    Partial ORFs lacking either a start or stop codon are not returned.
    """
    if type(min_aa_length) is not int or min_aa_length < 1:
        raise ValueError("min_aa_length must be a positive integer.")
    dna = _normalize_dna(sequence)
    n = len(dna)
    orfs: list[dict] = []

    for strand, oriented in (("+", dna), ("-", str(Seq(dna).reverse_complement()))):
        for offset in range(3):
            starts: list[int] = []
            for pos in range(offset, n - 2, 3):
                codon = oriented[pos : pos + 3]
                if codon == "ATG":
                    starts.append(pos)
                if codon in STOP_CODONS:
                    stop_end = pos + 3  # exclusive in oriented sequence
                    for start in starts:
                        aa_length = (pos - start) // 3
                        if aa_length < min_aa_length:
                            continue
                        if strand == "+":
                            start_coord, end_coord = start + 1, stop_end
                        else:
                            start_coord, end_coord = n - stop_end + 1, n - start

                        coding_dna = oriented[start:pos]  # omit stop
                        orfs.append(
                            {
                                "strand": strand,
                                "frame": offset + 1 if strand == "+" else -(offset + 1),
                                "start": start_coord,
                                "end": end_coord,
                                "length_nt": stop_end - start,
                                "length_aa": aa_length,
                                "start_codon": "ATG",
                                "stop_codon": codon,
                                "protein_sequence": str(Seq(coding_dna).translate(table=1)),
                            }
                        )
                    starts.clear()

    return sorted(orfs, key=lambda orf: (orf["start"], orf["end"], orf["strand"]))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze a DNA sequence with four BioSeq AI bioinformatics tools."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--sequence", help="Raw DNA sequence (A/C/G/T/N).")
    source.add_argument("--fasta", type=Path, help="Path to a single-record FASTA file.")
    parser.add_argument(
        "--action", choices=("all", "analyze", "transcribe", "translate", "orfs"),
        default="all", help="Which analysis to run (default: all)."
    )
    parser.add_argument("--frame", type=int, default=1, help="Translation frame (+/-1,2,3).")
    parser.add_argument(
        "--min-orf-length", type=int, default=1, metavar="AA",
        help="Minimum ORF length in amino acids, excluding stop (default: 1)."
    )
    parser.add_argument("--to-stop", action="store_true", help="Stop translation at first stop codon.")
    args = parser.parse_args()
    try:
        dna = read_fasta(args.fasta) if args.fasta else _normalize_dna(args.sequence)
        result: dict = {"input_length": len(dna)}
        if args.action in ("all", "analyze"):
            result["analysis"] = analyze_sequence(dna)
        if args.action in ("all", "transcribe"):
            result["rna"] = transcribe_sequence(dna)
        if args.action in ("all", "translate"):
            result["translation"] = {
                "frame": args.frame,
                "protein": translate_sequence(dna, args.frame, to_stop=args.to_stop),
            }
        if args.action in ("all", "orfs"):
            result["orfs"] = find_orfs(dna, min_aa_length=args.min_orf_length)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Error: {exc}\n")


if __name__ == "__main__":
    main()

---
name: bioseq-analysis
description: Analyze DNA or RNA sequences with tested Biopython code instead of estimating. Computes length, base composition and GC content, transcribes DNA to mRNA, translates any reading frame with any NCBI codon table, and finds open reading frames on both strands. Use when a user gives a nucleotide sequence or FASTA file and asks about GC content, composition, reverse complement, transcription, translation, protein sequence, codons, reading frames or ORFs.
license: MIT
compatibility: Requires Python 3.10+ and Biopython (pip install biopython). No network access needed.
metadata:
  project: bioseq-ai
  version: "0.1.0"
---

# BioSeq analysis

Use the bundled script for every number. Do not count bases, compute GC
content, translate codons or locate ORFs yourself: language models make
arithmetic and copying mistakes on long sequences, and this script is tested.

## How to run

Put the sequence in a FASTA file (or pass a bare sequence with `--seq`), then:

```bash
python scripts/run.py analyze   input.fasta
python scripts/run.py transcribe input.fasta
python scripts/run.py translate input.fasta --frame 1 --strand + --table 1 [--to-stop]
python scripts/run.py orfs      input.fasta --min-aa 30 [--forward-only]
python scripts/run.py analyze --seq ATGAAATTTGGGTAA
```

Each command prints JSON with one result per FASTA record. If the input is
invalid, the script exits with code 1 and prints an `error` field naming the
bad character and its 1-based position; show that message to the user.

## Choosing commands

| User asks about | Command |
|---|---|
| length, GC/AT content, base counts, reverse complement | `analyze` |
| mRNA, transcription | `transcribe` |
| protein, amino acids, codons, a specific frame | `translate` |
| genes, ORFs, coding regions, "where could a protein start" | `orfs` |

Run several commands when the question covers several of these.

## Reporting results

1. Quote numbers exactly as the script printed them (you may round, but say so).
2. Give ORF coordinates as 1-based, inclusive positions on the + strand, with the strand.
3. Long sequences are truncated in output (`"truncated": true`); say so rather than inventing the rest.
4. Add the caution that an ORF is a candidate only, not evidence a protein is expressed,
   and that results are not a clinical or diagnostic interpretation.

See [references/interpretation.md](references/interpretation.md) for what typical
values mean and common pitfalls.

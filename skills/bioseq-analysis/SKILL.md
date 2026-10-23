---
name: bioseq-analysis
description: Analyze DNA sequences with tested Biopython code instead of estimating. Computes length, base composition and GC content, transcribes DNA to RNA, translates any of the six reading frames, and finds open reading frames on both strands. Use when a user gives a DNA sequence or FASTA file and asks about GC content, base composition, transcription, translation, protein sequence, codons, reading frames or ORFs.
license: MIT
compatibility: Requires Python 3.10+ and Biopython (pip install biopython). No network access needed. DNA only, standard genetic code.
metadata:
  project: bioseq-ai
  version: "0.1.0"
---

# BioSeq analysis

Use the bundled script for every number. Do not count bases, compute GC
content, translate codons or locate ORFs yourself: language models make
arithmetic and copying mistakes on long sequences, and this script is tested.

## How to run

The script takes one DNA sequence (A, C, G, T, N), either as a bare string or
as a FASTA file with exactly one record:

```bash
python scripts/bioinformatics_tools.py --fasta input.fasta --action all
python scripts/bioinformatics_tools.py --sequence ATGAAATTTGGGTAA --action analyze
python scripts/bioinformatics_tools.py --fasta input.fasta --action translate --frame -1 [--to-stop]
python scripts/bioinformatics_tools.py --fasta input.fasta --action orfs --min-orf-length 30
```

It prints JSON. If the input is invalid it exits with code 2 and prints
`Error: ...` naming the bad characters; show that message to the user. For a
FASTA file with several records, split it and run the script once per record.

## Choosing actions

| User asks about | `--action` |
|---|---|
| length, GC content, base counts | `analyze` |
| RNA, mRNA, transcription | `transcribe` |
| protein, amino acids, a specific frame (+1..+3, -1..-3) | `translate` |
| genes, ORFs, coding regions | `orfs` (use `--min-orf-length 30` or more on long sequences) |
| several of these | `all` |

## Reporting results

1. Quote numbers exactly as the script printed them (you may round, but say so). `gc_percent: null` means GC is unknown because every base was N.
2. Give ORF coordinates as 1-based, inclusive positions on the + strand, with the strand.
3. Every in-frame ATG is reported as its own ORF candidate, so nested ORFs share a stop codon; lead with the longest.
4. Add the caution that an ORF is a candidate only, not evidence a protein is expressed,
   and that results are not a clinical or diagnostic interpretation.

See [references/interpretation.md](references/interpretation.md) for what typical
values mean and common pitfalls.

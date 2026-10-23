# Interpreting BioSeq results

## GC content
- Computed over unambiguous bases only (N is excluded from the denominator).
- Genome-wide GC differs widely between organisms (roughly 20% to 75% in bacteria),
  so a value is only "high" or "low" relative to the organism in question.
- High-GC regions melt at higher temperatures and can be harder to amplify by PCR.

## Transcription
- The tool assumes the input is the coding (sense) strand, so RNA = input with T→U.
- If the user gives the template strand, the protein is in the negative frames (`--frame -1`, `-2`, `-3`).

## Translation
- `*` is a stop codon; `X` is a codon containing N.
- Frames +1 to +3 start at positions 1–3; frames -1 to -3 read the reverse complement.
- Only the standard genetic code (NCBI table 1) is supported; mitochondrial and other codes are not.

## ORFs
- Reported ORFs start at ATG and end at a stop codon. Every in-frame ATG before a stop is a
  separate candidate, so nested ORFs share an end coordinate.
- Coordinates are 1-based, inclusive, on the input sequence (even for - strand ORFs), and include the stop codon;
  `length_aa` and `protein_sequence` exclude the stop.
- Random DNA contains short ORFs by chance; long ORFs (e.g. >100 aa) are more notable,
  but an ORF alone is never proof that a protein is made.
- Coding sequences often contain overlapping ORFs on the opposite strand; these are
  usually not real genes.

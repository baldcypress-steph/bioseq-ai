# Interpreting BioSeq results

## GC content
- Computed over unambiguous bases only (N is excluded from the denominator).
- Genome-wide GC differs widely between organisms (roughly 20% to 75% in bacteria),
  so a value is only "high" or "low" relative to the organism in question.
- High-GC regions melt at higher temperatures and can be harder to amplify by PCR.

## Transcription
- The tool assumes the input is the coding (sense) strand, so mRNA = input with T→U.
- If the user gives the template strand, transcribe the reverse complement instead
  (use `translate --strand -` for proteins).

## Translation
- `*` is a stop codon; `X` is a codon containing N.
- Frames 1–3 start at positions 1–3. The `-` strand frames are read from the reverse complement.
- Use `--table` for non-standard codes, e.g. 2 = vertebrate mitochondrial, 11 = bacterial/plastid.

## ORFs
- Reported ORFs start at ATG and end at a stop codon; nested ATGs in the same frame
  are not listed separately (the longest ORF for each stop is kept).
- Coordinates are 1-based, inclusive, on the + strand, and include the stop codon.
- Random DNA contains short ORFs by chance; long ORFs (e.g. >100 aa) are more notable,
  but an ORF alone is never proof that a protein is made.
- Coding sequences often contain overlapping ORFs on the opposite strand; these are
  usually not real genes.

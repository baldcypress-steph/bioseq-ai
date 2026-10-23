"""Generate the synthetic example FASTA used in the demo and tests (seeded, reproducible).

The sequences are synthetic, not real genes, so every expected value can be
checked by hand or by an independent script. For a real record, see README.
"""
import random
from pathlib import Path

from Bio.Seq import Seq

rng = random.Random(42)
CODONS = [a + b + c for a in "ACGT" for b in "ACGT" for c in "ACGT"]
SENSE = [c for c in CODONS if c not in ("TAA", "TAG", "TGA")]


def noise(n):
    # Random flanking DNA with stop codons sprinkled in every frame so no long ORF arises by chance.
    s = "".join(rng.choice("ACGT") for _ in range(n))
    return "".join(ch if i % 7 else "T" for i, ch in enumerate(s))


def orf(n_codons):
    return "ATG" + "".join(rng.choice(SENSE) for _ in range(n_codons - 1)) + "TAA"


fwd = orf(60)            # 60 aa protein on + strand
rev = orf(40)            # 40 aa protein, placed on - strand
demo = noise(45) + fwd + noise(30) + str(Seq(rev).reverse_complement()) + noise(25)

out = Path(__file__).resolve().parents[1] / "examples"
out.mkdir(exist_ok=True)
(out / "demo_construct.fasta").write_text(
    ">demo_construct synthetic construct with one forward and one reverse-strand ORF\n"
    + "\n".join(demo[i:i + 70] for i in range(0, len(demo), 70)) + "\n"
)
(out / "sample.fasta").write_text(
    ">demo_construct synthetic construct with one forward and one reverse-strand ORF\n"
    + "\n".join(demo[i:i + 70] for i in range(0, len(demo), 70)) + "\n"
    ">toy short hand-checkable sequence\nATGAAATTTGGGTAA\n"
)
print(len(demo), "nt written to", out / "sample.fasta")

from pathlib import Path

import pytest
from Bio.Seq import Seq

from bioseq_ai.tools import (
    SequenceError,
    analyze_sequence,
    clean_sequence,
    find_orfs,
    parse_fasta,
    transcribe_sequence,
    translate_sequence,
)

TOY = "ATGAAATTTGGGTAA"  # hand-checked: A=6 T=5 G=4 C=0, GC=4/15, protein MKFG*
SAMPLE = (Path(__file__).parents[1] / "examples" / "sample.fasta").read_text()


# ---- parsing and validation ------------------------------------------------ #
def test_parse_fasta_multi_record_and_bare_sequence():
    recs = parse_fasta(SAMPLE)
    assert [r["id"] for r in recs] == ["demo_construct", "toy"]
    assert recs[1]["sequence"] == TOY
    assert parse_fasta("acgt\nACGT")[0] == {"id": "seq1", "description": "", "sequence": "acgtACGT"}


def test_parse_fasta_strips_genbank_numbering():
    assert parse_fasta("1 atgaaa ttt\n10 ggg taa")[0]["sequence"] == "atgaaatttgggtaa"


def test_invalid_character_reports_one_based_position():
    with pytest.raises(SequenceError, match="'X' at position 3"):
        clean_sequence("ACXGT")


def test_mixed_t_and_u_rejected():
    with pytest.raises(SequenceError, match="both T and U"):
        clean_sequence("ACGTU")


def test_protein_input_rejected():
    with pytest.raises(SequenceError):
        analyze_sequence("MKVLLE")


def test_empty_rejected():
    with pytest.raises(SequenceError):
        analyze_sequence("   ")


# ---- analyze --------------------------------------------------------------- #
def test_analyze_toy_matches_hand_count():
    r = analyze_sequence(TOY)
    assert r["length"] == 15
    assert r["base_counts"] == {"A": 6, "C": 0, "G": 4, "T": 5, "N": 0}
    assert r["gc_content_percent"] == round(400 / 15, 2) == 26.67
    assert r["at_content_percent"] == 73.33
    assert r["reverse_complement"]["value"] == "TTACCCAAATTTCAT"


def test_gc_ignores_ambiguous_bases():
    r = analyze_sequence("GGNNCC")
    assert r["gc_content_percent"] == 100.0
    assert r["ambiguous_N_count"] == 2


def test_analyze_rna():
    r = analyze_sequence("GGAUCC")
    assert r["molecule_type"] == "RNA"
    assert r["reverse_complement"]["value"] == "GGAUCC"
    assert "au_content_percent" in r


def test_long_output_is_truncated():
    r = analyze_sequence("A" * 1000)
    assert r["reverse_complement"]["truncated"] is True
    assert r["reverse_complement"]["full_length"] == 1000


# ---- transcribe ------------------------------------------------------------ #
def test_transcribe():
    r = transcribe_sequence(TOY)
    assert r["rna"]["value"] == "AUGAAAUUUGGGUAA"
    assert r["rna_length"] == 15


def test_transcribe_rejects_rna():
    with pytest.raises(SequenceError, match="looks like RNA"):
        transcribe_sequence("AUG")


# ---- translate ------------------------------------------------------------- #
def test_translate_frames():
    assert translate_sequence(TOY)["protein"]["value"] == "MKFG*"
    assert translate_sequence(TOY, to_stop=True)["protein"]["value"] == "MKFG"
    f2 = translate_sequence(TOY, frame=2)
    assert f2["codons_translated"] == 4 and f2["trailing_bases_ignored"] == 2
    # - strand frame 1 = translation of the reverse complement TTACCCAAATTTCAT
    assert translate_sequence(TOY, strand="-")["protein"]["value"] == str(Seq("TTACCCAAATTTCAT").translate())


def test_translate_rna_equals_dna():
    assert translate_sequence("AUGAAAUUUGGGUAA")["protein"] == translate_sequence(TOY)["protein"]


def test_translate_alternative_table():
    # TGA is Trp (W) in the vertebrate mitochondrial code (table 2), a stop in table 1.
    assert translate_sequence("ATGTGA")["protein"]["value"] == "M*"
    assert translate_sequence("ATGTGA", table=2)["protein"]["value"] == "MW"


@pytest.mark.parametrize("kwargs", [{"frame": 4}, {"strand": "x"}, {"table": 99}])
def test_translate_bad_arguments(kwargs):
    with pytest.raises(SequenceError):
        translate_sequence(TOY, **kwargs)


# ---- ORFs ------------------------------------------------------------------ #
def test_find_orfs_toy():
    r = find_orfs(TOY, min_protein_length=1)
    top = r["orfs"][0]
    assert (top["strand"], top["frame"], top["start"], top["end"]) == ("+", 1, 1, 15)
    assert top["protein"]["value"] == "MKFG" and top["protein_length_aa"] == 4


def test_find_orfs_reverse_strand_coordinates():
    # The toy ORF reverse-complemented must be found on the - strand with + strand coordinates.
    rc = str(Seq(TOY).reverse_complement())
    padded = "CC" + rc + "CC"
    top = find_orfs(padded, min_protein_length=1, both_strands=True)["orfs"][0]
    assert top["strand"] == "-"
    assert (top["start"], top["end"]) == (3, 17)
    assert str(Seq(padded[top["start"] - 1 : top["end"]]).reverse_complement()) == TOY


def test_find_orfs_on_sample_construct():
    demo = parse_fasta(SAMPLE)[0]["sequence"]
    r = find_orfs(demo, min_protein_length=30)
    found = {(o["strand"], o["protein_length_aa"]) for o in r["orfs"]}
    assert ("+", 60) in found and ("-", 40) in found
    for o in r["orfs"]:  # every reported ORF must re-translate to its own protein
        frag = demo[o["start"] - 1 : o["end"]]
        if o["strand"] == "-":
            frag = str(Seq(frag).reverse_complement())
        assert frag.startswith("ATG") and str(Seq(frag[-3:]).translate()) == "*"
        assert str(Seq(frag).translate(to_stop=True)) == o["protein"]["value"]


def test_find_orfs_respects_minimum_and_strand_option():
    assert find_orfs(TOY, min_protein_length=5)["orf_count"] == 0
    assert find_orfs(TOY, min_protein_length=1, both_strands=False)["strands_searched"] == ["+"]

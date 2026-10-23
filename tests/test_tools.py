"""Tests for bioseq_ai/bioinformatics_tools.py and the agent adapters around it."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from Bio.Seq import Seq

from bioseq_ai import bioinformatics_tools as bt
from bioseq_ai.registry import SequenceError, SequenceStore, ToolError, parse_fasta, run_tool

ROOT = Path(__file__).parents[1]
TOY = "ATGAAATTTGGGTAA"  # hand-checked: A=6 C=0 G=4 T=5, GC=4/15, protein MKFG*
SAMPLE = (ROOT / "examples" / "sample.fasta").read_text()
DEMO = parse_fasta(SAMPLE)[0]["sequence"]


# ---- validation ------------------------------------------------------------ #
@pytest.mark.parametrize("bad", ["ACXGT", "ACGU", "MKVLLE"])
def test_invalid_characters_rejected(bad):
    with pytest.raises(ValueError, match="Invalid DNA character"):
        bt.analyze_sequence(bad)


@pytest.mark.parametrize("empty", ["", "   \n"])
def test_empty_rejected(empty):
    with pytest.raises(ValueError, match="cannot be empty"):
        bt.analyze_sequence(empty)


def test_lowercase_and_whitespace_normalized():
    assert bt.analyze_sequence("atg aaa\nttt ggg taa") == bt.analyze_sequence(TOY)


# ---- analyze --------------------------------------------------------------- #
def test_analyze_toy_matches_hand_count():
    r = bt.analyze_sequence(TOY)
    assert r["length"] == 15
    assert r["nucleotide_composition"] == {"A": 6, "C": 0, "G": 4, "T": 5, "N": 0}
    assert r["gc_percent"] == round(400 / 15, 2) == 26.67


def test_gc_ignores_n_and_is_none_when_unknown():
    r = bt.analyze_sequence("GGNNCC")
    assert r["gc_percent"] == 100.0 and r["known_bases"] == 4
    assert bt.analyze_sequence("NNNN")["gc_percent"] is None


# ---- transcribe ------------------------------------------------------------ #
def test_transcribe():
    assert bt.transcribe_sequence(TOY) == "AUGAAAUUUGGGUAA"


# ---- translate ------------------------------------------------------------- #
def test_translate_forward_frames():
    assert bt.translate_sequence(TOY) == "MKFG*"
    assert bt.translate_sequence(TOY, to_stop=True) == "MKFG"
    assert bt.translate_sequence(TOY, 2) == str(Seq(TOY[1:13]).translate())


def test_translate_reverse_frames():
    rc = str(Seq(TOY).reverse_complement())
    assert bt.translate_sequence(TOY, -1) == str(Seq(rc[:15]).translate())
    assert bt.translate_sequence(TOY, -3) == str(Seq(rc[2:14]).translate())


def test_translate_short_sequence_returns_empty():
    assert bt.translate_sequence("AT") == ""


@pytest.mark.parametrize("frame", [0, 4, -4, "1", 1.0])
def test_translate_bad_frame(frame):
    with pytest.raises(ValueError, match="frame must be"):
        bt.translate_sequence(TOY, frame)


# ---- ORFs ------------------------------------------------------------------ #
def test_find_orfs_toy():
    (orf,) = bt.find_orfs(TOY)
    assert (orf["strand"], orf["frame"], orf["start"], orf["end"]) == ("+", 1, 1, 15)
    assert orf["protein_sequence"] == "MKFG" and orf["length_aa"] == 4 and orf["stop_codon"] == "TAA"


def test_find_orfs_reverse_strand_coordinates():
    padded = "CC" + str(Seq(TOY).reverse_complement()) + "CC"
    (orf,) = [o for o in bt.find_orfs(padded) if o["length_aa"] == 4]
    assert orf["strand"] == "-" and orf["frame"] < 0
    assert (orf["start"], orf["end"]) == (3, 17)
    assert str(Seq(padded[orf["start"] - 1 : orf["end"]]).reverse_complement()) == TOY


def test_nested_starts_are_separate_candidates():
    # ATG ATG AAA TAA: two in-frame starts share one stop.
    found = bt.find_orfs("ATGATGAAATAA")
    assert sorted(o["length_aa"] for o in found if o["strand"] == "+") == [2, 3]


def test_find_orfs_on_sample_construct():
    found = bt.find_orfs(DEMO, min_aa_length=30)
    lengths = {(o["strand"], o["length_aa"]) for o in found}
    assert ("+", 60) in lengths and ("-", 40) in lengths  # the two designed ORFs
    for o in found:  # every reported ORF re-translates to its own protein
        frag = DEMO[o["start"] - 1 : o["end"]]
        if o["strand"] == "-":
            frag = str(Seq(frag).reverse_complement())
        assert frag.startswith("ATG") and frag[-3:] in bt.STOP_CODONS
        assert str(Seq(frag[:-3]).translate()) == o["protein_sequence"]


@pytest.mark.parametrize("bad", [0, -1, "30", 2.5])
def test_find_orfs_bad_minimum(bad):
    with pytest.raises(ValueError, match="positive integer"):
        bt.find_orfs(TOY, min_aa_length=bad)


# ---- read_fasta and the script's own command line --------------------------- #
def test_read_fasta_single_record(tmp_path):
    assert bt.read_fasta(ROOT / "examples" / "demo_construct.fasta") == DEMO
    with pytest.raises(ValueError, match="exactly one"):
        bt.read_fasta(ROOT / "examples" / "sample.fasta")
    empty = tmp_path / "e.fa"
    empty.write_text("")
    with pytest.raises(ValueError, match="no sequences"):
        bt.read_fasta(empty)


def test_script_command_line():
    out = subprocess.run(
        [sys.executable, str(ROOT / "bioseq_ai" / "bioinformatics_tools.py"), "--sequence", TOY],
        capture_output=True, text=True, check=True).stdout
    r = json.loads(out)
    assert r["analysis"]["gc_percent"] == 26.67 and r["rna"] == "AUGAAAUUUGGGUAA"
    assert r["translation"]["protein"] == "MKFG*" and r["orfs"][0]["protein_sequence"] == "MKFG"


# ---- agent adapters (registry) --------------------------------------------- #
def test_parse_fasta_multi_record_bare_and_numbered():
    assert [r["id"] for r in parse_fasta(SAMPLE)] == ["demo_construct", "toy"]
    assert parse_fasta("acgt\nACGT")[0] == {"id": "seq1", "description": "", "sequence": "acgtACGT"}
    assert parse_fasta("1 atgaaa ttt\n10 ggg taa")[0]["sequence"] == "atgaaatttgggtaa"
    with pytest.raises(SequenceError):
        parse_fasta(">only_a_header\n")


def test_adapters_label_and_shorten_results():
    store = SequenceStore.from_text(SAMPLE)
    t = run_tool("translate_sequence", {"sequence_id": "toy", "frame": 1}, store)
    assert t["protein"] == {"value": "MKFG*", "truncated": False} and t["stop_codon_count"] == 1
    o = run_tool("find_orfs", {"sequence_id": "demo_construct"}, store)
    assert o["min_aa_length"] == 30 and o["longest_orf_aa"] == 60
    assert o["orfs_longest_first"][0]["start"] == 46 and o["orfs_longest_first"][0]["end"] == 228
    long = SequenceStore.from_text(">x\n" + "ACGT" * 200)
    r = run_tool("transcribe_sequence", {"sequence_id": "x"}, long)
    assert r["rna"]["truncated"] and r["rna"]["full_length"] == 800


def test_adapter_turns_tool_errors_into_messages_for_the_model():
    store = SequenceStore.from_text(">bad\nACXT")
    with pytest.raises(ToolError, match="Invalid DNA character"):
        run_tool("analyze_sequence", {"sequence_id": "bad"}, store)
    with pytest.raises(ToolError, match="frame must be"):
        run_tool("translate_sequence", {"sequence_id": "seq1", "frame": 9}, SequenceStore.from_text(TOY))

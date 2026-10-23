from bioseq_ai.faithfulness import check_answer

OUT = [{"gc_content_percent": 52.38, "length": 1234, "orfs": [{"start": 46, "end": 228, "protein": {"value": "MKFGAAVLLWERT"}}]}]


def test_rounding_to_stated_precision_is_supported():
    r = check_answer("GC is 52.4% (about 52%), length 1,234 nt, ORF 46-228.", OUT)
    assert r.passed and set(r.supported) == {"52.4", "52", "1,234", "46", "228"}


def test_wrong_rounding_and_invented_numbers_flagged():
    r = check_answer("GC is 52.5% and Tm is 70 C.", OUT)
    assert set(r.unsupported) == {"52.5", "70"}
    assert r.score == 0.0


def test_ids_and_trivial_integers_ignored():
    r = check_answer("In seq1 (NM_000207) frame 2 on strand 1 ...", OUT)
    assert r.checked == 0 and r.passed


def test_numbers_from_question_are_allowed():
    assert check_answer("ORFs of at least 75 aa: none.", OUT, question="min length 75").passed


def test_fraction_percentage_equivalence():
    assert check_answer("GC fraction 0.5238", OUT).passed


def test_invented_protein_sequence_flagged_but_quoted_one_ok():
    assert check_answer("Protein: `MKFGAAVLLWERT`", OUT).passed
    assert check_answer("Starts `MKFGAAVL...`", OUT).passed  # truncated quotes are fine
    r = check_answer("Protein: `MKFGAAVLLWEEE`", OUT)
    assert r.unsupported_sequences == ["MKFGAAVLLWEEE"]
    r = check_answer("Protein MKFGAAVLLWEEEKKKKRRRR here", OUT)  # long bare run
    assert r.unsupported_sequences == ["MKFGAAVLLWEEEKKKKRRRR"]


def test_ordinary_capitalised_words_are_not_sequences():
    assert check_answer("CHARACTERISTIC results.", OUT).passed

# 🧬 BioSeq AI

**An open-weight AI agent that turns plain-language questions into verified DNA/RNA sequence analyses.**

> "Analyze my sequence, calculate its GC content, translate it and find possible open reading frames."

BioSeq AI reads a question like that, decides which analyses are needed, runs them with tested
Biopython code, and explains the results. The open-weight model runs on your own computer through
[Ollama](https://ollama.com), so no sequence data leaves your machine.

Built for Hacktoberfest Toronto × HuskyHack 2026 (Best Open-Source AI Project track).

![tests](https://github.com/OWNER/bioseq-ai/actions/workflows/ci.yml/badge.svg)

---

## The problem

Routine sequence analysis still assumes you can write Python or use command-line tools, then
interpret raw output. Chatbots look like a shortcut, but language models are bad at exactly the
things sequence analysis needs: counting thousands of bases, copying long strings without errors,
and translating codons. Ask a chatbot for the GC content of a 400 bp sequence and you usually get
a confident, plausible and wrong number.

## How BioSeq AI solves it

**The model plans and explains. Tested tools compute. A checker verifies.**

```
 Your question ──► Open-weight LLM (Qwen3 via Ollama)
                     │  chooses tools, sets arguments
                     ▼
                   Tool registry (allowlist + argument validation)
                     │
                     ▼
                   Biopython tools ── analyze · transcribe · translate · find ORFs
                     │  exact results (JSON)
                     ▼
                   LLM writes the answer
                     │
                     ▼
                   Faithfulness checker ── every number and sequence in the answer
                     │                       must appear in a tool output
                     ▼
                   Answer + tool trace + replayable run manifest
```

What makes it more than a chatbot wrapper:

| Feature | Why it matters |
|---|---|
| **Sequence handles** | The model refers to sequences by ID (`seq1`) and never retypes DNA, so it cannot corrupt bases when calling a tool. |
| **Faithfulness checker** | Extracts every number and quoted sequence from the AI's answer and flags any that no tool produced. Hallucinated numbers are shown in the UI as warnings. |
| **Visible tool trace** | The app shows each tool the AI chose, with arguments and outputs, so you can see that the AI drove the analysis. |
| **Replayable runs** | Every run produces a manifest (question, input SHA-256, model, parameters, all tool calls and outputs). `bioseq replay` re-runs it and confirms identical results. |
| **Robust harness for small models** | Validates tool names and arguments, returns errors to the model so it can retry, recovers tool calls written as text, strips `<think>` blocks, and enforces a step limit. |
| **Backend-agnostic** | Any OpenAI-compatible endpoint: Ollama, llama.cpp, vLLM, LM Studio. |
| **Agent Skill** | The same tools packaged as an [Agent Skills](https://agentskills.io) skill, usable from any compatible agent. |
| **Benchmark** | 15 tasks scoring tool choice, facts in the answer and faithfulness, comparing open-weight models with a no-LLM baseline. |

## Tools

| Tool | What it computes |
|---|---|
| `analyze_sequence` | Length, base counts and percentages, GC and AT content (N excluded), reverse complement |
| `transcribe_sequence` | DNA coding strand → mRNA |
| `translate_sequence` | Any frame (1–3) on either strand, any NCBI genetic code, optional stop at first stop codon |
| `find_orfs` | ATG→stop open reading frames in all six frames, 1-based + strand coordinates, minimum length |

Inputs are validated: invalid characters are reported with their 1-based position, mixed T/U input
is rejected, and FASTA files with several records or GenBank-style numbering are handled.

---

## Quick start (macOS, Linux, Windows)

**1. Install**

```bash
git clone https://github.com/OWNER/bioseq-ai.git
cd bioseq-ai
python3 -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

**2. Get an open-weight model** (one time; about 2.5 GB)

Install [Ollama](https://ollama.com/download), then:

```bash
ollama pull qwen3:4b
```

Qwen3 is released under the Apache 2.0 license. Any tool-calling model works, e.g. `llama3.2:3b`
or `qwen3:8b` if you have 16 GB+ RAM. Set it with `--model` or `BIOSEQ_MODEL`.

**3. Run the app**

```bash
streamlit run app.py
```

Paste or upload a FASTA file, pick an example question, and press **Run analysis**.

**Or use the command line**

```bash
bioseq ask examples/sample.fasta "What is the GC content of demo_construct, and does it contain an ORF?" --save run.json
bioseq replay run.json examples/sample.fasta
bioseq ask examples/sample.fasta "Find ORFs" --tools-only     # no LLM needed
```

**Tests**

```bash
pytest -q
```

The agent loop is tested with a scripted fake model, so tests run without an LLM.

---

## Example data

`examples/sample.fasta` holds two synthetic sequences (generated by `scripts/make_examples.py`
with a fixed seed) so every answer can be checked by hand:

| Sequence | Known values |
|---|---|
| `toy` (15 nt) | A=6, C=0, G=4, T=5 · GC 26.67% · protein `MKFG*` |
| `demo_construct` (406 nt) | GC 51.97% · designed 60 aa ORF on + strand at 46–228 · designed 40 aa ORF on − strand at 259–381 |

The ORF finder also reports a few shorter ORFs on the − strand. These arise by chance on the
opposite strand of a coding sequence, which is a useful reminder that an ORF is only a candidate.

**Try a real gene:** download the FASTA for human insulin mRNA
([NM_000207](https://www.ncbi.nlm.nih.gov/nuccore/NM_000207)) and ask
*"Find the longest ORF and translate it."* The longest ORF should encode the 110-amino-acid
preproinsulin ([UniProt P01308](https://www.uniprot.org/uniprotkb/P01308)).

---

## Benchmark

```bash
python benchmark/run_benchmark.py --models qwen3:4b llama3.2:3b
```

Writes `benchmark/results.md`. Metrics: **tool recall** (needed tools were called), **extra
tools**, **failed calls**, **facts in answer** (expected values present), **faithful answers**
(no unsupported numbers), and time per task. The keyword baseline shows what is possible without
an LLM; the agent should beat it on plain-language questions and on answer quality.

<!-- Paste benchmark/results.md here after running it. -->

---

## Agent Skill

`skills/bioseq-analysis/` follows the Agent Skills open standard (`SKILL.md` with YAML front
matter, plus `scripts/` and `references/`). Copy the folder into your agent's skills directory.
The script needs only Python and Biopython:

```bash
python skills/bioseq-analysis/scripts/run.py orfs examples/sample.fasta --min-aa 30
```

`scripts/bioseq_tools.py` is a copy of `bioseq_ai/tools.py`; `python scripts/sync_skill.py`
updates it and a test fails if the two drift apart.

## Project layout

```
bioseq-ai/
├── app.py                     Streamlit interface
├── bioseq_ai/
│   ├── tools.py               Biopython analysis tools (the only place numbers are computed)
│   ├── registry.py            Tool allowlist, JSON schemas, sequence store, argument validation
│   ├── llm.py                 OpenAI-compatible client for open-weight models
│   ├── agent.py               Agent loop, tools-only baseline, run manifest, replay
│   ├── faithfulness.py        Checks the answer's numbers/sequences against tool outputs
│   └── cli.py                 `bioseq ask` and `bioseq replay`
├── skills/bioseq-analysis/    Agent Skill package
├── benchmark/                 Tasks and benchmark runner
├── examples/sample.fasta
└── tests/                     45 tests (tools, agent loop, model client, faithfulness, skill)
```

## Limitations

- Nucleotide sequences only; protein analysis tools are future work.
- ORFs are ATG-initiated only and are candidates, not gene predictions.
- The faithfulness checker verifies numbers and quoted sequences, not the correctness of the
  model's prose interpretation.
- Small models sometimes skip a needed tool; the trace and benchmark make this visible.
- Research and education use only. Not for clinical or diagnostic decisions.

## Roadmap

- BLAST, UniProt and NCBI lookups with cached, cited accession IDs
- Protein properties (molecular weight, pI) and motif search
- Hosted demo on Hugging Face Spaces in tools-only mode

## License

MIT, see [LICENSE](LICENSE).

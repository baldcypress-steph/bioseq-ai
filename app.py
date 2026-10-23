"""BioSeq AI – Streamlit demo.   Run:  streamlit run app.py"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from bioseq_ai.agent import Agent, run_tools_only
from bioseq_ai.llm import LLMConfig, OpenAICompatibleLLM
from bioseq_ai.registry import SequenceError, SequenceStore

st.set_page_config(page_title="BioSeq AI", page_icon="🧬", layout="wide")
SAMPLE = (Path(__file__).parent / "examples" / "sample.fasta").read_text()
EXAMPLES = [
    "What is the GC content and length of each sequence?",
    "Analyze demo_construct: GC content, transcribe it, and find open reading frames of at least 30 amino acids.",
    "Translate toy in frames 1, 2 and 3. Which frame gives a protein that starts with M?",
    "Find the longest ORF in demo_construct and give me its protein sequence.",
]

# ---------------------------------------------------------------- sidebar --- #
with st.sidebar:
    st.header("Model")
    mode = st.radio("Mode", ["Agent (open-weight LLM)", "Tools-only (no LLM)"],
                    index=1 if os.getenv("BIOSEQ_TOOLS_ONLY") else 0,
                    help="Tools-only uses a keyword planner instead of a model. Useful on CPU-only hosts.")
    cfg = LLMConfig()
    cfg.model = st.text_input("Model", cfg.model, help="Any tool-calling model served by your backend.")
    cfg.base_url = st.text_input("OpenAI-compatible endpoint", cfg.base_url)
    max_steps = st.slider("Max agent steps", 1, 10, 6)
    st.caption("Default: Qwen3 4B via Ollama on this computer. Nothing leaves your machine.")
    st.divider()
    st.caption("Research and education tool. Not for clinical or diagnostic use.")

# ------------------------------------------------------------------- main --- #
st.title("🧬 BioSeq AI")
st.write("Ask a question in plain language. An open-weight model chooses the analyses, "
         "tested Biopython tools compute every number, and a checker confirms the answer only uses those numbers.")

c1, c2 = st.columns([3, 2])
with c1:
    upload = st.file_uploader("FASTA file", type=["fa", "fasta", "fna", "txt"])
    fasta = upload.read().decode("utf-8", "replace") if upload else st.text_area("…or paste FASTA", SAMPLE, height=160)
with c2:
    try:
        store = SequenceStore.from_text(fasta)
        st.write("**Loaded sequences**")
        st.dataframe(pd.DataFrame(store.summary()), hide_index=True, width="stretch")
    except SequenceError as exc:
        st.error(str(exc))
        st.stop()

pick = st.selectbox("Example questions", ["(write my own)"] + EXAMPLES)
question = st.text_input("Your question", "" if pick == "(write my own)" else pick)

if st.button("Run analysis", type="primary", disabled=not question.strip()):
    with st.status("Running…", expanded=True) as status:
        try:
            if mode.startswith("Tools"):
                res = run_tools_only(question, fasta)
            else:
                st.write(f"The first request can take a minute while {cfg.model} loads into memory.")
                res = Agent(OpenAICompatibleLLM(cfg), max_steps=max_steps).run(question, fasta, on_event=st.write)
            status.update(label=f"Done in {res.seconds}s", state="complete", expanded=False)
        except Exception as exc:
            status.update(label="Failed", state="error")
            st.error(f"Problem talking to the model at {cfg.base_url}: {exc}\n\n"
                     f"If it timed out, your computer may be too slow for {cfg.model}: try a smaller model "
                     "such as `qwen3:1.7b` (`ollama pull qwen3:1.7b`), or switch to Tools-only mode. "
                     f"If it could not connect, open the Ollama app and check `ollama pull {cfg.model}` finished.")
            st.stop()
    st.session_state["res"] = res

res = st.session_state.get("res")
if res:
    f = res.faithfulness
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Tool calls", len(res.trace))
    m2.metric("Failed calls", sum(not t.ok for t in res.trace))
    m3.metric("Numbers verified", f"{len(f['supported'])}/{f['numbers_checked']}")
    m4.metric("Time", f"{res.seconds}s")

    st.subheader("Answer")
    st.markdown(res.answer)
    if f["passed"]:
        st.success(f"Faithfulness check passed: every number in the answer ({f['numbers_checked']}) "
                   "matches a tool output.")
    else:
        bad = ", ".join(f["unsupported"] + f["unsupported_sequences"])
        st.warning(f"Faithfulness check: these values in the answer do NOT appear in any tool output: **{bad}**. "
                   "Treat them as unreliable.")

    st.subheader("What the AI did")
    st.caption(f"Model: {res.model} · mode: {res.mode} · stop reason: {res.stopped_reason}")
    for t in res.trace:
        icon = "✅" if t.ok else "⚠️"
        with st.expander(f"{icon} Step {t.step}: `{t.tool}({json.dumps(t.arguments)})`"):
            if t.ok:
                if t.tool == "find_orfs" and t.output["orfs_longest_first"]:
                    st.dataframe(pd.DataFrame([{**o, "protein_sequence": o["protein_sequence"]["value"]}
                                               for o in t.output["orfs_longest_first"]]),
                                 hide_index=True, width="stretch")
                st.json(t.output, expanded=False)
            else:
                st.error(t.error)

    st.download_button("Download run manifest (JSON)", json.dumps(res.manifest, indent=2),
                       file_name="bioseq_run.json", mime="application/json",
                       help="Question, input hash, model, every tool call and output. Replay with `bioseq replay`.")

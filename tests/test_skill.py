"""The Agent Skill must follow the spec and run the same tested code as the package."""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
SKILL = ROOT / "skills" / "bioseq-analysis"


def frontmatter():
    text = (SKILL / "SKILL.md").read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, "SKILL.md must start with YAML front matter"
    fields = dict(re.findall(r"^([a-z-]+):\s*(.*)$", m.group(1), re.MULTILINE))
    return fields, text


def test_frontmatter_follows_agent_skills_spec():
    f, text = frontmatter()
    name = f["name"]
    assert name == SKILL.name
    assert 1 <= len(name) <= 64 and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name)
    assert 1 <= len(f["description"]) <= 1024
    assert len(f.get("compatibility", "")) <= 500
    assert len(text.splitlines()) < 500


def test_vendored_tools_identical_to_package():
    assert (SKILL / "scripts" / "bioinformatics_tools.py").read_text() == \
        (ROOT / "bioseq_ai" / "bioinformatics_tools.py").read_text(), "Run: python scripts/sync_skill.py"


def run(*args):
    p = subprocess.run([sys.executable, str(SKILL / "scripts" / "bioinformatics_tools.py"), *args],
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def test_skill_script_runs():
    code, out, _ = run("--sequence", "ATGAAATTTGGGTAA", "--action", "analyze")
    assert code == 0 and json.loads(out)["analysis"]["gc_percent"] == 26.67
    code, out, _ = run("--fasta", str(ROOT / "examples" / "demo_construct.fasta"), "--action", "orfs",
                       "--min-orf-length", "30")
    assert code == 0 and max(o["length_aa"] for o in json.loads(out)["orfs"]) == 60


def test_skill_script_reports_errors():
    code, _, err = run("--sequence", "ACXT")
    assert code == 2 and "Invalid DNA character(s): X" in err


def test_skill_md_commands_match_script_options():
    _, text = frontmatter()
    for flag in re.findall(r"(?<![-\w])(--[a-z][a-z-]*)", text):
        assert flag in (SKILL / "scripts" / "bioinformatics_tools.py").read_text(), flag

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
    assert (SKILL / "scripts" / "bioseq_tools.py").read_text() == (ROOT / "bioseq_ai" / "tools.py").read_text(), \
        "Run: python scripts/sync_skill.py"


def run(*args):
    p = subprocess.run([sys.executable, str(SKILL / "scripts" / "run.py"), *args], capture_output=True, text=True)
    return p.returncode, json.loads(p.stdout)


def test_skill_script_runs():
    code, out = run("analyze", "--seq", "ATGAAATTTGGGTAA")
    assert code == 0 and out["results"][0]["gc_content_percent"] == 26.67
    code, out = run("orfs", str(ROOT / "examples" / "sample.fasta"))
    assert code == 0 and out["results"][0]["orfs"][0]["protein_length_aa"] == 60


def test_skill_script_reports_errors_as_json():
    code, out = run("analyze", "--seq", "ACXT")
    assert code == 1 and "position 3" in out["error"]

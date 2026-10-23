"""Copy bioseq_ai/bioinformatics_tools.py into the Agent Skill so the skill is self-contained.

Run after changing bioinformatics_tools.py. tests/test_skill.py fails if the copies differ.
"""
import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[1]
src = root / "bioseq_ai" / "bioinformatics_tools.py"
dst = root / "skills" / "bioseq-analysis" / "scripts" / "bioinformatics_tools.py"
shutil.copyfile(src, dst)
print("synced", dst)

"""Copy bioseq_ai/tools.py into the Agent Skill so the skill is self-contained.

Run after changing tools.py. tests/test_skill.py fails if the copies differ.
"""
import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[1]
dst = root / "skills" / "bioseq-analysis" / "scripts" / "bioseq_tools.py"
shutil.copyfile(root / "bioseq_ai" / "tools.py", dst)
print("synced", dst)

"""Faithfulness check: is every number and sequence in the answer backed by a tool?

Language models are fluent at inventing plausible numbers. This check extracts
every number (and every long protein/nucleotide string) from the model's final
answer and confirms it appears in the tool outputs or in the user's question.
A number counts as supported if it equals a tool value after rounding to the
precision the answer used, e.g. "52.4%" is supported by a tool value of 52.38.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# A number not glued to letters/underscores (so "seq1" or "NM_000207" are ignored).
_NUMBER = re.compile(r"(?<![A-Za-z0-9_.])(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)(?![A-Za-z0-9_])")
# Sequence claims: 8+ sequence letters inside `backticks`, or a bare run of 20+.
# (Shorter bare runs could be all-caps English words such as "CHARACTERISTIC".)
_SEQ_RUN = re.compile(r"`([ACDEFGHIKLMNPQRSTVWYUX*]{8,})(?:\.\.\.)?`|\b([ACDEFGHIKLMNPQRSTVWYUX*]{20,})\b")
# Small integers used in ordinary prose ("one of 3 frames", "step 2") are not flagged.
_TRIVIAL = {0, 1, 2, 3, 6}


@dataclass
class FaithfulnessReport:
    supported: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    unsupported_sequences: list[str] = field(default_factory=list)

    @property
    def checked(self) -> int:
        return len(self.supported) + len(self.unsupported)

    @property
    def passed(self) -> bool:
        return not self.unsupported and not self.unsupported_sequences

    @property
    def score(self) -> float:
        return 1.0 if self.checked == 0 else round(len(self.supported) / self.checked, 3)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "score": self.score,
            "numbers_checked": self.checked,
            "supported": self.supported,
            "unsupported": self.unsupported,
            "unsupported_sequences": self.unsupported_sequences,
        }


def _collect(obj, numbers: list[float], strings: list[str]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        numbers.append(float(obj))
    elif isinstance(obj, str):
        strings.append(obj.upper().replace("...", ""))
        for m in _NUMBER.finditer(obj):
            numbers.append(float(m.group(1).replace(",", "")))
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect(v, numbers, strings)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect(v, numbers, strings)


def _decimals(token: str) -> int:
    return len(token.split(".")[1]) if "." in token else 0


def _matches(value: float, decimals: int, candidates: list[float]) -> bool:
    tol = 0.5 * 10 ** (-decimals) + 1e-9
    return any(abs(c - value) <= tol for c in candidates)


def check_answer(answer: str, tool_outputs: list[dict], question: str = "") -> FaithfulnessReport:
    numbers: list[float] = []
    strings: list[str] = []
    _collect(tool_outputs, numbers, strings)
    for m in _NUMBER.finditer(question or ""):
        numbers.append(float(m.group(1).replace(",", "")))
    # Percentages may be stated as fractions or vice versa; accept both scales.
    candidates = numbers + [n * 100 for n in numbers if 0 < abs(n) <= 1] + [n / 100 for n in numbers]

    report = FaithfulnessReport()
    seen = set()
    for m in _NUMBER.finditer(answer or ""):
        token = m.group(1)
        if token in seen:
            continue
        seen.add(token)
        value = float(token.replace(",", ""))
        if value in _TRIVIAL and "." not in token:
            continue
        (report.supported if _matches(value, _decimals(token), candidates) else report.unsupported).append(token)

    haystack = " ".join(strings) + " " + (question or "").upper()
    # Case-sensitive on purpose: tools print sequences in uppercase, prose words are not.
    for m in _SEQ_RUN.finditer(answer or ""):
        claim = m.group(1) or m.group(2)
        frag = claim.rstrip("*")
        if frag and frag not in haystack:
            report.unsupported_sequences.append(claim)
    return report

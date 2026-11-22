"""Detectors for PII and secrets in strings.

Structured identifiers are checked with their checksums (Luhn for cards, Verhoeff for
Aadhaar) so random digit runs are not flagged.
shortcut: pattern + checksum detectors only; add Presidio/spaCy when free-text names
and addresses must be caught.
"""

import re
from collections.abc import Callable

SECRET_TYPES = frozenset(
    {
        "PRIVATE_KEY",
        "AWS_ACCESS_KEY",
        "GITHUB_TOKEN",
        "SLACK_TOKEN",
        "JWT",
        "API_KEY",
        "SECRET_FIELD",
    }
)

# Field names whose string values are treated as secrets, whatever they look like.
SECRET_FIELD_NAME = re.compile(
    r"pass(word|wd)?|secret|token|api[_-]?key|private[_-]?key|credential", re.IGNORECASE
)


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


_V_MUL = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]  # fmt: skip
_V_PERM = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]  # fmt: skip


def _verhoeff(digits: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _V_MUL[c][_V_PERM[i % 8][int(ch)]]
    return c == 0


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


# (entity type, pattern, optional validator of the matched text)
_DETECTORS: list[tuple[str, re.Pattern[str], Callable[[str], bool] | None]] = [
    (
        "PRIVATE_KEY",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(-----END [A-Z ]*PRIVATE KEY-----|$)"
        ),
        None,
    ),
    ("AWS_ACCESS_KEY", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"), None),
    ("GITHUB_TOKEN", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), None),
    ("SLACK_TOKEN", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), None),
    ("JWT", re.compile(r"\beyJ[\w-]{5,}\.eyJ[\w-]{5,}\.[\w-]{5,}"), None),
    # OpenAI/Anthropic style sk-..., Stripe sk_live_..., AgentGuard's own ag_... keys.
    ("API_KEY", re.compile(r"\b(sk-[\w-]{16,}|sk_(live|test)_\w{16,}|ag_[\w-]{40,})"), None),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"), None),
    (
        "CREDIT_CARD",
        re.compile(r"\b\d(?:[ -]?\d){12,18}\b"),
        lambda m: 13 <= len(_digits(m)) <= 19 and _luhn(_digits(m)),
    ),
    (
        "IN_AADHAAR",
        re.compile(r"\b[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}\b"),
        lambda m: _verhoeff(_digits(m)),
    ),
    ("IN_PAN", re.compile(r"\b[A-Z]{3}[ABCFGHJLPT][A-Z]\d{4}[A-Z]\b"), None),
    (
        "PHONE",
        re.compile(r"(?<![\w+])\+?\d[\d -]{8,15}\d\b"),
        lambda m: 10 <= len(_digits(m)) <= 13,
    ),
]


def find(text: str) -> list[tuple[str, int, int]]:
    """Return (entity_type, start, end) for non-overlapping matches, sorted by position.

    Where matches overlap, the detector listed first wins.
    """
    found: list[tuple[str, int, int]] = []
    for entity, pattern, valid in _DETECTORS:
        for m in pattern.finditer(text):
            s, e = m.span()
            if any(s < fe and fs < e for _, fs, fe in found):
                continue
            if valid and not valid(m.group()):
                continue
            found.append((entity, s, e))
    return sorted(found, key=lambda f: f[1])

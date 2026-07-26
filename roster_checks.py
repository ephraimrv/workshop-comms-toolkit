"""Shared roster-validation helpers for the certificate toolkit.

Used by both ``generate_certificates.py`` and ``rollup_attendance.py`` so the
two tools apply exactly the same rules to names and emails, rather than each
maintaining its own copy that could quietly drift apart.

Examples
--------
Check a field for common domain typos::

    >>> likely_domain_typo("cathnajorda@gmail.con")
    'gmail.com'
    >>> likely_domain_typo("felix@example.com") is None
    True
"""

from __future__ import annotations

import unicodedata

# Domains seen in real MMSU BSP workshop rosters. Extend as new legitimate
# domains show up; a domain not on this list is simply never flagged, so
# adding to it can only reduce false positives, never cause new ones.
KNOWN_GOOD_DOMAINS = frozenset(
    {
        "gmail.com",
        "yahoo.com",
        "outlook.com",
        "hotmail.com",
        "mmsu.edu.ph",
        "mymail.mmsu.edu.ph",
    }
)


def clean_name(raw: str) -> str:
    """Strip surrounding whitespace and normalise to NFC. Case untouched."""
    return unicodedata.normalize("NFC", raw.strip())


def _damerau_leq1(a: str, b: str) -> bool:
    """True if a and b are equal or one edit apart (insert/delete/substitute/
    adjacent transposition). Transposition matters here specifically because
    it is the most common domain typo shape (gmial, hotmial) and plain
    Levenshtein distance counts a transposition as two edits, missing it.
    """
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    m, n = len(a), len(b)
    d = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        d[i][0] = i
    for j in range(n + 1):
        d[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[m][n] <= 1


def likely_domain_typo(email: str) -> str | None:
    """Return the probable intended domain if email's domain is one edit
    away from a known-good domain, else None. Never auto-corrects -- this
    is for flagging to a human, not silently rewriting someone's address.
    """
    if "@" not in email:
        return None
    domain = email.strip().lower().rsplit("@", 1)[-1]
    if domain in KNOWN_GOOD_DOMAINS:
        return None
    for good in KNOWN_GOOD_DOMAINS:
        if _damerau_leq1(domain, good):
            return good
    return None


def structurally_valid_email(email: str) -> bool:
    """Cheap structural check: exactly one '@', no whitespace. Does not
    check deliverability and does not catch typos -- see likely_domain_typo
    for that.
    """
    e = email.strip()
    return (
        e.count("@") == 1
        and " " not in e
        and not e.startswith("@")
        and not e.endswith("@")
    )

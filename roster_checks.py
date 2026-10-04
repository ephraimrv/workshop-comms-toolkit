"""Shared roster-validation helpers for the certificate toolkit.

Used by ``generate_cert.py``, ``rollup_attendance.py``, ``new_registrants.py``
and ``mail_merge.py`` so every tool applies exactly the same rules to names
and emails, rather than each maintaining its own copy that could quietly
drift apart.

Examples
--------
Check a field for common domain typos::

    >>> likely_domain_typo("participant@gmail.con")
    'gmail.com'
    >>> likely_domain_typo("felix@example.com") is None
    True

Real providers one edit from a known domain must not be flagged::

    >>> likely_domain_typo("participant@ymail.com") is None
    True
    >>> likely_domain_typo("participant@mail.com") is None
    True
    >>> likely_domain_typo("participant@email.com") is None
    True

Structure is checked separately from typos::

    >>> structurally_valid_email("participant@example.com")
    True
    >>> [structurally_valid_email(e) for e in
    ...  ["x@y", "a@b..com", "a@.com", "a@com.", "a\tb@c.com", "@b.com", "a@"]]
    [False, False, False, False, False, False, False]
"""

from __future__ import annotations

import unicodedata

# Domains seen in real workshop rosters, plus real providers that sit one
# edit away from one of them (ymail.com and mail.com are one edit from
# gmail.com, and email.com is one edit from ymail.com and mail.com; each
# would otherwise be flagged as a typo). A domain on this list
# is never flagged itself; adding one also starts flagging addresses one
# edit away from it, so add only domains participants actually use.
KNOWN_GOOD_DOMAINS = frozenset(
    {
        "gmail.com",
        "yahoo.com",
        "outlook.com",
        "hotmail.com",
        "mmsu.edu.ph",
        "mymail.mmsu.edu.ph",
        "ustp.edu.ph",
        "ymail.com",
        "mail.com",
        "email.com",
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
    """Return True if email has the shape of a deliverable address.

    Requires exactly one '@', a non-empty local part, no whitespace, and a
    domain of at least two non-empty dot-separated labels. Does not check
    deliverability and does not catch typos -- see likely_domain_typo.
    """
    e = email.strip()
    if e.count("@") != 1 or any(ch.isspace() for ch in e):
        return False
    local, domain = e.split("@")
    labels = domain.split(".")
    return bool(local) and len(labels) >= 2 and all(labels)

"""Roll up per-session attendance records into one row per person with a tier.

Reads a CSV/TSV where each row is one person's sign-in for one session
(the same email may appear on multiple rows -- once per session attended,
sometimes more than once if someone signs in twice by mistake). Emits one
row per DISTINCT person with a derived tier, ready for
``generate_certificates.py``: columns ``name``, ``email``, ``tier``,
plus ``sessions_attended`` for a human to audit the result.

This tool does not know what a "workshop" is beyond a count of sessions.
Sessions-required-for-participation, and which column holds the session
number, are flags, so a 5-day workshop or a differently-shaped export
does not need this file edited.

Deriving tier
-------------
For each email (case-folded, whitespace-stripped), the set of DISTINCT
session values it appears under is counted -- a set, not a row count, so
signing in twice for the same session (a real trap found in testing)
does not inflate the count. If that count is >= --sessions-for-participation,
tier is "participation", else "attendance".

Which name wins
----------------
The same person may type their name slightly differently across sessions
(case, spacing). This tool keeps the name from that person's MOST RECENT
row by timestamp, on the assumption a later submission is more likely to
be a correction than an earlier one. This is a judgement call, not a
provable rule -- override by pre-editing the source file if a different
row's spelling should win for a specific person.

What gets flagged instead of silently resolved
------------------------------------------------
* A missing email on a row -- that attendance cannot be attributed to
  anyone, so the whole run refuses rather than silently dropping it.
* A structurally broken email (no ``@``, multiple ``@``, embedded spaces).
* An email whose domain is one edit away from a known-good domain
  (``gmail.con`` -> ``gmail.com``, ``gmial.com`` -> ``gmail.com``) --
  refused, not auto-corrected; only a human can confirm the real address.
* Two different email addresses sharing an identical name string -- almost
  certainly worth a look (a typo'd address for one returning person, or
  two genuinely different people with the same name), but NOT refused,
  since either explanation is plausible and only a human can tell which.

Examples
--------
Roll up a single accumulating export where every row already carries an
explicit session number::

    python rollup_attendance.py sim_attendance.csv \\
        --name-col "Full Name" --email-col "Email" \\
        --timestamp-col Timestamp --session-col session \\
        --out cert_roster.csv

Roll up an export that has no session column at all (e.g. today's
Session-1-only eval export) by supplying the session for the whole file::

    python rollup_attendance.py session1_only.csv \\
        --name-col "Full name (as you wish it to appear on your certificate)" \\
        --email-col "Email address  " --timestamp-col Timestamp \\
        --default-session 1 --out cert_roster.csv

Hand the result straight to the certificate generator::

    python generate_certificates.py cert_roster.csv \\
        --serial-prefix BSP-2026-W1 \\
        --template-attendance templates/ATTENDANCE.pdf \\
        --template-participation templates/PARTICIPATION.pdf
"""

from __future__ import annotations

__author__ = "Jan Ephraim R. Vallente"
__version__ = "0.1.0"

import csv
import sys
from argparse import ArgumentParser
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from roster_checks import clean_name, likely_domain_typo, structurally_valid_email

TIER_PARTICIPATION = "participation"
TIER_ATTENDANCE = "attendance"

# Timestamp formats seen in practice (Google Forms' own export format first).
_TIMESTAMP_FORMATS = ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S")


def parse_timestamp(raw: str):
    """Best-effort timestamp parse. Returns None, not a guess, on failure --
    sort-stability for same-day rows matters less than never inventing a time.
    """
    raw = raw.strip()
    for fmt in _TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def parse_args(argv: list[str] | None = None):
    p = ArgumentParser(
        description=(
            __doc__ or "Roll up attendance into a certificate roster."
        ).splitlines()[0]
    )
    p.add_argument("source", type=Path, help="CSV/TSV of per-session sign-ins.")
    p.add_argument("--name-col", required=True)
    p.add_argument("--email-col", required=True)
    p.add_argument("--timestamp-col", required=True)
    p.add_argument(
        "--session-col",
        default="session",
        help="Column holding each row's session number (default: session).",
    )
    p.add_argument(
        "--default-session",
        type=int,
        default=None,
        help=(
            "Session number to apply to every row when --session-col is "
            "not present in the file's header at all (e.g. a Session-1-"
            "only export with no session field yet)."
        ),
    )
    p.add_argument("--sessions-for-participation", type=int, default=3)
    p.add_argument("--out", type=Path, default=Path("cert_roster.csv"))
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.source.exists():
        print(f"error: source not found: {args.source}", file=sys.stderr)
        return 2

    delimiter = "\t" if args.source.suffix.lower() in {".tsv", ".tab"} else ","
    with args.source.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        headers = [h.strip() for h in (reader.fieldnames or [])]
        raw_rows = [
            {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            for row in reader
        ]

    for col in (args.name_col, args.email_col, args.timestamp_col):
        if col not in headers:
            print(
                f"error: column {col!r} not found; available: {headers}",
                file=sys.stderr,
            )
            return 2

    session_col_present = args.session_col in headers
    if not session_col_present and args.default_session is None:
        print(
            f"error: column {args.session_col!r} not found, and no "
            f"--default-session given to apply to the whole file.",
            file=sys.stderr,
        )
        return 2

    problems: list[str] = []
    sessions_by_email: dict[str, set[str]] = defaultdict(set)
    latest_name_by_email: dict[str, tuple] = {}  # email -> (timestamp_or_None, name)
    name_variants_by_normalised_name: dict[str, set[str]] = defaultdict(set)

    for lineno, row in enumerate(raw_rows, start=2):
        raw_email = row.get(args.email_col, "")
        raw_name = row.get(args.name_col, "")
        raw_ts = row.get(args.timestamp_col, "")
        raw_session = (
            row.get(args.session_col, "")
            if session_col_present
            else str(args.default_session)
        )

        if not raw_email:
            problems.append(f"line {lineno}: missing email (name={raw_name!r})")
            continue
        if not structurally_valid_email(raw_email):
            problems.append(f"line {lineno}: malformed email {raw_email!r}")
            continue
        typo_suggestion = likely_domain_typo(raw_email)
        if typo_suggestion:
            problems.append(
                f"line {lineno}: {raw_email!r} looks like a typo of "
                f"...@{typo_suggestion} -- fix in the source, not here"
            )
            continue
        if not raw_name.strip():
            problems.append(f"line {lineno}: empty name (email={raw_email!r})")
            continue
        session_str = raw_session.strip()
        if not session_str.lstrip("-").isdigit():
            problems.append(
                f"line {lineno}: session {raw_session!r} is not a whole number"
            )
            continue

        email = raw_email.strip().lower()
        name = clean_name(raw_name)
        sessions_by_email[email].add(session_str)
        name_variants_by_normalised_name[name.lower()].add(email)

        ts = parse_timestamp(raw_ts)
        prev = latest_name_by_email.get(email)
        if prev is None or (ts is not None and (prev[0] is None or ts >= prev[0])):
            latest_name_by_email[email] = (ts, name)

    if problems:
        print("error: source has problems; nothing generated:", file=sys.stderr)
        for pr in problems:
            print(f"  {pr}", file=sys.stderr)
        return 1
    if not sessions_by_email:
        print("error: no valid rows found", file=sys.stderr)
        return 1

    # Same name string under different emails: flag, don't block. Either a
    # typo'd address for one returning person, or two different people who
    # share a name -- only a human can tell which.
    for norm_name, emails in name_variants_by_normalised_name.items():
        if len(emails) > 1:
            print(
                f"warning: name {norm_name!r} appears under {len(emails)} "
                f"different emails: {sorted(emails)} -- verify manually",
                file=sys.stderr,
            )

    out_rows = []
    for email in sorted(sessions_by_email):  # deterministic order downstream
        n_sessions = len(sessions_by_email[email])
        tier = (
            TIER_PARTICIPATION
            if n_sessions >= args.sessions_for_participation
            else TIER_ATTENDANCE
        )
        out_rows.append(
            {
                "name": latest_name_by_email[email][1],
                "email": email,
                "tier": tier,
                "sessions_attended": n_sessions,
            }
        )

    with args.out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["name", "email", "tier", "sessions_attended"]
        )
        writer.writeheader()
        writer.writerows(out_rows)

    n_participation = sum(1 for r in out_rows if r["tier"] == TIER_PARTICIPATION)
    print(f"rolled up {len(out_rows)} distinct people from {len(raw_rows)} rows")
    print(f"  participation: {n_participation}")
    print(f"  attendance   : {len(out_rows) - n_participation}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

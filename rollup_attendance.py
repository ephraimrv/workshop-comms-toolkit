"""Roll up an accumulating eval/attendance export into one row per person.

Reads a single CSV/TSV that grows over the course of a workshop -- a
Google Form linked to a Sheet and downloaded as CSV, where the same
email reappears each time that person submits, once per session they
respond for. There is no session column; session membership is derived
from each row's submission timestamp (see Deriving session below).
Emits one row per DISTINCT person with a derived tier, ready for
``generate_cert.py``: columns ``name``, ``email``, ``tier``,
``sessions_attended`` (the count, for a human to audit the result),
and ``sessions`` (the distinct session numbers themselves, sorted and
semicolon-joined, which generate_cert.py reads to issue one attendance
certificate per session attended).

This tool does not know what a "workshop" is beyond a count of
sessions. The session date ranges and the number of sessions required
for participation are flags, so a differently-shaped workshop needs no
edit to this file.

Deriving session
----------------
Each row is assigned to a session by which ``--session-window`` its
timestamp falls inside. A window is an inclusive date range, one per
session. This dates a response by WHEN IT WAS SUBMITTED, which is a
proxy for which session the person attended: someone who attended
session 1 but submitted the form after session 2's window opened is
bucketed into session 2. This tool cannot detect that on its own --
the derived roster is a first pass to be reconciled against the master
attendance sheet, not a substitute for it.

Deriving tier
-------------
For each email (case-folded, whitespace-stripped), the number of
DISTINCT sessions it appears in is counted -- a set, not a row count,
so submitting twice within the same session's window does not inflate
the count. If that count is >= ``--sessions-for-participation``, tier
is "participation", else "attendance".

Which name wins
----------------
The same person may type their name slightly differently across
sessions (case, spacing). This tool keeps the name from that person's
MOST RECENT row by timestamp, on the assumption a later submission is
more likely to be a correction than an earlier one. This is a
judgement call, not a provable rule -- override by pre-editing the
source file if a different row's spelling should win for someone.

What gets flagged instead of silently resolved
------------------------------------------------
* A missing email on a row -- that attendance cannot be attributed to
  anyone, so the whole run refuses rather than silently dropping it.
* A structurally broken email (no ``@``, multiple ``@``, embedded
  spaces).
* An email whose domain is one edit away from a known-good domain
  (``gmail.con`` -> ``gmail.com``, ``gmial.com`` -> ``gmail.com``) --
  refused, not auto-corrected; only a human can confirm the real
  address.
* A timestamp that cannot be parsed, or that falls inside no
  ``--session-window`` -- reported, so an off-by-a-day window boundary
  surfaces rather than silently discarding a response.
* Two different email addresses sharing an identical name string --
  almost certainly worth a look (a typo'd address for one returning
  person, or two genuinely different people with the same name), but
  NOT refused, since either explanation is plausible and only a human
  can tell which.

Examples
--------
Roll up the accumulating export for a three-session workshop, dating
each response by the window its timestamp falls in::

    python rollup_attendance.py eval.csv \\
        --name-col "Full name" \\
        --email-col "Email address" \\
        --timestamp-col Timestamp \\
        --session-window 1 2026-07-23 2026-07-29 \\
        --session-window 2 2026-07-30 2026-08-05 \\
        --session-window 3 2026-08-06 2026-08-31 \\
        --out cert_roster.csv

Run mid-workshop with only session 1's window: everyone rolls up as
"attendance" (one session so far). Rerun with more windows as the
export grows and later sessions land::

    python rollup_attendance.py eval.csv \\
        --name-col "Full name" --email-col "Email address" \\
        --timestamp-col Timestamp \\
        --session-window 1 2026-07-23 2026-07-29 \\
        --out cert_roster.csv

Hand the result straight to the certificate generator::

    python generate_cert.py cert_roster.csv \\
        --serial-prefix BSP-2026-W1 \\
        --template-attendance templates/ATTENDANCE.pdf \\
        --template-participation templates/PARTICIPATION.pdf
"""

from __future__ import annotations

__author__ = "Jan Ephraim R. Vallente"
__version__ = "0.1.0"

import csv
import sys
from argparse import ArgumentParser, ArgumentTypeError, RawDescriptionHelpFormatter
from collections import defaultdict
from datetime import date, datetime
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


def parse_date(raw: str) -> date:
    """argparse type= for window dates: accept an ISO date (YYYY-MM-DD)."""
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ArgumentTypeError(f"{raw!r} is not an ISO date (YYYY-MM-DD)")


def parse_args(argv: list[str] | None = None):
    p = ArgumentParser(
        description=(
            __doc__ or "Roll up attendance into a certificate roster."
        ).splitlines()[0],
        formatter_class=RawDescriptionHelpFormatter,
        epilog=(
            "Session is derived from each row's timestamp, not a column: the\n"
            "source is one accumulating Google Forms export with no session\n"
            "field. Give one --session-window per session, and each response\n"
            "is assigned to the window its timestamp falls inside.\n\n"
            "Example (three-session workshop):\n"
            "  python rollup_attendance.py eval.csv \\\n"
            '      --name-col "Full name (as you wish it to appear on your '
            'certificate)" \\\n'
            '      --email-col "Email address" \\\n'
            "      --timestamp-col Timestamp \\\n"
            "      --session-window 1 2026-07-23 2026-07-29 \\\n"
            "      --session-window 2 2026-07-30 2026-08-05 \\\n"
            "      --session-window 3 2026-08-06 2026-08-31 \\\n"
            "      --out cert_roster.csv"
        ),
    )
    p.add_argument(
        "source",
        type=Path,
        metavar="SOURCE",
        help="The accumulating Google Forms export (CSV or TSV).",
    )
    p.add_argument(
        "--name-col",
        required=True,
        metavar="HEADER",
        help="Exact header of the column holding each person's full name.",
    )
    p.add_argument(
        "--email-col",
        required=True,
        metavar="HEADER",
        help="Exact header of the column holding each person's email address.",
    )
    p.add_argument(
        "--timestamp-col",
        required=True,
        metavar="HEADER",
        help=(
            "Exact header of the submission-timestamp column (Google Forms "
            "calls this 'Timestamp'). Used to assign each row to a session."
        ),
    )
    p.add_argument(
        "--session-window",
        action="append",
        required=True,
        nargs=3,
        metavar=("N", "START", "END"),
        help=(
            "Define one session as a date range: session N covers responses "
            "timestamped between START and END inclusive, both ISO dates "
            "(YYYY-MM-DD). Repeat once per session. A response whose date "
            "falls in no window is reported as an error, not silently dropped."
        ),
    )
    p.add_argument(
        "--sessions-for-participation",
        type=int,
        default=3,
        metavar="N",
        help=(
            "Attend at least N distinct sessions to earn a Participation "
            "certificate; fewer earns Attendance (default: 3)."
        ),
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("cert_roster.csv"),
        metavar="PATH",
        help="Where to write the rolled-up roster (default: cert_roster.csv).",
    )
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

    # Build session windows from the repeated --session-window flag. Each is
    # (N, START, END); validate the shape here so a bad flag fails before any
    # row is read.
    windows: list[tuple[int, date, date]] = []
    for n_str, start_str, end_str in args.session_window:
        if not n_str.lstrip("-").isdigit():
            print(f"error: session number {n_str!r} is not an integer", file=sys.stderr)
            return 2
        try:
            start, end = parse_date(start_str), parse_date(end_str)
        except ArgumentTypeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if start > end:
            print(
                f"error: session {n_str} window start {start} is after end {end}",
                file=sys.stderr,
            )
            return 2
        windows.append((int(n_str), start, end))

    def session_for(when: date) -> int | None:
        for n, start, end in windows:
            if start <= when <= end:
                return n
        return None

    problems: list[str] = []
    sessions_by_email: dict[str, set[int]] = defaultdict(set)
    latest_name_by_email: dict[str, tuple[datetime | None, str]] = (
        {}
    )  # email -> (timestamp_or_None, name)
    name_variants_by_normalised_name: dict[str, set[str]] = defaultdict(set)

    for lineno, row in enumerate(raw_rows, start=2):
        raw_email = row.get(args.email_col, "")
        raw_name = row.get(args.name_col, "")
        raw_ts = row.get(args.timestamp_col, "")

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

        ts = parse_timestamp(raw_ts)
        if ts is None:
            problems.append(f"line {lineno}: unparseable timestamp {raw_ts!r}")
            continue
        session = session_for(ts.date())
        if session is None:
            problems.append(
                f"line {lineno}: timestamp {raw_ts!r} falls in no "
                f"--session-window; extend a window or add one"
            )
            continue

        email = raw_email.strip().lower()
        name = clean_name(raw_name)
        sessions_by_email[email].add(session)
        name_variants_by_normalised_name[name.lower()].add(email)

        prev = latest_name_by_email.get(email)
        if prev is None or prev[0] is None or ts >= prev[0]:
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
                # The distinct session numbers themselves, sorted and
                # semicolon-joined, so generate_cert.py can issue one attendance
                # certificate PER session. sessions_attended is the count of
                # this set and stays for human audit; downstream reads this.
                "sessions": ";".join(str(s) for s in sorted(sessions_by_email[email])),
            }
        )

    with args.out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["name", "email", "tier", "sessions_attended", "sessions"],
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

"""List form registrants not yet sent a campaign; add them to a roster.

Reads the registration form's CSV export, removes everyone already
recorded in the given sent logs or exclusion files, and reports who is
left. With ``--write`` it appends those people to a roster that
``mail_merge.py`` can send from. Rerunning after the form has grown
picks up only the newcomers, so one campaign can be resent batch by
batch with the same body and the same sent log.

This file holds no participant data. Everything personal is read at run
time from files passed on the command line, which live in the event
folder, outside the repository.

What counts as already sent
---------------------------
An address appears in a ``--sent-log`` or an ``--exclude`` file, one
bare address per line, compared case-insensitively. Blank lines and
text after ``#`` are ignored. Any other line stops the run: a log in a
different format would match nobody, and everyone in it would be
treated as not yet sent. For the same reason ``--write`` is refused
while any sent log shares no address with the form.

Which row wins
--------------
The form export is chronological, so when one address registered more
than once, the later row's name is kept.

What gets flagged instead of silently resolved
----------------------------------------------
Names are written as the registrant typed them (surrounding whitespace
stripped, Unicode normalised), as in ``generate_cert.py``. Names in
capitals, with a comma, with a lower-case word or with repeated spaces
are flagged for a human to correct in the roster. So are addresses
outside ``--domain`` and addresses one edit from a known domain. A
structurally broken address is flagged and blocks ``--write``.

Example
-------
Run from the event folder, first to report, then to write::

    python ../../workshop-comms-toolkit/new_registrants.py \\
        --form "Event Registration Responses - Form Responses 1.csv" \\
        --sent-log logs/install-phase1-2026-09-24.log \\
                   install-phase1-v2-2026-09-25.sent.log \\
        --exclude exclusions.txt \\
        --template rosters/install-phase1-v2-2026-09-25.csv \\
        --roster rosters/install-phase1-v3-2026-09-25.csv
"""

from __future__ import annotations

__author__ = "Jan Ephraim R. Vallente"
__version__ = "0.1.0"

import csv
import sys
from argparse import ArgumentParser, Namespace, RawDescriptionHelpFormatter
from pathlib import Path

from roster_checks import (clean_name, likely_domain_typo,
                           structurally_valid_email)

CONTACT_PREFIX = "contact_"


class InputError(Exception):
    """An input file is missing or malformed; nothing is written."""


def parse_args(argv: list[str] | None = None) -> Namespace:
    """Parse the command line."""
    parser = ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else None,
        epilog=__doc__,
        formatter_class=RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--form", type=Path, required=True,
        help="registration form responses exported as CSV")
    parser.add_argument(
        "--sent-log", type=Path, nargs="+", required=True,
        help="sent logs of the earlier runs of this campaign")
    parser.add_argument(
        "--exclude", type=Path, nargs="*", default=[],
        help="files of further addresses to skip")
    parser.add_argument(
        "--template", type=Path, required=True,
        help="an earlier roster: supplies the header and contact_* values")
    parser.add_argument(
        "--roster", type=Path, required=True,
        help="roster to create or append to")
    parser.add_argument(
        "--domain", default="ustp.edu.ph",
        help="expected address domain; others are flagged "
             "(default: %(default)s)")
    parser.add_argument("--email-col", default="Email Address")
    parser.add_argument("--name-col", default="Full Name")
    parser.add_argument("--time-col", default="Timestamp")
    parser.add_argument(
        "--write", action="store_true",
        help="append to --roster (default: report only)")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def read_addresses(path: Path) -> set[str]:
    """Return the addresses in a one-address-per-line file, lower-cased.

    Raises InputError on a missing file or on any line that is not a
    single bare address.
    """
    if not path.is_file():
        raise InputError(f"not found: {path}")
    found: set[str] = set()
    text = path.read_text(encoding="utf-8-sig")
    for number, raw in enumerate(text.splitlines(), start=1):
        entry = raw.split("#", 1)[0].strip()
        if not entry:
            continue
        if not structurally_valid_email(entry) or "," in entry:
            raise InputError(f"{path} line {number} is not a bare address")
        found.add(entry.lower())
    return found


def read_form(path: Path, email_col: str, name_col: str,
              time_col: str) -> list[tuple[str, str]]:
    """Return (email, name) per address in form order; later rows win.

    Rows with an empty timestamp are the blank rows Sheets leaves in
    an export and are skipped.
    """
    if not path.is_file():
        raise InputError(f"not found: {path}")
    latest: dict[str, tuple[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        wanted = (email_col, name_col, time_col)
        missing = [c for c in wanted if c not in (reader.fieldnames or [])]
        if missing:
            raise InputError(f"{path} has no column(s) {missing}")
        for row in reader:
            if not (row[time_col] or "").strip():
                continue
            email = (row[email_col] or "").strip()
            name = clean_name(row[name_col] or "")
            latest[email.lower()] = (email, name)
    return list(latest.values())


def read_template(path: Path) -> tuple[list[str], dict[str, str]]:
    """Return the template roster's header and its contact_* values.

    The address must be the first column and there must be a ``name``
    column; any other column must be a contact_* column shared by every
    recipient, since this tool cannot fill per-person data.
    """
    if not path.is_file():
        raise InputError(f"not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        first = next(reader, None)
    if first is None or "name" not in header:
        raise InputError(f"{path} needs a 'name' column and one data row")
    if not structurally_valid_email(first[header[0]] or ""):
        raise InputError(f"{path}: first column is not an address")
    others = [c for c in header[1:] if c != "name"]
    unfillable = [c for c in others if not c.startswith(CONTACT_PREFIX)]
    if unfillable:
        raise InputError(
            f"{path} has per-person columns this tool cannot fill: "
            f"{unfillable}")
    return header, {c: first[c] for c in others}


def read_roster_addresses(path: Path, email_col: str) -> set[str]:
    """Return the lower-cased addresses already in a roster, if any."""
    if not path.exists():
        return set()
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {
            (row[email_col] or "").strip().lower()
            for row in csv.DictReader(f)
            if (row[email_col] or "").strip()
        }


def name_flags(name: str) -> list[str]:
    """Return reasons a name may need correcting by hand.

    >>> name_flags("OCTAVIO, RENAN P.")
    ['all capitals', 'comma (surname first?)']
    >>> name_flags("Rudy M. camay")
    ['lower-case word']
    >>> name_flags("Dhayan   L. Allego")
    ['repeated spaces']
    >>> name_flags("Ma. Katrina C. Tion")
    []
    """
    flags = []
    if name.isupper():
        flags.append("all capitals")
    if "," in name:
        flags.append("comma (surname first?)")
    words = name.replace("-", " ").split()
    if any(word[:1].islower() for word in words):
        flags.append("lower-case word")
    if "  " in name:
        flags.append("repeated spaces")
    return flags


def email_flags(email: str, domain: str) -> list[str]:
    """Return reasons an address may need checking before sending.

    >>> email_flags("someone@gmail.con", "ustp.edu.ph")
    ['not @ustp.edu.ph', 'typo for gmail.com?']
    >>> email_flags("someone@ustp.edu.ph", "ustp.edu.ph")
    []
    """
    if not structurally_valid_email(email):
        return ["not a valid address"]
    flags = []
    if not email.lower().endswith("@" + domain.lower()):
        flags.append(f"not @{domain}")
    suggestion = likely_domain_typo(email)
    if suggestion:
        flags.append(f"typo for {suggestion}?")
    return flags


def append_rows(path: Path, header: list[str], contacts: dict[str, str],
                people: list[tuple[str, str]]) -> bool:
    """Append people to the roster; return True if it was created."""
    creating = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
        if creating:
            writer.writeheader()
        for email, name in people:
            writer.writerow({header[0]: email, "name": name, **contacts})
    return creating


def main(argv: list[str] | None = None) -> int:
    """Report new registrants, and append them with --write.

    Returns 0 on success, 1 when writing is refused, 2 on bad input.
    """
    args = parse_args(argv)
    try:
        header, contacts = read_template(args.template)
        form = read_form(args.form, args.email_col, args.name_col,
                         args.time_col)
        logs = {path: read_addresses(path) for path in args.sent_log}
        excluded: set[str] = set()
        for path in args.exclude:
            excluded |= read_addresses(path)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    on_form = {email.lower() for email, _ in form}
    unmatched = [path for path, addrs in logs.items() if not addrs & on_form]
    for path in unmatched:
        print(f"warning: no address in {path} is on the form; "
              "is it the right log?", file=sys.stderr)

    done = excluded.union(*logs.values())
    queued = read_roster_addresses(args.roster, header[0]) - done
    skip = done | queued
    new = [(e, n) for e, n in form if e.lower() not in skip]

    print(f"form: {len(form)} addresses | sent or excluded: "
          f"{len(on_form & done)} | in roster, not yet sent: "
          f"{len(on_form & queued)} | new: {len(new)}")
    for email, name in new:
        flags = name_flags(name) + email_flags(email, args.domain)
        print(f"  {email:40} {name:32} {'; '.join(flags)}")

    if not new:
        return 0
    if not args.write:
        print("report only: rerun with --write to append")
        return 0
    if unmatched:
        print("error: not writing while a sent log matches nobody",
              file=sys.stderr)
        return 1
    broken = [e for e, _ in new if not structurally_valid_email(e)]
    if broken:
        print(f"error: not writing invalid address(es): {broken}",
              file=sys.stderr)
        return 1
    created = append_rows(args.roster, header, contacts, new)
    print(f"{'created' if created else 'appended to'} {args.roster}: "
          f"{len(new)} row(s); correct flagged names there before sending")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

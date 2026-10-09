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
than once, the later row is kept. An edited response keeps its place
and carries its edited answers.

How each roster column is filled
--------------------------------
The template roster's header decides the columns, in its order:

- the first column: the registrant's address;
- ``name``: the full name, or with ``--greeting first`` the first given
  name ("Ma." keeps the word after it);
- ``certificate_name``, if present: the full name;
- ``contact_*``: copied from the template's first data row;
- any column named in the ``--lookup`` file: looked up by the
  registrant's answer in ``--lookup-col``.

A lookup file is a CSV whose first column is the key. A form answer
matches a key exactly, or by its text before the first colon, so the key
``Day 1`` matches the answer ``Day 1: Monday, 12 October``. Any other
template column stops the run, since this tool has nothing to fill it
with.

What gets flagged instead of silently resolved
----------------------------------------------
Names are written as the registrant typed them (surrounding whitespace
stripped, Unicode normalised), as in ``generate_cert.py``. Names in
capitals, with a comma, with a lower-case word, with repeated spaces or
with an initial lacking its full stop are flagged for a human to correct
in the roster. So are addresses
outside ``--domain`` and addresses one edit from a known domain. A
structurally broken address, or an answer that matches no lookup key,
is flagged and blocks ``--write``.

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

With per-person columns filled from the form and a lookup file::

    python ../../workshop-comms-toolkit/new_registrants.py \\
        --form "Event Registration Responses - Form Responses 1.csv" \\
        --sent-log logs/<earlier campaign>.sent.log \\
        --exclude exclusions.txt \\
        --template rosters/<earlier roster>.csv \\
        --roster rosters/<new roster>.csv \\
        --greeting first \\
        --lookup day_lookup.csv \\
        --lookup-col "Which day would you prefer to attend?"
"""

from __future__ import annotations

__author__ = "Jan Ephraim R. Vallente"
__version__ = "0.2.0"

import csv
import sys
from argparse import ArgumentParser, Namespace, RawDescriptionHelpFormatter
from dataclasses import dataclass
from pathlib import Path

from roster_checks import (clean_name, likely_domain_typo,
                           structurally_valid_email)

CONTACT_PREFIX = "contact_"
FULL_NAME_COL = "certificate_name"
GIVEN_NAME_PREFIXES = {"ma", "ma."}


class InputError(Exception):
    """An input file is missing or malformed; nothing is written."""


@dataclass(frozen=True)
class Registrant:
    """One address's latest row on the form."""

    email: str
    name: str
    answer: str


@dataclass(frozen=True)
class Lookup:
    """Values keyed by a form answer, from a --lookup file."""

    columns: list[str]
    rows: dict[str, dict[str, str]]

    def key_for(self, answer: str) -> str | None:
        """Return the key an answer matches, or None.

        >>> table = Lookup(["venue"], {"Day 1": {"venue": "AVR"}})
        >>> table.key_for("Day 1: Monday, 12 October")
        'Day 1'
        >>> table.key_for("Day 1")
        'Day 1'
        >>> table.key_for("Day 10: Thursday") is None
        True
        >>> table.key_for("") is None
        True
        """
        answer = answer.strip()
        if answer in self.rows:
            return answer
        head = answer.split(":", 1)[0].strip()
        return head if ":" in answer and head in self.rows else None


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
        "--greeting", choices=("full", "first"), default="full",
        help="fill 'name' with the full name or the first given name "
             "(default: %(default)s)")
    parser.add_argument(
        "--lookup", type=Path,
        help="CSV keyed by a form answer; fills the template columns "
             "it names")
    parser.add_argument(
        "--lookup-col",
        help="form column whose answer is looked up (required with "
             "--lookup)")
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
    args = parser.parse_args(argv)
    if (args.lookup is None) != (args.lookup_col is None):
        parser.error("--lookup and --lookup-col go together")
    return args


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


def read_form(path: Path, email_col: str, name_col: str, time_col: str,
              answer_col: str | None = None) -> list[Registrant]:
    """Return one Registrant per address in form order; later rows win.

    Rows with an empty timestamp are the blank rows Sheets leaves in
    an export and are skipped.
    """
    if not path.is_file():
        raise InputError(f"not found: {path}")
    latest: dict[str, Registrant] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        wanted = [email_col, name_col, time_col]
        if answer_col is not None:
            wanted.append(answer_col)
        missing = [c for c in wanted if c not in (reader.fieldnames or [])]
        if missing:
            raise InputError(f"{path} has no column(s) {missing}")
        for row in reader:
            if not (row[time_col] or "").strip():
                continue
            email = (row[email_col] or "").strip()
            name = clean_name(row[name_col] or "")
            answer = (row[answer_col] or "") if answer_col else ""
            latest[email.lower()] = Registrant(email, name, answer)
    return list(latest.values())


def read_lookup(path: Path) -> Lookup:
    """Return the lookup table; its first column is the key.

    Raises InputError on a missing file, a repeated key or a blank
    value, since each would fill rows wrongly without a visible error.
    """
    if not path.is_file():
        raise InputError(f"not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        if len(header) < 2:
            raise InputError(f"{path} needs a key column and a value column")
        key_col, columns = header[0], header[1:]
        rows: dict[str, dict[str, str]] = {}
        for number, row in enumerate(reader, start=2):
            key = (row[key_col] or "").strip()
            if key in rows:
                raise InputError(f"{path} line {number}: key {key!r} repeated")
            values = {c: (row[c] or "").strip() for c in columns}
            blank = [c for c, v in values.items() if not v]
            if not key or blank:
                raise InputError(f"{path} line {number} has a blank value")
            rows[key] = values
    if not rows:
        raise InputError(f"{path} has no rows")
    return Lookup(columns, rows)


def read_template(path: Path, looked_up: set[str]
                  ) -> tuple[list[str], dict[str, str]]:
    """Return the template roster's header and its contact_* values.

    The address must be the first column and there must be a ``name``
    column. Every other column must be ``certificate_name``, a
    contact_* column shared by every recipient, or a column in
    ``looked_up``.
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
    others = [c for c in header[1:]
              if c not in {"name", FULL_NAME_COL} and c not in looked_up]
    unfillable = [c for c in others if not c.startswith(CONTACT_PREFIX)]
    if unfillable:
        raise InputError(
            f"{path} has per-person columns this tool cannot fill: "
            f"{unfillable}; supply them with --lookup")
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


def first_given_name(name: str) -> str:
    """Return the first given name; "Ma." keeps the word after it.

    >>> first_given_name("Ma. Leona Maye B. Pepito")
    'Ma. Leona'
    >>> first_given_name("Demetria May T. Saniel, DM")
    'Demetria'
    >>> first_given_name("Mary-Ann V. Galo")
    'Mary-Ann'
    >>> first_given_name("Ma")
    'Ma'
    >>> first_given_name("")
    ''
    """
    words = name.split()
    if len(words) > 1 and words[0].lower() in GIVEN_NAME_PREFIXES:
        return f"{words[0]} {words[1].rstrip(',')}"
    return words[0].rstrip(",") if words else ""


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
    >>> name_flags("Mervic M Gamolo")
    ['initial without full stop']
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
    if any(len(word) == 1 and word.isalpha() for word in words):
        flags.append("initial without full stop")
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


def build_row(person: Registrant, header: list[str],
              contacts: dict[str, str], greeting: str,
              lookup: Lookup | None) -> dict[str, str] | None:
    """Return the roster row for one registrant.

    Returns None when the registrant's answer matches no lookup key.
    """
    row = {header[0]: person.email, **contacts}
    row["name"] = (first_given_name(person.name) if greeting == "first"
                   else person.name)
    if FULL_NAME_COL in header:
        row[FULL_NAME_COL] = person.name
    if lookup is not None:
        key = lookup.key_for(person.answer)
        if key is None:
            return None
        row.update({c: v for c, v in lookup.rows[key].items()
                    if c in header})
    return row


def append_rows(path: Path, header: list[str],
                rows: list[dict[str, str]]) -> bool:
    """Append rows to the roster; return True if it was created."""
    creating = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
        if creating:
            writer.writeheader()
        writer.writerows(rows)
    return creating


def main(argv: list[str] | None = None) -> int:
    """Report new registrants, and append them with --write.

    Returns 0 on success, 1 when writing is refused, 2 on bad input.
    """
    args = parse_args(argv)
    try:
        lookup = read_lookup(args.lookup) if args.lookup else None
        header, contacts = read_template(
            args.template, set(lookup.columns) if lookup else set())
        form = read_form(args.form, args.email_col, args.name_col,
                         args.time_col, args.lookup_col)
        logs = {path: read_addresses(path) for path in args.sent_log}
        excluded: set[str] = set()
        for path in args.exclude:
            excluded |= read_addresses(path)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    on_form = {p.email.lower() for p in form}
    unmatched = [path for path, addrs in logs.items() if not addrs & on_form]
    for path in unmatched:
        print(f"warning: no address in {path} is on the form; "
              "is it the right log?", file=sys.stderr)

    done = excluded.union(*logs.values())
    queued = read_roster_addresses(args.roster, header[0]) - done
    skip = done | queued
    new = [p for p in form if p.email.lower() not in skip]

    print(f"form: {len(form)} addresses | sent or excluded: "
          f"{len(on_form & done)} | in roster, not yet sent: "
          f"{len(on_form & queued)} | new: {len(new)}")
    rows: list[dict[str, str]] = []
    no_match: list[str] = []
    for person in new:
        row = build_row(person, header, contacts, args.greeting, lookup)
        flags = name_flags(person.name) + email_flags(person.email,
                                                      args.domain)
        if row is None:
            no_match.append(person.email)
            flags.append(f"answer {person.answer!r} matches no lookup key")
        else:
            rows.append(row)
        key = (f"{lookup.key_for(person.answer) or '?':8} "
               if lookup else "")
        print(f"  {person.email:40} {person.name:32} {key}"
              f"{'; '.join(flags)}")

    if not new:
        return 0
    if not args.write:
        print("report only: rerun with --write to append")
        return 0
    if unmatched:
        print("error: not writing while a sent log matches nobody",
              file=sys.stderr)
        return 1
    broken = [p.email for p in new if not structurally_valid_email(p.email)]
    if broken:
        print(f"error: not writing invalid address(es): {broken}",
              file=sys.stderr)
        return 1
    if no_match:
        print(f"error: not writing rows with no lookup match: {no_match}",
              file=sys.stderr)
        return 1
    created = append_rows(args.roster, header, rows)
    print(f"{'created' if created else 'appended to'} {args.roster}: "
          f"{len(rows)} row(s); correct flagged names there before sending")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

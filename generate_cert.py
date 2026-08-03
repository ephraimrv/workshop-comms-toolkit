"""Generate per-recipient certificate PDFs and a mail_merge-ready roster.

Reads a clean roster (one row per person, with a tier), stamps each
name onto the matching template, and writes one certificate PDF per
person plus an enriched roster ready for ``mail_merge.py``.

Output
------
<out-dir>/<SERIAL>.pdf
    One certificate per serial, named by its serial (ASCII-safe). A
    participation-tier person has one; an attendance-tier person has
    one per session attended.
<out-dir>/roster_out.csv
    One row per PERSON (never per certificate: mail_merge.py refuses a
    roster with a repeated address). Carries the input columns plus
    three ``mail_merge.py`` reads: ``attachments`` (the filename(s) on
    disk), ``attachment_display`` (the name(s) the recipient sees), and
    ``serials`` (for audit). Where a person holds several certificates,
    all three are semicolon-joined in matching order, matching
    mail_merge.py's default ``--attachment-sep``.

Notes
-----
Tier is an input column, not something this tool decides. Tier is
produced upstream by an attendance rollup that counts distinct
sessions attended per person. Keeping tier derivation out of here is
deliberate: this file's single responsibility is stamping and naming,
so it stays identical across workshops while the rollup and the CLI
flags carry everything workshop-specific.

Everything that changes between workshops is a flag, not an edit:
``--serial-prefix`` (e.g. ``BSP-2026-W1`` vs ``BSP-2026-W2``),
``--template-attendance-pattern`` / ``--template-participation`` (this
workshop's artwork), and ``--font`` (a static Regular weight; see
Font below).

An attendance-tier person receives one certificate PER session they
attended (each stamped onto that session's own template); a
participation-tier person receives one. Serials therefore encode the
session: ``<prefix>-A-S<n>-<NNN>`` for attendance, ``<prefix>-P-<NNN>``
for participation. ``NNN`` is a zero-padded running number kept per
bucket -- one sequence per (tier, session) for attendance, one for
participation -- so a serial reads as "the NNNth attendance certificate
for session <n>". Numbers are assigned after sorting the roster by
email, a stable and unique key: sorting by name would let a later
roster edit (a fixed spelling, a late addition) silently reassign a
serial to a different person; email cannot drift that way.

Names are printed verbatim: the registration form asked how each
person wants their name to appear, so case and spelling are never
altered. The only transforms are stripping surrounding whitespace
and normalising to Unicode NFC, so a decomposed "n + combining
tilde" submission renders as one glyph rather than a floating
accent or a missing-glyph box.

Font must be a static Montserrat-Regular.ttf (``usWeightClass``
400, no ``fvar`` table). The variable-font build some sources serve
by default has a Thin default weight; a metrics-only check will not
catch this, only a visual check of the rendered output will.

Placement constants are measured against the real templates, which
share identical geometry: page 841.92 x 595.2 pt, name baseline at
y = 328.34, name size 36 pt.

Examples
--------
Generate Workshop 1's certificates from a rollup roster. The
attendance template is a PATTERN with ``{n}`` for the session number,
so an attendance-tier person gets one certificate per session::

    python generate_cert.py cert_roster.csv \\
        --serial-prefix BSP-2026-W1 \\
        --template-attendance-pattern templates/ATTENDANCE_S{n}.pdf \\
        --template-participation templates/PARTICIPATION.pdf \\
        --font fonts/Montserrat-Regular.ttf

Use custom roster column names::

    python generate_cert.py cert_roster.csv \\
        --name-col "Full Name" \\
        --email-col "Email" \\
        --tier-col "Certificate Tier" \\
        --sessions-col "Sessions" \\
        --serial-prefix BSP-2026-W1 \\
        --template-attendance-pattern templates/ATTENDANCE_S{n}.pdf \\
        --template-participation templates/PARTICIPATION.pdf

Write certificates somewhere other than ./certs, then hand the
result straight to mail_merge.py. Because a person may hold several
certificates, roster_out.csv is one row per person with the filenames
and display names semicolon-joined -- exactly mail_merge.py's default
``--attachment-sep``::

    python generate_cert.py cert_roster.csv \\
        --serial-prefix BSP-2026-W2 \\
        --template-attendance-pattern templates/ATTENDANCE_S{n}.pdf \\
        --template-participation templates/PARTICIPATION.pdf \\
        --out-dir certs_w2

    python mail_merge.py \\
        -R certs_w2/roster_out.csv \\
        --email-col email \\
        --attachment-dir certs_w2 \\
        --attachment-name-col attachment_display \\
        -b body.txt -s "Your BSP Workshop Certificate"
"""

from __future__ import annotations

__author__ = "Jan Ephraim R. Vallente"
__version__ = "0.1.0"

import csv
import io
import sys
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from collections import defaultdict
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf._page import PageObject
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from roster_checks import clean_name, likely_domain_typo, structurally_valid_email

PAGE_W, PAGE_H = 841.92, 595.2
NAME_SIZE = 36.0
NAME_BASELINE_Y = 328.34
SAFE_W = 690.0
SERIAL_SIZE = 7.5
FONT_NAME = "Montserrat"

# tier -> (serial letter, human label used in the display filename)
TIERS = {
    "attendance": ("A", "Attendance"),
    "participation": ("P", "Participation"),
}


def fitted_size(text: str, max_w: float, start: float = NAME_SIZE) -> float:
    """Largest size <= start at which text fits max_w. Closed form: stringWidth
    is exactly linear in point size, so the fit size is computed, not searched.
    """
    width_at_start = pdfmetrics.stringWidth(text, FONT_NAME, start)
    if width_at_start <= max_w:
        return start
    return max(start * max_w / width_at_start, 8.0)


def stamp(template_pdf: Path, name: str, serial: str) -> PageObject:
    """Return the template's first page with name (centred) and serial stamped."""
    buf = io.BytesIO()

    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    c.setFont(FONT_NAME, fitted_size(name, SAFE_W))  # ← this block draws the NAME
    c.setFillColorRGB(0, 0, 0)
    c.drawCentredString(PAGE_W / 2.0, NAME_BASELINE_Y, name)

    # Serial — white pill behind the text so it reads over any photo content
    serial_x, serial_y = 11.0, 28.0
    pad = 1.0
    serial_w = pdfmetrics.stringWidth(serial, FONT_NAME, SERIAL_SIZE)
    c.setFillColorRGB(1, 1, 1)  # white background
    c.rect(
        serial_x - pad,
        serial_y - pad,
        serial_w + 2 * pad,
        SERIAL_SIZE + 2 * pad,
        fill=1,
        stroke=0,
    )

    c.setFont(FONT_NAME, SERIAL_SIZE)
    c.setFillColorRGB(0.35, 0.35, 0.35)  # dark grey text
    c.drawString(11.0, 29.0, serial)
    c.showPage()
    c.save()
    buf.seek(0)
    page = PdfReader(template_pdf).pages[0]
    page.merge_page(PdfReader(buf).pages[0])
    return page


def load_roster(
    path: Path, name_col: str, email_col: str, tier_col: str, sessions_col: str
):
    """Read the roster, reporting every bad row at once rather than one per run.

    Returns (rows, problems). Each returned row is a dict with normalised
    'name', 'email', and 'tier' keys plus the original columns preserved.
    The parsed session list is stored under '_sessions' (a list of ints) so
    the original 'sessions' string column survives untouched into roster_out.
    """
    delimiter = "\t" if path.suffix.lower() in {".tsv", ".tab"} else ","
    rows: list[dict] = []
    problems: list[str] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        headers = [h.strip() for h in (reader.fieldnames or [])]
        for col in (name_col, email_col, tier_col, sessions_col):
            if col not in headers:
                problems.append(f"column {col!r} not found; available: {headers}")
        if problems:
            return [], problems
        for lineno, raw in enumerate(reader, start=2):
            row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
            name = clean_name(row.get(name_col, ""))
            email = row.get(email_col, "").lower()
            tier = row.get(tier_col, "").lower()
            if not name:
                problems.append(f"line {lineno}: empty name")
                continue
            if not structurally_valid_email(email):
                problems.append(f"line {lineno}: malformed email {email!r}")
                continue
            typo_suggestion = likely_domain_typo(email)
            if typo_suggestion:
                problems.append(
                    f"line {lineno}: {email!r} looks like a typo of "
                    f"...@{typo_suggestion} -- fix in the source, not here"
                )
                continue
            if tier not in TIERS:
                problems.append(f"line {lineno}: tier {tier!r} not in {sorted(TIERS)}")
                continue
            raw_sessions = row.get(sessions_col, "")
            session_nums: list[int] = []
            bad_token = False
            for tok in raw_sessions.split(";"):
                tok = tok.strip()
                if not tok:
                    continue
                if not tok.lstrip("-").isdigit():
                    problems.append(
                        f"line {lineno}: session {tok!r} is not an integer "
                        f"in {sessions_col!r}={raw_sessions!r}"
                    )
                    bad_token = True
                    break
                session_nums.append(int(tok))
            if bad_token:
                continue
            # Attendance fans out over sessions, so it needs at least one.
            # Participation is a single certificate and ignores the list.
            if tier == "attendance" and not session_nums:
                problems.append(
                    f"line {lineno}: attendance tier needs at least one session "
                    f"in {sessions_col!r}, got {raw_sessions!r}"
                )
                continue
            row["name"], row["email"], row["tier"] = name, email, tier
            row["_sessions"] = sorted(set(session_nums))
            rows.append(row)
    return rows, problems


def parse_args(argv: list[str] | None = None):
    p = ArgumentParser(
        description=(
            __doc__ or "Generate per-recipient certificate PDFs."
        ).splitlines()[0],
        formatter_class=RawDescriptionHelpFormatter,
        epilog=(
            "An attendance-tier person receives ONE certificate per session "
            "they attended, each stamped onto that session's template; a\n"
            "participation-tier person receives one certificate. roster_out.csv "
            "carries one row per PERSON, with each person's certificate\n"
            "filenames and display names semicolon-joined in matching order, "
            "ready for mail_merge.py.\n\n"
            "Example:\n"
            "  python generate_cert.py cert_roster.csv \\\n"
            "      --serial-prefix BSP-2026-W1 \\\n"
            "      --template-attendance-pattern templates/ATTENDANCE_S{n}.pdf \\\n"
            "      --template-participation templates/PARTICIPATION.pdf \\\n"
            "      --font fonts/Montserrat-Regular.ttf \\\n"
            "      --out-dir certs"
        ),
    )
    p.add_argument(
        "roster",
        type=Path,
        metavar="ROSTER",
        help=(
            "Rolled-up roster (CSV/TSV) with name, email, tier and sessions "
            "columns, as produced by rollup_attendance.py."
        ),
    )
    p.add_argument(
        "--name-col",
        default="name",
        metavar="HEADER",
        help="Column holding each person's name (default: %(default)s).",
    )
    p.add_argument(
        "--email-col",
        default="email",
        metavar="HEADER",
        help=(
            "Column holding each person's email; also the sort key that fixes "
            "serial assignment order (default: %(default)s)."
        ),
    )
    p.add_argument(
        "--tier-col",
        default="tier",
        metavar="HEADER",
        help=(
            "Column holding the tier, 'attendance' or 'participation' "
            "(default: %(default)s)."
        ),
    )
    p.add_argument(
        "--sessions-col",
        default="sessions",
        metavar="HEADER",
        help=(
            "Column holding the semicolon-joined distinct session numbers a "
            "person attended; attendance tier issues one certificate per "
            "session listed (default: %(default)s)."
        ),
    )
    p.add_argument(
        "--serial-prefix",
        required=True,
        metavar="PREFIX",
        help=(
            "Serial prefix identifying the workshop, e.g. BSP-2026-W1. "
            "Attendance serials read <prefix>-A-S<n>-<NNN>, participation "
            "serials <prefix>-P-<NNN>."
        ),
    )
    p.add_argument(
        "--template-attendance-pattern",
        required=True,
        metavar="PATTERN",
        help=(
            "Path template for the per-session attendance certificate, with "
            "{n} standing in for the session number, e.g. "
            "templates/ATTENDANCE_S{n}.pdf. Only the templates for sessions "
            "that actually appear in the roster are required."
        ),
    )
    p.add_argument(
        "--template-participation",
        type=Path,
        required=True,
        metavar="PDF",
        help="Path to the single participation certificate template PDF.",
    )
    p.add_argument(
        "--font",
        type=Path,
        default=Path("fonts/Montserrat-Regular.ttf"),
        metavar="TTF",
        help=(
            "Static Montserrat-Regular TTF used to stamp the name and serial "
            "(default: %(default)s)."
        ),
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("certs"),
        metavar="DIRECTORY",
        help=(
            "Where to write the certificate PDFs and roster_out.csv "
            "(default: %(default)s)."
        ),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Existence checks that do not depend on the roster contents. The
    # per-session attendance templates are resolved and checked below, once we
    # know which sessions actually appear.
    for label, path in (
        ("font", args.font),
        ("participation template", args.template_participation),
        ("roster", args.roster),
    ):
        if not path.exists():
            print(f"error: {label} not found: {path}", file=sys.stderr)
            return 2

    rows, problems = load_roster(
        args.roster,
        args.name_col,
        args.email_col,
        args.tier_col,
        args.sessions_col,
    )
    if problems:
        print("error: roster has problems; nothing generated:", file=sys.stderr)
        for pr in problems:
            print(f"  {pr}", file=sys.stderr)
        return 1
    if not rows:
        print("error: roster has no valid rows", file=sys.stderr)
        return 1

    # Resolve the attendance templates for exactly the sessions that appear,
    # reporting every missing one at once (same fail-together policy the roster
    # check uses). Participation needs no per-session template.
    needed_sessions = sorted(
        {s for r in rows if r["tier"] == "attendance" for s in r["_sessions"]}
    )
    attendance_template: dict[int, Path] = {}
    missing_templates: list[str] = []
    for s in needed_sessions:
        path = Path(args.template_attendance_pattern.format(n=s))
        attendance_template[s] = path
        if not path.exists():
            missing_templates.append(f"  session {s}: {path}")
    if missing_templates:
        print(
            "error: attendance template(s) not found; nothing generated:",
            file=sys.stderr,
        )
        for mt in missing_templates:
            print(mt, file=sys.stderr)
        return 2

    # Deterministic order: sort by email so serial assignment is stable across
    # reruns and independent of the roster's row order.
    rows.sort(key=lambda r: r["email"])

    pdfmetrics.registerFont(TTFont(FONT_NAME, str(args.font)))
    args.out_dir.mkdir(parents=True, exist_ok=True)

    # One running number per bucket: per (tier, session) for attendance, one
    # for participation. A serial's NNN therefore reads as "the Nth attendance
    # certificate for session <n>", assigned in email order within each bucket.
    counters: dict[tuple[str, int | None], int] = defaultdict(int)

    def next_serial(tier: str, session: int | None) -> str:
        if tier == "attendance":
            counters[("A", session)] += 1
            return f"{args.serial_prefix}-A-S{session}-{counters[('A', session)]:03d}"
        counters[("P", None)] += 1
        return f"{args.serial_prefix}-P-{counters[('P', None)]:03d}"

    enriched: list[dict] = []
    total_certs = 0
    for row in rows:
        name = row["name"]
        # Each person yields one (template, display_name, serial) job for a
        # participation certificate, or one per session for attendance.
        jobs: list[tuple[Path, str, str]] = []
        if row["tier"] == "participation":
            jobs.append(
                (
                    args.template_participation,
                    f"Certificate of Participation - {name}.pdf",
                    next_serial("participation", None),
                )
            )
        else:
            for s in row["_sessions"]:
                jobs.append(
                    (
                        attendance_template[s],
                        f"Certificate of Attendance (Session {s}) - {name}.pdf",
                        next_serial("attendance", s),
                    )
                )

        filenames: list[str] = []
        displays: list[str] = []
        serials: list[str] = []
        for template_path, display, serial in jobs:
            page = stamp(template_path, name, serial)
            pdf_writer = PdfWriter()
            pdf_writer.add_page(page)
            with (args.out_dir / f"{serial}.pdf").open("wb") as fh:
                pdf_writer.write(fh)
            filenames.append(f"{serial}.pdf")  # ASCII, on disk
            displays.append(display)
            serials.append(serial)
            total_certs += 1

        # One row per PERSON. mail_merge.py aborts on duplicate addresses, so
        # the same email must appear exactly once; multiple certificates ride
        # as semicolon-joined lists in matching order, which is precisely what
        # mail_merge.py's --attachment-sep and --attachment-name-col expect.
        # Original roster columns are preserved (minus the internal _sessions
        # list) so a mail_merge body template may still reference them.
        out_row = {k: v for k, v in row.items() if k != "_sessions"}
        out_row["serials"] = ";".join(serials)
        out_row["attachments"] = ";".join(filenames)
        out_row["attachment_display"] = ";".join(displays)
        enriched.append(out_row)

    out_roster = args.out_dir / "roster_out.csv"
    fieldnames = list(enriched[0].keys())
    with out_roster.open("w", encoding="utf-8", newline="") as f:
        csv_writer = csv.DictWriter(f, fieldnames=fieldnames)
        csv_writer.writeheader()
        csv_writer.writerows(enriched)

    print(
        f"generated {total_certs} certificate(s) for {len(enriched)} "
        f"person(s) in {args.out_dir}/"
    )
    print(f"mail_merge roster: {out_roster}")
    print(f"  attachment dir  : {args.out_dir}")
    print("  attachment col  : attachments")
    print("  attachment name col: attachment_display")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

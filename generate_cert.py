"""Generate per-recipient certificate PDFs and a mail_merge-ready roster.

Reads a clean roster (one row per person, with a tier), stamps each
name onto the matching template, and writes one certificate PDF per
person plus an enriched roster ready for ``mail_merge.py``.

Output
------
<out-dir>/<SERIAL>.pdf
    One certificate per person, named by its serial (ASCII-safe).
<out-dir>/roster_out.csv
    The input roster plus two columns ``mail_merge.py`` reads
    directly: ``attachments`` (the filename on disk) and
    ``attachment_display`` (the name the recipient sees).

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
``--template-attendance`` / ``--template-participation`` (this
workshop's artwork), and ``--font`` (a static Regular weight; see
Font below).

Serial scheme is ``<prefix>-<T>-<NNN>``, where ``T`` is ``A``
(attendance) or ``P`` (participation) and ``NNN`` is a zero-padded
running number. The number is a single global sequence assigned
after sorting the roster by email -- a stable, unique key. Sorting
by name would let a later roster edit (a fixed spelling, a late
addition) silently reassign a serial to a different person; email
cannot drift that way.

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
Generate Workshop 1's certificates from a rollup roster::

    python generate_certificates.py cert_roster.csv \\
        --serial-prefix BSP-2026-W1 \\
        --template-attendance templates/ATTENDANCE.pdf \\
        --template-participation templates/PARTICIPATION.pdf \\
        --font fonts/Montserrat-Regular.ttf

Use custom roster column names::

    python generate_certificates.py cert_roster.csv \\
        --name-col "Full Name" \\
        --email-col "Email" \\
        --tier-col "Certificate Tier" \\
        --serial-prefix BSP-2026-W1 \\
        --template-attendance templates/ATTENDANCE.pdf \\
        --template-participation templates/PARTICIPATION.pdf

Write certificates somewhere other than ./certs, then hand the
result straight to mail_merge.py::

    python generate_certificates.py cert_roster.csv \\
        --serial-prefix BSP-2026-W2 \\
        --template-attendance templates/ATTENDANCE.pdf \\
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
from argparse import ArgumentParser
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

    # Serial — white pill behind the text so it reads over any photo content
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    c.setFont(FONT_NAME, fitted_size(name, SAFE_W))
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


def load_roster(path: Path, name_col: str, email_col: str, tier_col: str):
    """Read the roster, reporting every bad row at once rather than one per run.

    Returns (rows, problems). Each returned row is a dict with normalised
    'name', 'email', and 'tier' keys plus the original columns preserved.
    """
    delimiter = "\t" if path.suffix.lower() in {".tsv", ".tab"} else ","
    rows: list[dict] = []
    problems: list[str] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        headers = [h.strip() for h in (reader.fieldnames or [])]
        for col in (name_col, email_col, tier_col):
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
            row["name"], row["email"], row["tier"] = name, email, tier
            rows.append(row)
    return rows, problems


def parse_args(argv: list[str] | None = None):
    p = ArgumentParser(
        description=(
            __doc__ or "Generate per-recipient certificate PDFs."
        ).splitlines()[0]
    )
    p.add_argument("roster", type=Path, help="CSV/TSV roster with name, email, tier.")
    p.add_argument("--name-col", default="name")
    p.add_argument("--email-col", default="email")
    p.add_argument("--tier-col", default="tier")
    p.add_argument("--serial-prefix", required=True, help="e.g. BSP-2026-W1")
    p.add_argument("--template-attendance", type=Path, required=True)
    p.add_argument("--template-participation", type=Path, required=True)
    p.add_argument("--font", type=Path, default=Path("fonts/Montserrat-Regular.ttf"))
    p.add_argument("--out-dir", type=Path, default=Path("certs"))
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    for label, path in (
        ("font", args.font),
        ("attendance template", args.template_attendance),
        ("participation template", args.template_participation),
        ("roster", args.roster),
    ):
        if not path.exists():
            print(f"error: {label} not found: {path}", file=sys.stderr)
            return 2

    rows, problems = load_roster(
        args.roster, args.name_col, args.email_col, args.tier_col
    )
    if problems:
        print("error: roster has problems; nothing generated:", file=sys.stderr)
        for pr in problems:
            print(f"  {pr}", file=sys.stderr)
        return 1
    if not rows:
        print("error: roster has no valid rows", file=sys.stderr)
        return 1

    # Deterministic order: sort by email, then assign a single global sequence.
    rows.sort(key=lambda r: r["email"])
    templates = {
        "attendance": args.template_attendance,
        "participation": args.template_participation,
    }

    pdfmetrics.registerFont(TTFont(FONT_NAME, str(args.font)))
    args.out_dir.mkdir(parents=True, exist_ok=True)

    enriched: list[dict] = []
    for n, row in enumerate(rows, start=1):
        letter, label = TIERS[row["tier"]]
        serial = f"{args.serial_prefix}-{letter}-{n:03d}"
        page = stamp(templates[row["tier"]], row["name"], serial)
        writer = PdfWriter()
        writer.add_page(page)
        with (args.out_dir / f"{serial}.pdf").open("wb") as fh:
            writer.write(fh)
        row["serial"] = serial
        row["attachments"] = f"{serial}.pdf"  # ASCII, on disk
        row["attachment_display"] = f"Certificate of {label} - {row['name']}.pdf"
        enriched.append(row)

    out_roster = args.out_dir / "roster_out.csv"
    fieldnames = list(enriched[0].keys())
    with out_roster.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(enriched)

    print(f"generated {len(enriched)} certificate(s) in {args.out_dir}/")
    print(f"mail_merge roster: {out_roster}")
    print(f"  attachment dir  : {args.out_dir}")
    print(f"  attachment col  : attachments")
    print(f"  display-name col: attachment_display")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

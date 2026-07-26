"""Spike v2 — prove the certificate name-stamping mechanic against the REAL templates.

Supersedes spike_stamp.py. Still a spike, not the production generator: cases
are hardcoded, no roster/manifest integration, no tier logic. What changed and
why, versus v1 — every change is called out, nothing is silently revised:

  1. NAME_BASELINE_Y corrected 319.0 -> 328.34. This was an assumption in v1,
     flagged in the handoff as "verify against a test render." Verified by
     extracting the actual text-origin of the LOREM IPSUM placeholder from
     ATTENDANCE.pdf / PARTICIPATION.pdf via PyMuPDF's text dict (both files
     share identical geometry). The old value was wrong by 9.3pt.
  2. Stamps onto the REAL template page (PdfReader on the actual PDF) instead
     of a stand-in guide-rail page. This is the meaningful upgrade: v1 proved
     the mechanic in isolation, v2 proves it against the artwork it will
     actually ship on.
  3. fitted_size() replaced: v1 decremented by 0.25pt in a loop until the
     string fit. stringWidth is exactly linear in point size (verified: width
     at 1pt * 36 == width at 36pt, to the last digit), so the fit size is
     computable in closed form: size = start * max_w / width_at(start).
     One line, exact, no loop, no floor-guard needed for the search itself
     (a floor is kept as a sanity minimum, not a loop terminator).
  4. SAFE_W left at 690.0, UNCHANGED, but the justification changed: there is
     no artwork or border within ~100pt of the name line in either axis (the
     building photo's top edge and the name's descender don't come close to
     meeting), so this is not a collision boundary the way NAME_BASELINE_Y
     was. It's a kept aesthetic default (it happens to closely match the
     width of the template's own "Given this {DAY} day..." line, 691.22pt).
     Change it freely -- nothing will clip.
  5. Two templates supported (ATTENDANCE, PARTICIPATION) since both share
     identical page size and placeholder origin -- confirmed, not assumed.

Font: point MONTSERRAT_PATH at a static Montserrat-Regular.ttf (usWeightClass
400, no fvar table). Do NOT use the variable-font build Google Fonts serves
by default -- its default axis position is wght=100 (Thin), and a metrics-only
check will not catch this: the variable file's width for common strings is
within ~1% of the static Regular, so only a visual check of the rendered
output reveals the wrong weight.
"""

from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# --- measurements, extracted from the real ATTENDANCE/PARTICIPATION templates ---
PAGE_W, PAGE_H = 841.92, 595.2
NAME_SIZE = 36.0
NAME_BASELINE_Y = 328.34  # measured; was 319.0 (assumed) in v1
SAFE_W = 690.0  # aesthetic default; see docstring point 4
SERIAL_SIZE = 7.5

MONTSERRAT_PATH = "fonts/Montserrat-Regular.ttf"  # point this at YOUR real file
TEMPLATES = {
    "attendance": "templates/ATTENDANCE.pdf",
    "participation": "templates/PARTICIPATION.pdf",
}

pdfmetrics.registerFont(TTFont("Montserrat", MONTSERRAT_PATH))


def fitted_size(text: str, max_w: float, start: float = NAME_SIZE) -> float:
    """Largest size <= start at which text fits max_w. Never enlarges.

    Closed form: stringWidth scales linearly with point size, so the fit
    size is computed directly rather than searched for.
    """
    width_at_start = pdfmetrics.stringWidth(text, "Montserrat", start)
    if width_at_start <= max_w:
        return start
    size = start * max_w / width_at_start
    return max(size, 8.0)  # sanity floor, not a search terminator


def stamp(template_page, name: str, serial: str):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))

    size = fitted_size(name, SAFE_W)
    c.setFont("Montserrat", size)
    c.setFillColorRGB(0, 0, 0)
    c.drawCentredString(PAGE_W / 2.0, NAME_BASELINE_Y, name)

    c.setFont("Montserrat", SERIAL_SIZE)
    c.setFillColorRGB(0.45, 0.45, 0.45)
    c.drawString(36.0, 28.0, serial)

    c.showPage()
    c.save()
    buf.seek(0)
    overlay = PdfReader(buf).pages[0]
    template_page.merge_page(overlay)
    return template_page, size


CASES = [
    ("Glory B. Va\u00f1o", "BSP-2026-W1-A-001"),
    ("Felix R. Olivas, Jr.", "BSP-2026-W1-A-002"),
    ("Sydney Scarlette A. Saturnino", "BSP-2026-W1-P-003"),
    ("Immanuelle Faith S. Sibayan", "BSP-2026-W1-P-004"),
    ("Mae Rose Maoirat-Abad", "BSP-2026-W1-P-005"),
    ("Maria Cristina Bernadette Villanueva-Dimaculangan III", "BSP-2026-W1-A-006"),
]

if __name__ == "__main__":
    for label, path in TEMPLATES.items():
        if not Path(path).exists():
            print(f"skip {label}: {path} not found (expected -- adjust TEMPLATES)")
            continue
        writer = PdfWriter()
        print(f"\n=== {label} ({path}) ===")
        print(f"{'name':<54}{'width@36':>10}{'used':>8}{'fits':>7}")
        for name, serial in CASES:
            w36 = pdfmetrics.stringWidth(name, "Montserrat", NAME_SIZE)
            page = PdfReader(path).pages[0]
            page, used = stamp(page, name, serial)
            writer.add_page(page)
            print(f"{name:<54}{w36:>10.1f}{used:>8.2f}{str(w36 <= SAFE_W):>7}")
        out_path = f"spike_v2_{label}.pdf"
        with open(out_path, "wb") as fh:
            writer.write(fh)
        print(f"wrote {out_path}")

"""Spike — prove the certificate name-stamping mechanic.

NOT the production script. This exists to answer four questions before the
real template is available:

  1. Does centring computed from real font metrics land dead centre?
  2. Does the 'n-tilde' in 'Vano' survive embedding?
  3. What happens to a name wider than the safe width?
  4. Does the serial land clear of the artwork?
"""

from __future__ import annotations

import io

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# --- measurements recorded from ATTENDANCE.pdf (handoff s6) ------------------
PAGE_W, PAGE_H = 841.92, 595.2
NAME_SIZE = 36.0
NAME_BASELINE_Y = 319.0
SAFE_W = 690.0
SERIAL_SIZE = 7.5

pdfmetrics.registerFont(TTFont("Montserrat", "fonts/Montserrat-Regular.ttf"))


def fitted_size(text: str, max_w: float, start: float = NAME_SIZE) -> float:
    """Largest size <= start at which text fits max_w. Never enlarges."""
    size = start
    while size > 8.0 and pdfmetrics.stringWidth(text, "Montserrat", size) > max_w:
        size -= 0.25
    return size


def stamp(template_page, name: str, serial: str):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))

    size = fitted_size(name, SAFE_W)
    c.setFont("Montserrat", size)
    c.setFillColorRGB(0, 0, 0)
    # drawCentredString centres on the *advance width*, which is what we want.
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


def make_stand_in() -> bytes:
    """A stand-in for the real template: page box + guide marks only."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    c.setStrokeColorRGB(0.85, 0.85, 0.85)
    c.rect(20, 20, PAGE_W - 40, PAGE_H - 40)
    # safe-width rails
    c.setStrokeColorRGB(0.95, 0.6, 0.6)
    for x in ((PAGE_W - SAFE_W) / 2, (PAGE_W + SAFE_W) / 2):
        c.line(x, NAME_BASELINE_Y - 20, x, NAME_BASELINE_Y + 40)
    # page-centre rail
    c.setStrokeColorRGB(0.6, 0.7, 0.95)
    c.line(PAGE_W / 2, NAME_BASELINE_Y - 30, PAGE_W / 2, NAME_BASELINE_Y + 50)
    # baseline rail
    c.setStrokeColorRGB(0.8, 0.8, 0.8)
    c.line(60, NAME_BASELINE_Y, PAGE_W - 60, NAME_BASELINE_Y)
    c.showPage()
    c.save()
    return buf.getvalue()


CASES = [
    ("Glory B. Va\u00f1o", "BSP-2026-W1-A-001"),
    ("Felix R. Olivas, Jr.", "BSP-2026-W1-A-002"),
    ("Sydney Scarlette A. Saturnino", "BSP-2026-W1-P-003"),
    ("Immanuelle Faith S. Sibayan", "BSP-2026-W1-P-004"),
    ("Mae Rose Maoirat-Abad", "BSP-2026-W1-P-005"),
    ("Maria Cristina Bernadette Villanueva-Dimaculangan III", "BSP-2026-W1-A-006"),
]

if __name__ == "__main__":
    stand_in = make_stand_in()
    writer = PdfWriter()
    print(f"{'name':<54}{'width@36':>10}{'used':>8}{'fits':>7}")
    for name, serial in CASES:
        w36 = pdfmetrics.stringWidth(name, "Montserrat", NAME_SIZE)
        page = PdfReader(io.BytesIO(stand_in)).pages[0]
        page, used = stamp(page, name, serial)
        writer.add_page(page)
        print(f"{name:<54}{w36:>10.1f}{used:>8.2f}{str(w36 <= SAFE_W):>7}")
    with open("spike_out.pdf", "wb") as fh:
        writer.write(fh)
    print("\nwrote spike_out.pdf")

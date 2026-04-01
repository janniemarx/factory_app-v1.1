# D:\factory_app\utils\leave_pdf.py
from __future__ import annotations
from io import BytesIO
from datetime import date, timedelta
from typing import Dict, Tuple, Optional

from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.units import mm
from reportlab.lib.colors import gray
from pypdf import PdfReader, PdfWriter


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _page_size(template_path: str) -> tuple[float, float]:
    r = PdfReader(template_path)
    p = r.pages[0]
    return float(p.mediabox.width), float(p.mediabox.height)

def _mm(x: float) -> float:
    return float(x) * mm

def _xy_top_left(page_h_pt: float, x_mm: float, y_mm: float) -> tuple[float, float]:
    """Convert top-left millimetres -> reportlab coords (points from bottom-left)."""
    return _mm(x_mm), page_h_pt - _mm(y_mm)

def _draw_grid(c: canvas.Canvas, w_pt: float, h_pt: float, step_mm: int = 10):
    """Light grid for alignment (toggle with debug=1)."""
    c.setStrokeColor(gray)
    c.setLineWidth(0.3)
    cols = int(round(w_pt / _mm(step_mm)))
    rows = int(round(h_pt / _mm(step_mm)))
    for i in range(cols + 1):
        x = _mm(i * step_mm)
        c.line(x, 0, x, h_pt)
        c.setFont("Helvetica", 6)
        c.drawString(x + 1, 2, f"{i*step_mm}mm")
    for j in range(rows + 1):
        y = _mm(j * step_mm)
        c.line(0, y, w_pt, y)
        c.setFont("Helvetica", 6)
        c.drawString(2, y + 2, f"{j*step_mm}mm")

def _fit_text_in_box(
    c: canvas.Canvas,
    page_h_pt: float,
    x_mm: float, y_mm: float, w_mm: float, h_mm: float,
    text: str,
    font: str = "Helvetica",
    size: float = 10.0,
    align: str = "left",
):
    """Single-line text that auto-shrinks to stay inside the box width."""
    if not text:
        return
    x_left, y_top = _xy_top_left(page_h_pt, x_mm, y_mm)
    max_w = _mm(w_mm)
    y_baseline = y_top - _mm(h_mm) * 0.58  # slightly above vertical center

    c.setFont(font, size)
    text_w = pdfmetrics.stringWidth(text, font, size)
    while text_w > max_w and size > 6:
        size -= 0.5
        c.setFont(font, size)
        text_w = pdfmetrics.stringWidth(text, font, size)

    if align == "center":
        x = x_left + (max_w - text_w) / 2.0
    elif align == "right":
        x = x_left + (max_w - text_w)
    else:
        x = x_left
    c.drawString(x, y_baseline, text)

def _draw_multiline_in_box(
    c: canvas.Canvas,
    page_h_pt: float,
    x_mm: float, y_mm: float, w_mm: float, h_mm: float,
    text: str,
    font: str = "Helvetica",
    size: float = 9.0,
    leading: float | None = None,           # pass _mm(6) ≈ one ruled line spacing
    max_lines: int | None = 3,
):
    if not text:
        return

    # setup
    x_left, y_top = _xy_top_left(page_h_pt, x_mm, y_mm)
    max_w = _mm(w_mm)
    max_h = _mm(h_mm)
    c.setFont(font, size)
    leading = leading or (size * 1.25)

    def _wrap_para(s: str) -> list[str]:
        words = s.split()
        lines, cur = [], ""
        for w in words:
            cand = (cur + " " + w).strip()
            if pdfmetrics.stringWidth(cand, font, size) <= max_w:
                cur = cand
                continue
            if cur:                         # push current line
                lines.append(cur)
            # if a single word is longer than the line, hard-wrap it
            if pdfmetrics.stringWidth(w, font, size) > max_w:
                buf = ""
                for ch in w:
                    if pdfmetrics.stringWidth(buf + ch, font, size) <= max_w:
                        buf += ch
                    else:
                        lines.append(buf)
                        buf = ch
                cur = buf
            else:
                cur = w
        if cur:
            lines.append(cur)
        return lines

    # respect explicit newlines and wrap each paragraph
    paragraphs = text.replace("\r", "").split("\n")
    lines: list[str] = []
    for p in paragraphs:
        chunk = _wrap_para(p.strip())
        lines.extend(chunk if chunk else [""])

    # fit height / truncate w/ ellipsis
    max_fit = int(max_h // leading) or 1
    if max_lines:
        max_fit = min(max_fit, max_lines)
    if len(lines) > max_fit:
        lines = lines[:max_fit]
        last = lines[-1]
        ell = "…"
        while last and pdfmetrics.stringWidth(last + ell, font, size) > max_w:
            last = last[:-1]
        lines[-1] = (last + ell) if last else ell

    # draw lines top→down; each line will NOT exceed ruled-line width
    for i, line in enumerate(lines):
        y = y_top - leading * (i + 0.8)
        c.drawString(x_left, y, line)

def _business_days_inclusive(start: date, end: date) -> int:
    """Mon–Fri only, inclusive."""
    days = 0
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            days += 1
        cur += timedelta(days=1)
    return days


# ──────────────────────────────────────────────────────────────────────────────
# Tuned positions (mm) from TOP-LEFT
# ──────────────────────────────────────────────────────────────────────────────
LEAVE_POS: Dict[str, Tuple[float, float, float, float]] = {
    # Top boxes
    "employee_name":  (55.0, 48.0, 110.0, 7.0),
    "application_dt": (64.0, 56.0,  40.0, 7.0),

    # Table row #1 (Annual) — X/W/H reused for all rows; Y is row-specific below
    "row1_from":      (75.0,  89.0, 30.0, 7.0),
    "row1_to":        (122.5, 89.0, 30.0, 7.0),
    "row1_days":      (163.0, 89.0, 10.0, 7.0),

    # Total (bottom-right of the table)
    "total_days":     (163.0, 127.0, 10.0, 7.0),

    # Comments area (right of the "Comments:" label) — approx; tweak if needed
    "comments":       (35.0, 135.8, 80.0, 18.0),  # x, y, w, h (3 lines high)
}

# Per-row Y coordinates (mm). Non-uniform row heights handled here.
ROW_Y_MM: Dict[int, float] = {
    1: 89.0,   # Annual
    2: 95.0,   # Sick
    3: 102.0,  # Special
    4: 110.0,  # Unpaid
    5: 118.0,  # Family Responsibility
}

# Mapping from leave type string to row index
ROW_FOR_TYPE = {
    "annual": 1, "annual leave": 1,
    "sick": 2,   "sick leave": 2,
    "special": 3, "special leave": 3,
    "other": 3,  # <- backward-compat: old data labeled 'other' lands on Special row
    "study": 3, "study leave": 3,
    "unpaid": 4, "unpaid leave": 4,
    "family": 5, "family responsibility": 5, "family_responsibility": 5,
}

def _box(key: str, dx: float, dy: float) -> tuple[float, float, float, float]:
    x, y, w, h = LEAVE_POS[key]
    return x + dx, y + dy, w, h


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def render_leave_pdf(
    *,
    template_path: str,
    employee_name: str,
    application_date: date,
    leave_type: str,
    start_date: date,
    end_date: date,
    hours_per_day: float | None = None,
    days_total: float | None = None,
    nudge_dx_mm: float = 0.0,
    nudge_dy_mm: float = 0.0,
    debug_grid: bool = False,
    row_nudges_mm: Dict[int, float] | None = None,
    comments: Optional[str] = None,   # <— NEW
) -> BytesIO:
    """
    Returns a BytesIO of the merged PDF ready to send to the browser.
    - nudge_*: global micro adjustments for all fields.
    - row_nudges_mm: fine-tune a specific table row (keyed by row index 1..5).
    - comments: prints into the Comments box (word-wrapped).
    """
    w_pt, h_pt = _page_size(template_path)

    # Compute days
    if days_total is None:
        bd = _business_days_inclusive(start_date, end_date)
        if hours_per_day and hours_per_day > 0 and hours_per_day != 8:
            days = round(bd * (hours_per_day / 8.0), 2)
        else:
            days = bd
    else:
        days = days_total

    # Overlay
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(w_pt, h_pt))

    if debug_grid:
        _draw_grid(c, w_pt, h_pt, step_mm=10)

    # Top fields
    _fit_text_in_box(c, h_pt, *_box("employee_name", nudge_dx_mm, nudge_dy_mm),
                     employee_name, size=10)
    _fit_text_in_box(c, h_pt, *_box("application_dt", nudge_dx_mm, nudge_dy_mm),
                     application_date.isoformat(), size=10)

    # Table row: exact Y from per-row map (+ optional per-row nudge)
    key = (leave_type or "").strip().lower()
    row = ROW_FOR_TYPE.get(key, 1)
    y_row = ROW_Y_MM.get(row, ROW_Y_MM[1]) + (row_nudges_mm or {}).get(row, 0.0)

    # FROM / TO / Days
    x, _y1, w, h = LEAVE_POS["row1_from"]
    _fit_text_in_box(c, h_pt, x + nudge_dx_mm, y_row + nudge_dy_mm, w, h,
                     start_date.isoformat(), size=10)

    x, _y1, w, h = LEAVE_POS["row1_to"]
    _fit_text_in_box(c, h_pt, x + nudge_dx_mm, y_row + nudge_dy_mm, w, h,
                     end_date.isoformat(), size=10)

    x, _y1, w, h = LEAVE_POS["row1_days"]
    _fit_text_in_box(c, h_pt, x + nudge_dx_mm, y_row + nudge_dy_mm, w, h,
                     str(days).rstrip("0").rstrip("."), size=10, align="right")

    # Total days
    _fit_text_in_box(c, h_pt, *_box("total_days", nudge_dx_mm, nudge_dy_mm),
                     str(days).rstrip("0").rstrip("."), size=10, align="right")

    # Comments (wrapped)
    if comments:
        _draw_multiline_in_box(
            c, h_pt, *_box("comments", nudge_dx_mm, nudge_dy_mm),
            comments, size=9, leading=_mm(5), max_lines=3  # ~6mm between the lines
        )

    c.save()
    buf.seek(0)

    # Merge with template
    base = PdfReader(template_path)
    page = base.pages[0]
    overlay = PdfReader(buf).pages[0]
    page.merge_page(overlay)
    out = PdfWriter()
    out.add_page(page)
    final = BytesIO()
    out.write(final)
    final.seek(0)
    return final

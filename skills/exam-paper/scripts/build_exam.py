#!/usr/bin/env python3
"""Build a school exam paper (Arabic/English, A4, print-ready) as a PDF.

    python build_exam.py --data exam.json --out exam.pdf [--max-pages 4]

The JSON format is described in references/data-format.md and the layout rules in
references/layout-rules.md. The short version of what this script guarantees:

  1. Items (pictures, choices, word banks, matching options) are spread across equal
     columns, and a partial last row is centred, so no side is left with a ragged gap.
  2. Both sides of a matching question get the same distribution: if the pictures run
     horizontally, the sentences run horizontally underneath them, in the same columns.
  3. A single question is not cut between two pages. When keeping it whole would push
     a large blank down the page, the spacing ladder is tightened until it fits.
  4. Paragraphs are justified, but the last line is never stretched and paragraphs
     shorter than three lines stay ragged.
  5. The choices of a multiple-choice item sit on one line whenever they fit; the
     fallback is a balanced two or three column block, never one orphan at the end.
  6. The paper stops at --max-pages (4 by default). If it still does not fit, the
     script says so loudly and names the longest questions.
"""
import argparse
import base64
import html
import json
import math
import pathlib
import re
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
FONT_DIR = SKILL_DIR / "assets" / "fonts"
LOGO = SKILL_DIR / "assets" / "logo.png"
sys.path.insert(0, str(HERE))

from exam_css import CONTENT_H_PX, CONTENT_W_PX, stylesheet  # noqa: E402

# ---------------------------------------------------------------------------- tokens
PALETTE = {
    "navy": "#0a1544",
    "sec": "#343e66",
    "line": "#d5dbeb",
    "navy05": "#f3f5fb",
    "navy10": "#e6eaf5",
    "red": "#eb3c0b",
    "red_deep": "#b92f09",
    "green": "#039a79",
    "green_deep": "#006c55",
    "yellow": "#f1e102",
    "yellow_tint": "#fffbd6",
}

# Pairs that carry text; each must reach WCAG AA (4.5:1).
CONTRAST_PAIRS = [
    ("navy", "white", "نص الأسئلة"),
    ("sec", "white", "النص الثانوي"),
    ("navy", "navy05", "بطاقات البيانات وخلفية القطعة"),
    ("navy", "yellow_tint", "حبة الدرجة"),
    ("sec", "navy05", "عناوين الجوانب"),
    ("white", "navy", "رقم السؤال"),
]

# The density ladder: (spacing, font scale, line-height). Spacing is squeezed first,
# because narrowing the leading costs less legibility than shrinking the glyphs.
DENSITY = [
    (1.00, 1.00, 1.72),
    (0.90, 1.00, 1.66),
    (0.80, 1.00, 1.60),
    (0.72, 0.99, 1.56),
    (0.64, 0.97, 1.52),
    (0.56, 0.95, 1.48),
    (0.48, 0.93, 1.44),
    (0.42, 0.91, 1.40),
    (0.36, 0.89, 1.36),
]

ARABIC_MARKERS = ["أ", "ب", "ج", "د", "هـ", "و", "ز", "ح"]
LATIN_MARKERS = ["A", "B", "C", "D", "E", "F", "G", "H"]
QUESTION_TYPES = {"mcq", "truefalse", "matching", "fill", "short", "passage", "essay", "order"}

LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z0-9'’\-]*(?:[,.]?[  ]+[A-Za-z0-9][A-Za-z0-9'’\-]*)*[?!.]?")
# Only an explicit <...> or [[...]] token counts as an unfilled placeholder; plain
# square brackets are ordinary punctuation in exam texts.
PLACEHOLDER = re.compile(r"<[^<>\n]{1,60}>|\[\[[^\]\n]{1,60}\]\]")


# ---------------------------------------------------------------------------- colour
def _rgb(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _lum(rgb):
    def f(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(fg, bg):
    a = PALETTE.get(fg, "#ffffff")
    b = PALETTE.get(bg, "#ffffff")
    l1, l2 = sorted([_lum(_rgb(a)), _lum(_rgb(b))], reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def check_contrast():
    return [(f, b, d, contrast(f, b), contrast(f, b) >= 4.5) for f, b, d in CONTRAST_PAIRS]


# ---------------------------------------------------------------------------- text
def rich(text):
    """Escape, isolate Latin phrases, and turn ___ into a ruled blank.

    The isolation keeps '?' and quotation marks attached to the English words when an
    English phrase sits inside an Arabic sentence.
    """
    text = str(text)
    parts, pos = [], 0
    for m in LATIN_RUN.finditer(text):
        parts.append(html.escape(text[pos:m.start()]))
        parts.append('<bdi dir="ltr" lang="en">' + html.escape(m.group(0)) + "</bdi>")
        pos = m.end()
    parts.append(html.escape(text[pos:]))
    out = "".join(parts)
    out = re.sub(r"_{3,}", '<span class="blank"></span>', out)
    return out


def marker(i, style):
    if style == "num":
        return str(i + 1)
    table = LATIN_MARKERS if style == "latin" else ARABIC_MARKERS
    return table[i] if i < len(table) else str(i + 1)


def data_uri(path, base):
    p = pathlib.Path(path)
    if not p.is_absolute():
        p = base / p
    if not p.exists():
        raise SystemExit(f"خطأ: الصورة غير موجودة: {p}")
    kind = {"png": "png", "jpg": "jpeg", "jpeg": "jpeg", "gif": "gif",
            "svg": "svg+xml", "webp": "webp"}.get(p.suffix.lower().lstrip("."), "png")
    return f"data:image/{kind};base64," + base64.b64encode(p.read_bytes()).decode("ascii")


def walk_strings(node, key=None):
    """Yield every string value in the data, skipping the keys we fill ourselves."""
    if isinstance(node, dict):
        for k, v in node.items():
            if str(k).startswith("_"):
                continue
            yield from walk_strings(v, k)
    elif isinstance(node, list):
        for v in node:
            yield from walk_strings(v, key)
    elif isinstance(node, str) and key not in ("image", "logo"):
        yield node


def text_len(v):
    return len(re.sub(r"\s+", " ", str(v or "")).strip())


# ---------------------------------------------------------------------------- loading
def load(path, allow_placeholders=False):
    base = pathlib.Path(path).resolve().parent
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    errors, warnings = [], []

    meta = data.setdefault("meta", {})
    for key in ("title", "subject", "grade"):
        if not str(meta.get(key, "")).strip():
            errors.append(f"الحقل meta.{key} مطلوب.")
    meta.setdefault("school", "مدارس أجيال المواهب")
    meta.setdefault("dir", "rtl")
    meta.setdefault("student_fields", ["اسم الطالب", "الفصل", "رقم الجلوس"])
    meta.setdefault("end_note", "انتهت الأسئلة")
    meta.setdefault("footer", "مع تمنياتنا لكم بالتوفيق والنجاح")

    questions = data.get("questions") or []
    if not questions:
        errors.append("لا توجد أسئلة في الملف (questions).")

    total = 0
    for n, q in enumerate(questions, 1):
        qt = q.get("type")
        if qt not in QUESTION_TYPES:
            errors.append(f"السؤال {n}: نوع غير معروف '{qt}'. الأنواع: {', '.join(sorted(QUESTION_TYPES))}")
            continue
        if not str(q.get("prompt", "")).strip():
            errors.append(f"السؤال {n}: نص السؤال (prompt) مطلوب.")
        try:
            total += float(q.get("marks") or 0)
        except (TypeError, ValueError):
            errors.append(f"السؤال {n}: الدرجة (marks) ليست رقماً.")
        if qt == "mcq":
            for j, it in enumerate(q.get("items") or [], 1):
                ch = it.get("choices") or []
                if len(ch) < 2:
                    errors.append(f"السؤال {n} الفقرة {j}: يلزم خياران على الأقل.")
        if qt == "matching":
            opts, stems = q.get("options") or [], q.get("stems") or []
            if not opts or not stems:
                errors.append(f"السؤال {n}: سؤال التطابق يحتاج options وstems.")
            elif len(opts) != len(stems):
                warnings.append(
                    f"السؤال {n}: عدد الخيارات {len(opts)} لا يساوي عدد العبارات {len(stems)}؛ "
                    "التوزيع سيبقى متناسقاً لكن ستبقى خلية فارغة."
                )
        for it in (q.get("items") or []) + (q.get("options") or []) + (q.get("stems") or []):
            if isinstance(it, dict) and it.get("image"):
                it["_src"] = data_uri(it["image"], base)

    if meta.get("logo"):
        meta["_logo"] = data_uri(meta["logo"], base)
    elif LOGO.exists():
        meta["_logo"] = data_uri(LOGO, pathlib.Path("."))

    if meta.get("total_marks") in (None, "") and total:
        meta["total_marks"] = int(total) if float(total).is_integer() else total
    elif total and meta.get("total_marks") not in (None, ""):
        try:
            if abs(float(meta["total_marks"]) - total) > 1e-6:
                warnings.append(
                    f"مجموع درجات الأسئلة {total:g} لا يساوي meta.total_marks "
                    f"{meta['total_marks']}؛ راجع الدرجات."
                )
        except (TypeError, ValueError):
            errors.append("meta.total_marks ليس رقماً.")

    if not allow_placeholders:
        for value in walk_strings(data):
            m = PLACEHOLDER.search(value)
            if m and any(ch.isalpha() for ch in m.group(0)):
                errors.append(f"نص بين أقواس لم يُملأ: {m.group(0)[:60]}")
                break

    return data, base, errors, warnings


# ---------------------------------------------------------------------------- markup
def row(children, sync=None, nowrap=True, min_px=0, max_cols=0, cls=""):
    attrs = ['class="' + ("row " + cls).strip() + '"']
    if sync:
        attrs.append(f'data-sync="{sync}"')
    if not nowrap:
        attrs.append('data-nowrap="0"')
    if min_px:
        attrs.append(f'data-min="{min_px}"')
    if max_cols:
        attrs.append(f'data-max="{max_cols}"')
    return "<div " + " ".join(attrs) + ">" + "".join(children) + "</div>"


def pic_cell(item, tag, img_style):
    img = f'<img src="{item["_src"]}" alt="" style="{img_style}">' if item.get("_src") else ""
    label = f'<span class="tag">{rich(tag)}</span>' if tag else ""
    txt = f'<span class="fitw">{rich(item["text"])}</span>' if item.get("text") else ""
    return f'<div class="pic">{img}{txt}{label}</div>'


def lines_block(n):
    return '<div class="lines">' + "<i></i>" * max(1, int(n)) + "</div>"


def choices_html(item, qid, idx, style):
    chs = item.get("choices") or []
    cells = []
    for k, c in enumerate(chs):
        cells.append(
            f'<div class="choice box"><span class="mk">{marker(k, style)}</span>'
            f'<span class="fitw">{rich(c)}</span></div>'
        )
    return row(cells, max_cols=min(len(chs), 6))


def count_phrase(n, single, dual, plural):
    """Arabic counts the noun by the number: 1 noun, 2 dual, 3-10 plural, 11+ singular."""
    try:
        value = float(n)
    except (TypeError, ValueError):
        return f"{n} {single}"
    whole = int(value) if float(value).is_integer() else None
    if whole == 1:
        return f"{single} واحدة"
    if whole == 2:
        return dual
    if whole is not None and 3 <= whole <= 10:
        return f"{whole} {plural}"
    return f"{whole if whole is not None else f'{value:g}'} {single}"


def marks_phrase(marks):
    return count_phrase(marks, "درجة", "درجتان", "درجات")


def pages_phrase(n):
    return count_phrase(n, "صفحة", "صفحتان", "صفحات")


def items_phrase(n):
    return count_phrase(n, "فقرة", "فقرتان", "فقرات")


def q_header(n, q):
    marks = q.get("marks")
    pill = f'<span class="q-marks">{marks_phrase(marks)}</span>' if marks else ""
    # dir="auto" lets an Arabic gloss under an English instruction (or the reverse)
    # keep its own direction, so its full stop stays at the end of the sentence.
    sub = f'<span class="q-sub" dir="auto">{rich(q["sub"])}</span>' if q.get("sub") else ""
    return (
        f'<div class="q-head"><span class="q-num">{rich(n)}</span>'
        f'<span class="q-prompt">{rich(q["prompt"])}{sub}</span>{pill}</div>'
    )


def matching_html(q, qid):
    opts, stems = q.get("options") or [], q.get("stems") or []
    opt_style = q.get("option_marker", "latin")
    has_image = any(o.get("_src") for o in opts) or any(s.get("_src") for s in stems)
    longest = max([text_len(o.get("text")) for o in opts] + [text_len(s.get("text")) for s in stems] + [0])
    want = q.get("layout", "auto")
    horizontal = want == "horizontal" or (want == "auto" and (has_image or longest <= 34))

    img_style = q.get("img_height") and f"max-height:{q['img_height']}" or ""
    labels = q.get("side_labels") or ["", ""]

    def opt_cell(o, i):
        tag = marker(i, opt_style)
        if o.get("_src"):
            return pic_cell(o, tag, img_style)
        return (f'<div class="opt"><span class="tag">{rich(tag)}</span>'
                f'<span class="fitw">{rich(o.get("text", ""))}</span></div>')

    def stem_cell(s, i):
        if s.get("_src"):
            return pic_cell(s, str(i + 1), img_style)
        return (f'<div class="opt"><span class="tag" dir="ltr">{rich(i + 1)}.</span>'
                f'<span class="fitw">{rich(s.get("text", ""))}</span></div>')

    # horizontal: the two sides and the answer boxes share one column count
    opt_row = row([opt_cell(o, i) for i, o in enumerate(opts)],
                  sync=qid, nowrap=not has_image, min_px=74 if has_image else 0,
                  max_cols=min(len(opts), 6))
    stem_row = row([stem_cell(s, i) for i, s in enumerate(stems)],
                   sync=qid, nowrap=True, max_cols=min(len(stems), 6))
    ans_row = row([f'<div class="ans">{i + 1} <em></em></div>' for i in range(len(stems))],
                  sync=qid, nowrap=True, max_cols=min(len(stems), 6))
    lab0 = f'<div class="side-label">{rich(labels[0])}</div>' if labels[0] else ""
    lab1 = f'<div class="side-label">{rich(labels[1])}</div>' if len(labels) > 1 and labels[1] else ""
    horiz = (f'<div class="m-h" data-sync="{qid}">{lab0}{opt_row}{lab1}{stem_row}'
             f'<div class="side-label">{rich(q.get("answer_label", "الإجابة"))}</div>{ans_row}</div>')

    # Vertical: one CSS grid of two columns rather than two stacks side by side, so
    # row n of the statements and row n of the options always sit on the same line even
    # when one of them wraps. The two sides are distributed alike here as well.
    cells = []
    if lab0 or lab1:
        cells += [f'<div class="vlab">{rich(labels[1]) if len(labels) > 1 else ""}</div>',
                  f'<div class="vlab">{rich(labels[0])}</div>']
    for i in range(max(len(stems), len(opts))):
        if i < len(stems):
            s = stems[i]
            cells.append(f'<div class="vrow"><span class="tag" dir="ltr">{rich(i + 1)}.</span>'
                         f'<span class="fitw" dir="auto">{rich(s.get("text", ""))}</span>'
                         f'<span class="ans"><em></em></span></div>')
        else:
            cells.append('<div class="vrow"></div>')
        if i < len(opts):
            o = opts[i]
            cells.append(f'<div class="vrow"><span class="tag" dir="ltr">{rich(marker(i, opt_style))}.</span>'
                         f'<span class="fitw" dir="auto">{rich(o.get("text", ""))}</span></div>')
        else:
            cells.append('<div class="vrow"></div>')
    vert = (f'<div class="m-v" data-sync="{qid}" style="display:none">'
            f'<div class="pairs">{"".join(cells)}</div></div>')

    body = (horiz + vert) if horizontal else vert.replace('style="display:none"', "")
    return f'<div class="match{"" if horizontal else " vertical"}">{body}</div>'


def question_html(n, q, qid):
    t = q["type"]
    style = q.get("marker", "latin" if q.get("dir") == "ltr" else "arabic")
    body = []

    if t == "mcq":
        for i, it in enumerate(q.get("items") or []):
            pic = f'<div class="pic" style="max-width:40%;margin-bottom:4px"><img src="{it["_src"]}" alt=""></div>' if it.get("_src") else ""
            stem = (f'<div class="stem"><span class="n" dir="ltr">{i + 1}.</span>'
                    f'<span class="t" dir="auto">{rich(it.get("text", ""))}</span></div>')
            body.append(f'<div class="item">{pic}{stem}{choices_html(it, qid, i, style)}</div>')

    elif t == "truefalse":
        labels = q.get("labels") or ["صح", "خطأ"]
        cells = []
        for i, it in enumerate(q.get("items") or []):
            cells.append(
                f'<div class="opt"><span class="tag" dir="ltr">{i + 1}.</span>'
                f'<span class="fitw">{rich(it.get("text", ""))}</span>'
                f'<span class="tf" style="margin-inline-start:auto">'
                f'<b>{rich(labels[0])}</b><b>{rich(labels[1])}</b></span></div>'
            )
        body.append(row(cells, max_cols=2))

    elif t == "matching":
        body.append(matching_html(q, qid))

    elif t == "fill":
        if q.get("bank"):
            cards = [f'<div class="opt" style="justify-content:center">'
                     f'<span class="fitw">{rich(w)}</span></div>' for w in q["bank"]]
            body.append(f'<div class="side-label">{rich(q.get("bank_label", "بنك الكلمات"))}</div>')
            body.append(row(cards, max_cols=min(len(q["bank"]), 8)))
        for i, it in enumerate(q.get("items") or []):
            body.append(f'<div class="item"><div class="stem"><span class="n" dir="ltr">{i + 1}.</span>'
                        f'<span class="t">{rich(it.get("text", ""))}</span></div></div>')

    elif t == "short":
        for i, it in enumerate(q.get("items") or []):
            body.append(f'<div class="item"><div class="stem"><span class="n" dir="ltr">{i + 1}.</span>'
                        f'<span class="t">{rich(it.get("text", ""))}</span></div>'
                        f'{lines_block(it.get("lines", q.get("lines", 2)))}</div>')

    elif t == "passage":
        p = q.get("passage") or {}
        head = f'<h4>{rich(p["title"])}</h4>' if p.get("title") else ""
        paras = "".join(f'<p class="para">{rich(x)}</p>' for x in (p.get("paragraphs") or []))
        body.append(f'<div class="passage">{head}{paras}</div>')
        for i, it in enumerate(q.get("items") or []):
            stem = (f'<div class="stem"><span class="n" dir="ltr">{i + 1}.</span>'
                    f'<span class="t" dir="auto">{rich(it.get("text", ""))}</span></div>')
            tail = choices_html(it, qid, i, style) if it.get("choices") else lines_block(it.get("lines", 1))
            body.append(f'<div class="item">{stem}{tail}</div>')

    elif t == "order":
        for i, it in enumerate(q.get("items") or []):
            cards = [f'<div class="opt" style="justify-content:center">'
                     f'<span class="fitw">{rich(w)}</span></div>' for w in (it.get("parts") or [])]
            # An ordering item usually carries no stem text, so the number rides beside
            # the word cards instead of sitting on a line of its own.
            stem = (f'<div class="stem"><span class="n" dir="ltr">{i + 1}.</span>'
                    f'<span class="t" dir="auto">{rich(it.get("text", ""))}</span></div>'
                    if str(it.get("text", "")).strip() else "")
            label = "" if stem else f'<span class="n" dir="ltr">{i + 1}.</span>'
            body.append(f'<div class="item">{stem}<div class="ordline">{label}'
                        f'{row(cards, max_cols=min(len(cards), 8))}</div>'
                        f'{lines_block(1)}</div>')

    elif t == "essay":
        if q.get("paragraphs"):
            body.append("".join(f'<p class="para">{rich(x)}</p>' for x in q["paragraphs"]))
        body.append(lines_block(q.get("lines", 6)))

    inner = "".join(body)
    big = t in ("passage", "essay") or len(q.get("items") or []) >= 8
    cls = "q splittable" if (q.get("splittable", big)) else "q"
    label = f"س{n}"
    return (f'<section class="{cls}" data-id="{qid}" data-label="{html.escape(label)}"'
            f'{" dir=ltr" if q.get("dir") == "ltr" else ""}>'
            f'{q_header(n, q)}<div class="q-body">{inner}</div></section>')


def header_html(meta):
    logo = f'<img src="{meta["_logo"]}" alt="">' if meta.get("_logo") else ""
    dept = f'<div class="dept">{rich(meta["department"])}</div>' if meta.get("department") else ""
    total = meta.get("total_marks")
    stamp = (f'<div class="stamp"><b>{rich(total)}</b>'
             f'<span>{rich(meta.get("marks_label", "الدرجة الكلية"))}</span></div>') if total else ""
    return (f'<header class="head" data-id="head">{logo}'
            f'<div class="names"><div class="school">{rich(meta["school"])}</div>{dept}</div>'
            f'{stamp}</header>')


def meta_html(meta):
    cells = []
    order = [("subject", "المادة"), ("grade", "الصف"), ("term", "الفصل"),
             ("year", "العام"), ("date", "التاريخ"), ("duration", "الزمن")]
    for key, label in order:
        if meta.get(key):
            cells.append(f'<div class="cell"><b>{rich(meta.get(key + "_label", label))}:</b>'
                         f'<span class="fitw">{rich(meta[key])}</span></div>')
    info = row(cells, max_cols=min(len(cells), 4)) if cells else ""
    fields = [f'<div class="cell fill"><b>{rich(f)}:</b><span></span></div>'
              for f in (meta.get("student_fields") or [])]
    student = row(fields, nowrap=False, max_cols=min(len(fields), 4)) if fields else ""
    return (f'<div class="meta" data-id="meta">{info}</div>'
            f'<div class="meta" data-id="student" style="margin-top:calc(5px*var(--u))">'
            f'{student}</div>')


def build_html(data, step):
    meta = data["meta"]
    qs = data["questions"]
    notice = ""
    if meta.get("instructions"):
        lis = "".join(f"<li>{rich(x)}</li>" for x in meta["instructions"])
        notice = f'<div class="notice" data-id="notice"><ul>{lis}</ul></div>'
    body = "".join(question_html(i + 1, q, f"q{i + 1}") for i, q in enumerate(qs))
    end = (f'<div class="endnote" data-id="end">{rich(meta["end_note"])}'
           f'<span>{rich(meta["footer"])}</span></div>') if meta.get("end_note") else ""
    css = stylesheet(PALETTE | {"white": "#ffffff"}, step, FONT_DIR)
    fit_js = (HERE / "fit.js").read_text(encoding="utf-8")
    return f"""<!doctype html>
<html lang="ar" dir="{html.escape(meta.get('dir', 'rtl'))}">
<head><meta charset="utf-8"><title>{html.escape(str(meta['title']))}</title>
<style>{css}</style></head>
<body><main>
{header_html(meta)}
<div class="ribbon" data-id="ribbon"><i></i><i></i><i></i><i></i></div>
<h1 class="title" data-id="title">{rich(meta['title'])}</h1>
{meta_html(meta)}
{notice}
{body}
{end}
</main>
<script>{fit_js}</script>
</body></html>"""


# ---------------------------------------------------------------------------- paging
def simulate(blocks, page_h):
    """Model Chromium's pagination under break-inside:avoid.

    Returns (pages, gaps, hard_splits). A gap is the empty strip left at the foot of a
    page because the next question was kept whole and moved down - the "empty internal
    space" the layout is trying to avoid.
    """
    y, page = 0.0, 1
    gaps, splits = [], []
    for b in blocks:
        h = b["h"]
        avail = page_h - y
        if h <= avail + 0.5:
            y += h
            continue
        units = b["parts"] if (not b["atomic"] and b.get("parts")) else [h]
        for u in units:
            avail = page_h - y
            if u <= avail + 0.5:
                y += u
            elif u <= page_h + 0.5:
                if avail > 24:
                    gaps.append({"page": page, "gap": avail, "before": b["label"] or b["id"]})
                page += 1
                y = u
            else:                                   # taller than one page: it must be cut
                splits.append(b["label"] or b["id"])
                rest = u - avail
                page += int(rest // page_h) + 1
                y = rest % page_h
    return page, gaps, sorted(set(splits))


# A strip shorter than this at the foot of a page reads as an ordinary margin, not as
# a hole, so it must not buy a tighter - and less legible - setting of the whole paper.
GAP_TOLERANCE_PX = 110.0   # ~29 mm


def quality(pages, gaps, splits, max_pages):
    worst = max([g["gap"] for g in gaps], default=0.0)
    return {
        "pages": pages,
        "fits": pages <= max_pages,
        "splits": splits,
        "gaps": gaps,
        "worst_gap": worst,
        "gap_bucket": int(max(0.0, worst - GAP_TOLERANCE_PX) // 60),
        "total_gap": sum(g["gap"] for g in gaps),
    }


# ---------------------------------------------------------------------------- render
def find_chromium():
    """Return an explicit browser path when the bundled one does not match.

    The container ships one Chromium build under PLAYWRIGHT_BROWSERS_PATH; a newer
    playwright wheel looks for a different revision and fails. Pointing at the build
    that is actually present is cheaper than downloading another one.
    """
    import os
    root = pathlib.Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    if not root.exists():
        return None
    for pattern in ("chromium-*/chrome-linux/chrome",
                    "chromium_headless_shell-*/chrome-linux/chrome-headless-shell",
                    "chromium/chrome-linux/chrome"):
        hits = sorted(root.glob(pattern))
        if hits:
            return str(hits[-1])
    return None


def launch_browser(pw):
    try:
        return pw.chromium.launch()
    except Exception:
        path = find_chromium()
        if not path:
            raise
        return pw.chromium.launch(executable_path=path)


def run(data, out, html_path, max_pages, verbose=True):
    from playwright.sync_api import sync_playwright

    results = []
    with sync_playwright() as pw:
        browser = launch_browser(pw)
        page = browser.new_page(viewport={"width": int(CONTENT_W_PX), "height": 900})
        for idx, step in enumerate(DENSITY):
            html_path.write_text(build_html(data, step), encoding="utf-8")
            page.goto(html_path.as_uri())
            page.evaluate("document.fonts.ready")
            info = page.evaluate("window.__layout()")
            blocks = page.evaluate("window.__measure()")
            pages, gaps, splits = simulate(blocks, CONTENT_H_PX)
            q = quality(pages, gaps, splits, max_pages)
            q.update({"step": step, "idx": idx, "layout": info})
            results.append(q)
            if verbose:
                print(f"  كثافة {step[0]:.2f}: {pages_phrase(pages)}، "
                      f"أكبر فراغ {q['worst_gap'] / 3.78:.0f} مم"
                      + (f"، أسئلة مقسومة: {', '.join(splits)}" if splits else ""))
            if q["fits"] and not splits and q["gap_bucket"] == 0:
                break

        ok = [r for r in results if r["fits"] and not r["splits"]]
        if ok:
            best = min(ok, key=lambda r: (r["gap_bucket"], r["idx"]))
        else:
            best = min(results, key=lambda r: (len(r["splits"]), r["pages"], r["gap_bucket"]))

        html_path.write_text(build_html(data, best["step"]), encoding="utf-8")
        page.goto(html_path.as_uri())
        page.evaluate("document.fonts.ready")
        best["layout"] = page.evaluate("window.__layout()")
        page.wait_for_load_state("networkidle")
        page.pdf(path=str(out), prefer_css_page_size=True, print_background=True, tagged=True)
        browser.close()
    return best


def pdf_pages(path):
    import subprocess
    out = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True).stdout
    m = re.search(r"Pages:\s+(\d+)", out)
    return int(m.group(1)) if m else 0


# ---------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--html-out")
    ap.add_argument("--max-pages", type=int, default=4,
                    help="أقصى عدد صفحات لورقة الاختبار (الافتراضي 4)")
    ap.add_argument("--allow-placeholders", action="store_true")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    bad = [r for r in check_contrast() if not r[4]]
    if bad:
        for f, b, d, ratio, _ in bad:
            print(f"تباين غير كافٍ: {f} على {b} ({d}) = {ratio:.2f}:1", file=sys.stderr)
        sys.exit(2)

    data, base, errors, warnings = load(args.data, args.allow_placeholders)
    for w in warnings:
        print("تحذير:", w)
    if errors:
        for e in errors:
            print("خطأ:", e, file=sys.stderr)
        sys.exit(1)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    html_path = pathlib.Path(args.html_out) if args.html_out else \
        pathlib.Path(tempfile.mkdtemp()) / "exam.html"

    best = run(data, out, html_path, args.max_pages, verbose=not args.quiet)
    actual = pdf_pages(out)
    space, font, lh = best["step"]

    print(f"تم إنشاء {out}")
    print(f"الصفحات: {pages_phrase(actual)} (الحد {args.max_pages}) | التباعد {space:.2f} | "
          f"حجم الخط {font:.2f} | تباعد الأسطر {lh}")
    fb = best["layout"].get("verticalFallback") or []
    if fb:
        print("أسئلة تطابق حُوّلت إلى التوزيع العمودي لضيق العرض: " + "، ".join(fb))
    if best["gaps"]:
        worst = max(best["gaps"], key=lambda g: g["gap"])
        print(f"أكبر فراغ داخلي: {worst['gap'] / 3.78:.0f} مم قبل {worst['before']} "
              f"(في صفحة {worst['page']})")
    if best["splits"]:
        print("تحذير: هذه الأسئلة أطول من صفحة كاملة فاضطر تقسيمها: "
              + "، ".join(best["splits"]))

    exceeded = actual > args.max_pages
    if exceeded:
        heavy = sorted(
            ((q.get("marks") or 0, f"س{i + 1}",
              len(q.get("items") or q.get("stems") or []) ) for i, q in enumerate(data["questions"])),
            key=lambda x: -x[2])[:3]
        print("", file=sys.stderr)
        print("=" * 64, file=sys.stderr)
        print(f"تنبيه: ورقة الاختبار بلغت {pages_phrase(actual)}، وتجاوزت الحد "
              f"({pages_phrase(args.max_pages)}).", file=sys.stderr)
        print("استُنفدت كل درجات ضغط التباعد، ولا يمكن الوصول إلى الحد دون حذف محتوى.",
              file=sys.stderr)
        print("أطول الأسئلة: " + "، ".join(f"{lbl} ({items_phrase(cnt)})" for _, lbl, cnt in heavy),
              file=sys.stderr)
        print("الخيارات: قلّل عدد الفقرات، أو اختصر نصوصها، أو انقل سؤالاً إلى ورقة ثانية، "
              "أو ارفع الحد بـ --max-pages.", file=sys.stderr)
        print("=" * 64, file=sys.stderr)

    if not args.no_verify:
        import verify_exam_pdf
        ok = verify_exam_pdf.run(str(out), str(html_path), max_pages=args.max_pages)
        sys.exit(0 if (ok and not exceeded) else (4 if exceeded else 3))
    sys.exit(4 if exceeded else 0)


if __name__ == "__main__":
    main()

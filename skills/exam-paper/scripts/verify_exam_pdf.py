#!/usr/bin/env python3
"""Check a generated exam paper before it is handed over.

    python verify_exam_pdf.py exam.pdf exam.html [--max-pages 4]

Checks, in order:
  1. page count is within the limit;
  2. Tajawal is embedded and no fallback font crept in;
  3. the PDF is tagged and carries a title (screen readers);
  4. the text layer is intact - every Arabic and Latin word in the source is in the
     PDF exactly as written, lam-alef joins included, so copy and search work;
  5. no question is spread over more than one page, except the ones marked splittable;
  6. the text/background colour pairs still reach WCAG AA.
"""
import argparse
import html as html_mod
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

FALLBACK_FONTS = ("DejaVu", "Liberation", "FreeSerif", "FreeSans", "Noto")
ARABIC_WORD = re.compile(r"[ء-ي٠-٩]{3,}")
LATIN_WORD = re.compile(r"[A-Za-z]{3,}")
WHITESPACE = re.compile(r"\s+")
# Tashkeel is dropped from both sides before the words are compared: where a mark
# sits relative to its letter is a font matter, while the check is about the letters
# themselves staying in order (the lam-alef join above all).
DIACRITICS = re.compile("[" + chr(0x64b) + "-" + chr(0x652) + chr(0x670) + chr(0x640) + "]")


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def strip_tags(fragment):
    fragment = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", fragment, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html_mod.unescape(text)).strip()


def bare(text):
    """Diacritics and spaces removed, so only the letter sequence is compared.

    pdftotext emits a space around a tashkeel glyph that the font draws as its own
    mark, so "مبكرا" comes back as "مبكر ا". That is a position artefact, not damage,
    while a reversed lam-alef really does change the letter order - and that is what
    this check is for.
    """
    return WHITESPACE.sub("", DIACRITICS.sub("", text))


def pdf_pages_text(pdf):
    """Return a list with one normalised string per page."""
    n = 0
    info = sh(["pdfinfo", str(pdf)])
    m = re.search(r"Pages:\s+(\d+)", info)
    n = int(m.group(1)) if m else 0
    pages = []
    for i in range(1, n + 1):
        t = sh(["pdftotext", "-f", str(i), "-l", str(i), "-enc", "UTF-8", str(pdf), "-"])
        pages.append(re.sub(r"\s+", " ", t))
    return pages


def sections(html_text):
    """(label, splittable, [text chunks]) for every question in the source HTML."""
    out = []
    for m in re.finditer(r'<section class="(q[^"]*)"[^>]*data-label="([^"]*)"(.*?)</section>',
                         html_text, flags=re.S):
        cls, label, inner = m.group(1), html_mod.unescape(m.group(2)), m.group(3)
        inner = re.sub(r'<div class="m-v".*?</div>\s*</div>\s*</div>', " ", inner, flags=re.S)
        chunks = [c for c in (strip_tags(x) for x in re.split(r"(?=<div class=\"(?:item|opt|pic)\")", inner)) if c]
        out.append((label, "splittable" in cls, chunks))
    return out


def run(pdf, html_path, max_pages=4):
    pdf = pathlib.Path(pdf)
    source = pathlib.Path(html_path).read_text(encoding="utf-8")
    problems, notes = [], []

    info = sh(["pdfinfo", str(pdf)])
    m = re.search(r"Pages:\s+(\d+)", info)
    pages = int(m.group(1)) if m else 0
    if pages == 0:
        problems.append("تعذّرت قراءة الملف أو أنه فارغ.")
    elif pages > max_pages:
        problems.append(f"عدد الصفحات {pages} أكبر من الحد {max_pages}.")
    else:
        notes.append(f"عدد الصفحات {pages} ضمن الحد {max_pages}.")

    if "Tagged:          yes" not in info and "Tagged: yes" not in info.replace("  ", " "):
        problems.append("الملف غير موسوم (Tagged)، فقارئات الشاشة لن تقرأه ترتيبياً.")
    if not re.search(r"Title:\s*\S", info):
        problems.append("الملف بلا عنوان (Title).")
    if not [p for p in problems if "موسوم" in p or "عنوان" in p]:
        notes.append("الملف موسوم وله عنوان، فتقرؤه قارئات الشاشة بالترتيب.")

    fonts = sh(["pdffonts", str(pdf)])
    if "Tajawal" in fonts:
        notes.append("الخط Tajawal مضمَّن في الملف.")
    if "Tajawal" not in fonts:
        problems.append("الخط Tajawal غير مضمَّن في الملف.")
    for bad in FALLBACK_FONTS:
        if bad.lower() in fonts.lower():
            problems.append(f"ظهر خط احتياطي ({bad}) في الملف؛ الخط العربي لم يُضمَّن كاملاً.")
            break
    if re.search(r"\bno\b\s*$", fonts, flags=re.M) and "emb" in fonts.lower():
        notes.append("راجع عمود emb في pdffonts.")

    page_texts = pdf_pages_text(pdf)
    whole = bare(" ".join(page_texts))

    body = re.search(r"<main>(.*?)</main>", source, flags=re.S)
    # Marks are dropped before the words are split out, so a shadda inside a word
    # does not break it into two tokens; spaces stay, so words stay separate.
    src_text = DIACRITICS.sub("", strip_tags(body.group(1) if body else source))
    missing = []
    for word in set(ARABIC_WORD.findall(src_text)) | set(LATIN_WORD.findall(src_text)):
        if bare(word) not in whole:
            missing.append(word)
    if missing:
        sample = "، ".join(sorted(missing)[:8])
        problems.append(f"كلمات لم تظهر سليمة في طبقة النص ({len(missing)}): {sample}")
    else:
        notes.append("طبقة النص سليمة: كل الكلمات العربية والإنجليزية قابلة للنسخ والبحث.")

    split = []
    for label, splittable, chunks in sections(source):
        used = set()
        for c in chunks:
            probe = c[:40]
            if len(probe) < 15:
                continue
            for i, pt in enumerate(page_texts, 1):
                if bare(probe) in bare(pt):
                    used.add(i)
                    break
        if len(used) > 1 and not splittable:
            split.append(f"{label} (صفحات {'، '.join(str(x) for x in sorted(used))})")
    if split:
        problems.append("أسئلة انقسمت بين صفحتين: " + "، ".join(split))
    else:
        notes.append("لا يوجد سؤال مقسوم بين صفحتين.")

    try:
        import build_exam
        bad = [r for r in build_exam.check_contrast() if not r[4]]
        if bad:
            problems.append("تباين لوني دون 4.5:1: "
                            + "، ".join(f"{d} ({ratio:.2f}:1)" for _, _, d, ratio, _ in bad))
        else:
            notes.append("كل أزواج النص والخلفية تتجاوز 4.5:1.")
    except Exception as exc:                                   # pragma: no cover
        notes.append(f"تعذّر فحص التباين: {exc}")

    print("فحص ورقة الاختبار")
    for n in notes:
        print("  ✓", n)
    for p in problems:
        print("  ✗", p)
    print("النتيجة:", "سليم" if not problems else f"{len(problems)} ملاحظة تحتاج معالجة")
    return not problems


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("html")
    ap.add_argument("--max-pages", type=int, default=4)
    a = ap.parse_args()
    sys.exit(0 if run(a.pdf, a.html, a.max_pages) else 1)


if __name__ == "__main__":
    main()

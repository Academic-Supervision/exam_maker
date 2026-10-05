"""Stylesheet for the exam paper (A4, RTL-first, print).

Kept apart from build_exam.py so the layout rules stay readable. Everything that
changes with the density ladder is a CSS custom property set in :root, so the
same stylesheet serves every density step without string surgery.

Layout rules implemented here (see references/layout-rules.md):
  1. .row  - one flexible row engine used by choices, word banks, image strips and
     both sides of a matching question. Cells share one width, so items line up in
     columns, and a partial last row is centred instead of leaving a gap on one side.
  2. .q    - break-inside:avoid, so a question is never cut between two pages.
  3. .para - justified with text-align-last:start (the last line is not stretched).
  4. --u / --fs / --lh - the density ladder that squeezes spacing before font size.
"""

MM_PX = 96 / 25.4            # CSS pixels per millimetre at 96 dpi
PAGE_W_MM = 210.0
PAGE_H_MM = 297.0
MARGIN_TOP_MM = 12.0
MARGIN_SIDE_MM = 13.0
MARGIN_BOTTOM_MM = 14.0

CONTENT_W_PX = (PAGE_W_MM - 2 * MARGIN_SIDE_MM) * MM_PX
CONTENT_H_PX = (PAGE_H_MM - MARGIN_TOP_MM - MARGIN_BOTTOM_MM) * MM_PX


def font_faces(font_dir):
    faces = []
    for weight, name in ((300, "Light"), (400, "Regular"), (700, "Bold"), (800, "ExtraBold")):
        url = (font_dir / f"Tajawal-{name}.ttf").as_uri()
        faces.append(
            "@font-face{font-family:'Tajawal';font-weight:%d;font-style:normal;"
            "src:url('%s') format('truetype');}" % (weight, url)
        )
    return "\n".join(faces)


def root_vars(palette, step):
    """step = (space, font, line-height) from the density ladder."""
    space, font, lh = step
    pairs = ";".join(f"--{k.replace('_', '-')}:{v}" for k, v in palette.items())
    return (
        ":root{" + pairs + ";"
        f"--u:{space};--fs:{font};--lh:{lh};"
        f"--page-w:{PAGE_W_MM}mm;--page-h:{PAGE_H_MM}mm;"
        f"--mt:{MARGIN_TOP_MM}mm;--ms:{MARGIN_SIDE_MM}mm;--mb:{MARGIN_BOTTOM_MM}mm;"
        "}"
    )


# Chromium writes the lam-alef ligature to the PDF text layer in reverse order, so
# "الملاحظة" is copied back as "المالحظة". Turning ligatures off repairs copy, search
# and screen readers with no visible difference in Tajawal. Do not remove.
LIGATURE_CSS = (
    "font-variant-ligatures:none;"
    "font-feature-settings:'liga' 0,'rlig' 0,'calt' 0,'clig' 0;"
)

STATIC = """
*{box-sizing:border-box}
@page{
  size:A4;
  margin:var(--mt) var(--ms) var(--mb) var(--ms);
}
html{
  font-family:'Tajawal',sans-serif;
  font-size:calc(13.2px * var(--fs));
  line-height:var(--lh);
  color:var(--navy);
  __LIG__
  -webkit-print-color-adjust:exact;print-color-adjust:exact;
}
body{margin:0}
main{display:block}

/* ---------------------------------------------------------------- header */
.head{display:flex;align-items:center;gap:calc(10px * var(--u));
      padding-bottom:calc(7px * var(--u));border-bottom:2px solid var(--navy)}
.head img{height:calc(50px * var(--u) + 14px);width:auto}
.head .names{flex:1;min-width:0}
.head .school{font-weight:800;font-size:1.06rem;line-height:1.35}
.head .dept{color:var(--sec);font-size:.8rem;line-height:1.4}
.head .stamp{text-align:center;border:1px solid var(--line);border-radius:6px;
      padding:calc(4px * var(--u) + 2px) 10px;min-width:92px}
.head .stamp b{display:block;font-size:1.5rem;font-weight:800;line-height:1.1}
.head .stamp span{font-size:.72rem;color:var(--sec)}

.ribbon{display:flex;height:4px;margin:0 0 calc(8px * var(--u)) 0}
.ribbon i{flex:1}
.ribbon i:nth-child(1){background:var(--navy)}
.ribbon i:nth-child(2){background:var(--red)}
.ribbon i:nth-child(3){background:var(--yellow)}
.ribbon i:nth-child(4){background:var(--green)}

.title{text-align:center;font-weight:800;font-size:1.22rem;margin:calc(4px * var(--u)) 0}

/* meta + student fields: one row engine, equal cells, no ragged gap */
.meta{margin-bottom:calc(6px * var(--u))}
.meta .cell{background:var(--navy05);border:1px solid var(--line);border-radius:5px;
      padding:calc(3px * var(--u) + 2px) 8px;font-size:.82rem;display:flex;gap:6px;
      align-items:baseline;min-width:0}
.meta .cell b{font-weight:700;color:var(--sec);white-space:nowrap}
.meta .cell span{font-weight:700;overflow-wrap:anywhere}
.meta .cell.fill span{flex:1;border-bottom:1px dotted var(--sec);min-height:1.1em}

.notice{border-right:3px solid var(--navy);background:var(--navy05);
        padding:calc(5px * var(--u) + 2px) 10px;border-radius:0 5px 5px 0;
        font-size:.84rem;margin-bottom:calc(8px * var(--u))}
[dir=ltr] .notice{border-right:0;border-left:3px solid var(--navy);border-radius:5px 0 0 5px}
.notice ul{margin:0;padding-inline-start:16px}
.notice li{margin:calc(1px * var(--u)) 0}

/* ---------------------------------------------------------------- question */
/* Rule 2: one question is never cut between two pages. */
.q{break-inside:avoid;page-break-inside:avoid;margin-bottom:calc(11px * var(--u))}
.q.splittable{break-inside:auto;page-break-inside:auto}
.q-head{display:flex;align-items:flex-start;gap:8px;break-after:avoid;
        page-break-after:avoid;margin-bottom:calc(5px * var(--u) + 1px)}
.q-num{flex:0 0 auto;background:var(--navy);color:#fff;font-weight:800;
       border-radius:5px;padding:1px 7px;font-size:.84rem;line-height:1.5}
.q-prompt{flex:1;font-weight:700;min-width:0}
.q-sub{display:block;font-weight:400;color:var(--sec);font-size:.84rem}
.q-marks{flex:0 0 auto;border:1px solid var(--line);background:var(--yellow-tint);
         border-radius:5px;padding:1px 7px;font-size:.76rem;font-weight:700;white-space:nowrap}
.q-body{padding-inline-start:calc(4px * var(--u))}

/* ---------------------------------------------------------------- row engine */
/* Rule 1: equal-width cells, so items line up in columns; a partial last row is
   centred so the leftover space is split on both sides instead of hanging at one end.
   --cols is written by the fitting script in the page (fit.js). */
.row{display:flex;flex-wrap:wrap;justify-content:center;align-items:stretch;
     gap:calc(5px * var(--u) + 2px);--cols:1}
.row > *{flex:0 0 calc((100% - (var(--cols) - 1) * (5px * var(--u) + 2px)) / var(--cols));
         max-width:calc((100% - (var(--cols) - 1) * (5px * var(--u) + 2px)) / var(--cols));
         min-width:0;break-inside:avoid;page-break-inside:avoid}
.row.start{justify-content:flex-start}

/* choices (rule 5): the marker sits in a fixed box so the texts start on one line */
.choice{display:flex;align-items:baseline;gap:5px;
        padding:calc(2px * var(--u)) 2px;overflow-wrap:anywhere}
.choice .mk{flex:0 0 auto;min-width:1.45em;text-align:center;font-weight:700;
            color:var(--navy);border:1px solid var(--line);border-radius:4px;
            line-height:1.5;font-size:.78rem}
.choice.box .mk{border-radius:50%;min-width:1.5em}

.stem{margin-bottom:calc(3px * var(--u) + 1px);display:flex;gap:6px;align-items:baseline}
.stem .n{flex:0 0 auto;font-weight:700;color:var(--sec);min-width:1.4em}
.stem .t{flex:1;min-width:0}
.ordline{display:flex;gap:7px;align-items:center}
.ordline > .n{flex:0 0 auto;font-weight:700;color:var(--sec);min-width:1.4em}
.ordline > .row{flex:1;min-width:0}
.item{break-inside:avoid;page-break-inside:avoid;margin-bottom:calc(7px * var(--u))}
.item:last-child{margin-bottom:0}

/* picture cells */
.pic{border:1px solid var(--line);border-radius:6px;padding:calc(3px * var(--u) + 2px);
     text-align:center;background:#fff;display:flex;flex-direction:column;
     justify-content:space-between;gap:4px}
.pic img{width:100%;height:auto;object-fit:contain;display:block;margin:auto}
.pic .tag{font-weight:800;font-size:.8rem;border:1px solid var(--navy);border-radius:4px;
          display:inline-block;padding:0 6px;align-self:center}

/* ---------------------------------------------------------------- matching */
/* Rule: both sides of a matching question are distributed the same way. The two
   .row elements carry the same data-sync value, and fit.js gives them one shared
   column count, so the pictures and the sentences stand in the same columns. */
.side-label{font-size:.78rem;color:var(--sec);font-weight:700;
            margin:calc(4px * var(--u)) 0 calc(2px * var(--u)) 0}
/* One card used by matching options, true/false statements and word banks, so the
   three read as one family and every cell in a row keeps the same height. */
.opt{border:1px solid var(--line);border-radius:6px;background:var(--navy05);
     padding:calc(3px * var(--u) + 2px) 7px;display:flex;gap:6px;align-items:baseline;
     flex-wrap:nowrap;min-width:0}
.opt .tag{flex:0 0 auto;font-weight:800;color:var(--navy)}
.opt .fitw{min-width:0;overflow-wrap:anywhere}
.ans{border:1px solid var(--line);border-radius:6px;padding:calc(3px * var(--u) + 2px) 6px;
     display:flex;align-items:center;justify-content:center;gap:6px;font-weight:700;
     background:#fff}
.ans em{font-style:normal;display:inline-block;min-width:2.1em;height:1.35em;
        border-bottom:1.5px solid var(--navy)}
/* vertical fallback: two synchronised columns, equal row heights */
.pairs{display:grid;grid-template-columns:1fr 1fr;
       column-gap:calc(8px * var(--u) + 4px);row-gap:calc(4px * var(--u) + 1px)}
.vlab{font-size:.78rem;color:var(--sec);font-weight:700}
.vrow{display:flex;gap:6px;align-items:baseline;min-width:0;
      min-height:calc(1.55rem * var(--lh) / 1.6);break-inside:avoid}
.vrow .fitw{flex:1;min-width:0;overflow-wrap:anywhere}
.vrow .ans{flex:0 0 auto;padding:0 5px}

/* ---------------------------------------------------------------- passages */
/* Rule 3: justified, but the last line is never stretched; fit.js leaves short
   paragraphs ragged because justifying one or two lines looks worse than not. */
.para{text-align:justify;text-align-last:start;overflow-wrap:break-word;
      margin:0 0 calc(5px * var(--u)) 0}
.para:last-child{margin-bottom:0}
.passage{border:1px solid var(--line);border-radius:6px;background:var(--navy05);
         padding:calc(6px * var(--u) + 3px) 10px;margin-bottom:calc(7px * var(--u))}
.passage h4{margin:0 0 calc(3px * var(--u)) 0;font-size:.92rem;font-weight:800}

/* ---------------------------------------------------------------- answer space */
.lines{margin-top:calc(3px * var(--u))}
.lines i{display:block;border-bottom:1px dotted var(--sec);
         height:calc(1.48rem * var(--lh) / 1.6 * var(--u) + .45rem)}
.tf{display:flex;gap:5px;flex:0 0 auto;align-items:center;margin-inline-start:auto;
     padding-inline-start:6px}
.tf b{border:1px solid var(--line);border-radius:4px;min-width:2.1em;text-align:center;
      font-weight:700;line-height:1.6}
.blank{display:inline-block;min-width:4.5em;border-bottom:1px dotted var(--sec)}

/* ---------------------------------------------------------------- footer */
.endnote{text-align:center;font-weight:700;margin-top:calc(8px * var(--u));
         padding-top:calc(5px * var(--u));border-top:1px solid var(--line);
         font-size:.88rem;break-inside:avoid}
.endnote span{color:var(--sec);font-weight:400;font-size:.82rem;display:block}
"""


def stylesheet(palette, step, font_dir):
    return "\n".join([
        font_faces(font_dir),
        root_vars(palette, step),
        STATIC.replace("__LIG__", LIGATURE_CSS),
    ])

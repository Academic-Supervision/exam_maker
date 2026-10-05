# ajyal-exams

إضافة Claude Code لتوليد أوراق الاختبارات في مدارس أجيال المواهب: من ملف أسئلة
بصيغة JSON إلى ملف PDF مطبوع بهوية المدرسة، في أربع صفحات على الأكثر.

## ماذا تضبط هذه الإضافة

| القاعدة | السلوك |
|---|---|
| توزيع أفقي متوازن | العناصر في أعمدة متساوية العرض، والصف الأخير الناقص يُتوسَّط |
| تناسق سؤال التطابق | الطرفان بالتوزيع نفسه وعدد الأعمدة نفسه، أفقيين معاً أو عموديين معاً |
| السؤال لا ينقسم | كتلة واحدة لا تُقطع بين صفحتين، والتباعد يُضغط بدل ترك فراغ داخلي |
| تبرير هادئ | تبرير الطرفين، والسطر الأخير بلا تمطيط، والفقرات القصيرة بلا تبرير |
| الخيارات في سطر واحد | ما دامت تتسع، وإلا عمودان أو ثلاثة متوازنة |
| حد أربع صفحات | وإن تعذّر، تنبيه واضح بأطول الأسئلة والخيارات المتاحة |

التفاصيل والأسباب في `skills/exam-paper/references/layout-rules.md`.

## الاستعمال

```bash
python skills/exam-paper/scripts/build_exam.py \
    --data exam.json \
    --out "اختبار_اللغة_العربية_الثالث.pdf" \
    --max-pages 4
```

مثال كامل يعمل كما هو:

```bash
python skills/exam-paper/scripts/build_exam.py \
    --data skills/exam-paper/references/example/exam-sample.json \
    --out /tmp/exam.pdf
```

صيغة ملف الأسئلة في `skills/exam-paper/references/data-format.md`.

## المتطلبات

- Python 3.9 فأحدث، وحزمة `playwright` مع متصفح Chromium؛
- أدوات poppler: `pdfinfo` و`pdftotext` و`pdffonts` و`pdftoppm` للفحص والمعاينة.

## التركيب

```
.claude-plugin/plugin.json
skills/exam-paper/
    SKILL.md
    scripts/   build_exam.py · exam_css.py · fit.js · verify_exam_pdf.py
    assets/    fonts/Tajawal-*.ttf · logo.png
    references/ data-format.md · layout-rules.md · design-tokens.md · example/
```

## الرخصة

خط Tajawal تحت رخصته المرفقة في `skills/exam-paper/assets/fonts/FONT-LICENSE.txt`.

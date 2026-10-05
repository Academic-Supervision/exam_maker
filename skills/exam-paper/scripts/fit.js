/* Layout fitting that runs inside the page before the PDF is printed.
 *
 * Measuring in the browser instead of guessing from character counts is the whole
 * point: Arabic glyph widths in Tajawal are not predictable from text length, and a
 * guess produces either a wrapped "one line" of choices or a needlessly narrow one.
 *
 * It does four things, in order:
 *   1. fitRows()    - gives every .row the largest column count whose cells still
 *                     hold their text on one line (rule 1 and rule 5).
 *   2. syncRows()   - forces every row in one data-sync group to share the smallest
 *                     of those column counts, so both sides of a matching question
 *                     are distributed identically (rule 2).
 *   3. matchFallback() - if a matching question cannot hold two columns, it switches
 *                     to the vertical pair layout instead of leaving one item per row.
 *   4. justify()    - justifies only paragraphs of three lines or more (rule 3).
 *
 * window.__measure() is called afterwards from Python and returns the block heights
 * used to simulate pagination.
 */
(function () {
  'use strict';

  function colCandidates(n, maxCols) {
    // For each possible number of rows, the balanced column count. Fewest rows first.
    var out = [];
    for (var r = 1; r <= n; r++) {
      var c = Math.ceil(n / r);
      if (c <= maxCols && out.indexOf(c) === -1) out.push(c);
    }
    if (out.indexOf(1) === -1) out.push(1);
    return out;
  }

  function cells(row) {
    return Array.prototype.slice.call(row.children);
  }

  function fits(row, cols) {
    row.style.setProperty('--cols', cols);
    var min = parseFloat(row.dataset.min || '0');
    var kids = cells(row);
    for (var i = 0; i < kids.length; i++) {
      if (min && kids[i].getBoundingClientRect().width + 0.5 < min) return false;
    }
    if (row.dataset.nowrap === '0') return true;      // free-wrapping row: width only
    var probes = row.querySelectorAll('.fitw');
    for (var j = 0; j < probes.length; j++) {
      if (probes[j].scrollWidth > probes[j].clientWidth + 1) return false;
    }
    return true;
  }

  function bestCols(row) {
    var n = cells(row).length;
    if (!n) return 1;
    var maxCols = parseInt(row.dataset.max || '0', 10) || n;
    var cands = colCandidates(n, maxCols);
    row.classList.add('probe');
    var chosen = 1;
    for (var i = 0; i < cands.length; i++) {
      if (fits(row, cands[i])) { chosen = cands[i]; break; }
    }
    row.classList.remove('probe');
    row.style.setProperty('--cols', chosen);
    return chosen;
  }

  function fitRows() {
    var rows = document.querySelectorAll('.row');
    for (var i = 0; i < rows.length; i++) {
      rows[i].dataset.cols = bestCols(rows[i]);
    }
  }

  function syncRows() {
    var groups = {};
    var rows = document.querySelectorAll('.row[data-sync]');
    for (var i = 0; i < rows.length; i++) {
      var g = rows[i].dataset.sync;
      var c = parseInt(rows[i].dataset.cols, 10) || 1;
      groups[g] = groups[g] === undefined ? c : Math.min(groups[g], c);
    }
    for (var j = 0; j < rows.length; j++) {
      var cols = groups[rows[j].dataset.sync];
      rows[j].style.setProperty('--cols', cols);
      rows[j].dataset.cols = cols;
    }
    return groups;
  }

  function matchFallback(groups) {
    // A matching question laid out horizontally needs at least two columns to be
    // worth it. Below that the vertical twin-column layout reads better.
    var switched = [];
    Object.keys(groups).forEach(function (g) {
      if (groups[g] >= 2) return;
      var h = document.querySelector('.m-h[data-sync="' + g + '"]');
      var v = document.querySelector('.m-v[data-sync="' + g + '"]');
      if (!h || !v) return;
      h.style.display = 'none';
      v.style.display = 'block';
      switched.push(g);
    });
    return switched;
  }

  function justify() {
    var ps = document.querySelectorAll('.para');
    var ragged = 0;
    for (var i = 0; i < ps.length; i++) {
      var cs = getComputedStyle(ps[i]);
      var lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.6;
      var lines = Math.round(ps[i].getBoundingClientRect().height / lh);
      if (lines < 3) { ps[i].style.textAlign = 'start'; ragged++; }
    }
    return ragged;
  }

  function outerHeight(el) {
    var r = el.getBoundingClientRect();
    var cs = getComputedStyle(el);
    if (cs.display === 'none') return 0;
    return r.height + parseFloat(cs.marginBottom || 0) + parseFloat(cs.marginTop || 0);
  }

  window.__layout = function () {
    fitRows();
    var groups = syncRows();
    var switched = matchFallback(groups);
    if (switched.length) { fitRows(); groups = syncRows(); }
    var ragged = justify();
    return { groups: groups, verticalFallback: switched, raggedParagraphs: ragged };
  };

  window.__measure = function () {
    var blocks = [];
    var kids = document.querySelectorAll('main > *');
    for (var i = 0; i < kids.length; i++) {
      var el = kids[i];
      var h = outerHeight(el);
      if (h === 0) continue;
      var parts = null;
      if (el.classList.contains('splittable')) {
        parts = [];
        var subs = el.querySelectorAll(':scope > .q-head, :scope > .q-body > *');
        for (var j = 0; j < subs.length; j++) parts.push(outerHeight(subs[j]));
      }
      blocks.push({
        id: el.dataset.id || el.className || ('block' + i),
        label: el.dataset.label || '',
        h: h,
        atomic: !el.classList.contains('splittable'),
        parts: parts
      });
    }
    return blocks;
  };
})();

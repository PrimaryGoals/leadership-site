/* Site search: runs entirely in the browser over /assets/search-index.json (built by build.py).
   The index is only downloaded when someone focuses the box or opens /search/. */
(function () {
  'use strict';
  var form = document.querySelector('form.search');
  if (!form) return;
  var input = form.querySelector('input[name=q]');
  var pop = form.querySelector('.search-pop');
  var indexUrl = form.getAttribute('data-index');
  var docs = null, loading = null, active = -1, shown = [];

  function h(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function reEsc(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

  function load() {
    if (docs) return Promise.resolve(docs);
    if (!loading) {
      loading = fetch(indexUrl).then(function (r) {
        if (!r.ok) throw new Error('index ' + r.status);
        return r.json();
      }).then(function (list) {
        docs = list.map(function (d) {
          return { u: d.u, t: d.t, d: d.d, x: d.x, tl: d.t.toLowerCase(), dl: d.d.toLowerCase(), xl: d.x.toLowerCase() };
        });
        return docs;
      });
      loading.catch(function () { loading = null; });
    }
    return loading;
  }

  function terms(q) {
    return (q.toLowerCase().match(/[\p{L}\p{N}]+/gu) || []);
  }

  function wordStart(s, i) { return i === 0 || /[^\p{L}\p{N}]/u.test(s.charAt(i - 1)); }

  function score(d, ts, phrase) {
    var s = 0;
    for (var k = 0; k < ts.length; k++) {
      var t = ts[k];
      var ti = d.tl.indexOf(t), di = d.dl.indexOf(t);
      var c = 0, pos = 0, i;
      while (c < 20 && (i = d.xl.indexOf(t, pos)) !== -1) { c++; pos = i + t.length; }
      if (ti < 0 && di < 0 && c === 0) return 0;      // every word must appear somewhere
      if (ti >= 0) s += 20 + (wordStart(d.tl, ti) ? 10 : 0);
      if (di >= 0) s += 8;
      s += Math.min(c, 10);
    }
    if (ts.length > 1) {
      if (d.tl.indexOf(phrase) >= 0) s += 40;
      else if (d.xl.indexOf(phrase) >= 0) s += 15;
    }
    return s;
  }

  function search(q) {
    var ts = terms(q);
    if (!ts.length) return { ts: ts, hits: [] };
    var phrase = ts.join(' ');
    var hits = [];
    for (var i = 0; i < docs.length; i++) {
      var sc = score(docs[i], ts, phrase);
      if (sc) hits.push({ d: docs[i], s: sc });
    }
    hits.sort(function (a, b) { return b.s - a.s || a.d.t.localeCompare(b.d.t); });
    return { ts: ts, hits: hits };
  }

  function highlight(text, ts) {
    if (!ts.length) return h(text);
    var re = new RegExp('(' + ts.map(reEsc).join('|') + ')', 'gi');
    return text.split(re).map(function (p, i) { return i % 2 ? '<mark>' + h(p) + '</mark>' : h(p); }).join('');
  }

  function snippet(d, ts, len) {
    var src = d.d || d.x, low = src.toLowerCase(), at = -1;
    for (var k = 0; k < ts.length && at < 0; k++) at = low.indexOf(ts[k]);
    if (at < 0) { src = d.x; low = d.xl; for (k = 0; k < ts.length && at < 0; k++) at = low.indexOf(ts[k]); }
    if (at < 0) at = 0;
    var start = Math.max(0, at - 60), end = Math.min(src.length, start + len);
    if (start > 0) { var sp = src.indexOf(' ', start); if (sp > -1 && sp < at) start = sp + 1; }
    var out = src.slice(start, end).trim();
    return (start > 0 ? '… ' : '') + highlight(out, ts) + (end < src.length ? ' …' : '');
  }

  /* ---- dropdown under the header box ---- */
  function closePop() {
    pop.hidden = true; pop.innerHTML = ''; active = -1; shown = [];
    input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant');
  }

  function setActive(n) {
    var items = pop.querySelectorAll('[role=option]');
    if (!items.length) return;
    active = (n + items.length) % items.length;
    for (var i = 0; i < items.length; i++) {
      items[i].setAttribute('aria-selected', i === active ? 'true' : 'false');
      items[i].classList.toggle('on', i === active);
    }
    input.setAttribute('aria-activedescendant', items[active].id);
    items[active].scrollIntoView({ block: 'nearest' });
  }

  function renderPop(q) {
    var r = search(q);
    if (!r.ts.length) { closePop(); return; }
    shown = r.hits.slice(0, 8);
    var html = '';
    if (!shown.length) {
      html = '<p class="none">No pages match “' + h(q) + '”.</p>';
    } else {
      shown.forEach(function (x, i) {
        html += '<a role="option" id="sr-' + i + '" aria-selected="false" href="' + h(x.d.u) + '">' +
          '<strong>' + highlight(x.d.t, r.ts) + '</strong><span>' + snippet(x.d, r.ts, 110) + '</span></a>';
      });
      html += '<a class="all" href="/search/?q=' + encodeURIComponent(q) + '">See all ' + r.hits.length +
        ' result' + (r.hits.length === 1 ? '' : 's') + '</a>';
    }
    pop.innerHTML = html;
    pop.hidden = false; active = -1;
    input.setAttribute('aria-expanded', 'true');
  }

  var timer = null;
  function onInput() {
    clearTimeout(timer);
    timer = setTimeout(function () {
      var q = input.value.trim();
      if (!q) { closePop(); return; }
      load().then(function () { if (input.value.trim() === q) renderPop(q); })
            .catch(function () { pop.innerHTML = '<p class="none">Search is unavailable right now.</p>'; pop.hidden = false; });
    }, 120);
  }

  input.addEventListener('focus', function () { load().catch(function () {}); });
  input.addEventListener('input', onInput);
  input.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowDown') { if (!pop.hidden) { e.preventDefault(); setActive(active + 1); } }
    else if (e.key === 'ArrowUp') { if (!pop.hidden) { e.preventDefault(); setActive(active < 0 ? -1 : active - 1); } }
    else if (e.key === 'Escape') { closePop(); }
    else if (e.key === 'Enter' && active >= 0) {
      var items = pop.querySelectorAll('[role=option]');
      if (items[active]) { e.preventDefault(); window.location.href = items[active].getAttribute('href'); }
    }
  });
  document.addEventListener('click', function (e) { if (!form.contains(e.target)) closePop(); });
  form.addEventListener('focusout', function () {
    setTimeout(function () { if (!form.contains(document.activeElement)) closePop(); }, 0);
  });

  /* ---- the /search/ results page ---- */
  var box = document.getElementById('search-results');
  if (box) {
    var status = document.getElementById('search-status');
    var params = new URLSearchParams(window.location.search);
    var render = function (q) {
      document.title = (q ? 'Search: ' + q : 'Search') + ' – Primary Goals';
      if (!q.trim()) { status.textContent = 'Type a word or phrase in the search box.'; box.innerHTML = ''; return; }
      status.textContent = 'Searching…';
      load().then(function () {
        var r = search(q), hits = r.hits.slice(0, 100), out = '';
        status.textContent = r.hits.length ? r.hits.length + ' result' + (r.hits.length === 1 ? '' : 's') +
          ' for “' + q + '”' + (r.hits.length > hits.length ? ' (showing the first ' + hits.length + ')' : '')
          : 'No pages match “' + q + '”. Try fewer or different words, or browse the site map.';
        hits.forEach(function (x) {
          out += '<article class="hit"><h2><a href="' + h(x.d.u) + '">' + highlight(x.d.t, r.ts) + '</a></h2>' +
            '<p class="meta">' + h(x.d.u) + '</p><p>' + snippet(x.d, r.ts, 240) + '</p></article>';
        });
        box.innerHTML = out;
      }).catch(function () { status.textContent = 'Search is unavailable right now. Please try again, or use the site map.'; });
    };
    var q0 = params.get('q') || params.get('s') || '';
    input.value = q0;
    render(q0);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var q = input.value.trim();
      history.replaceState(null, '', '/search/' + (q ? '?q=' + encodeURIComponent(q) : ''));
      closePop();
      render(q);
    });
  }
})();

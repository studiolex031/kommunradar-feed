/* Kommunradar – skicka med det besökaren redan skrivit till Stripe-kassan.
 *
 * När någon klickar på en köpknapp (en buy.stripe.com-länk, [data-buy], [data-checkout] eller
 * "Få alla i mejlen – gratis") tar vi bevakningsord, län och e-post som redan finns på sidan –
 * hero-sökningen, demoformuläret "Visa mina missade upphandlingar" eller gate-mejlrutan – och ber
 * /api/checkout.php om en kassa där de är ifyllda. Svarar servern inte inom 5 sekunder, eller fel,
 * går besökaren till den vanliga betallänken precis som förut. Inget köp kan alltså tappas.
 */
(function () {
  'use strict';
  if (window.__krPrefill) return;
  window.__krPrefill = 1;

  var CFG = window.KOMMUNRADAR || {};
  var API = CFG.checkoutPrefillUrl || '/api/checkout.php';
  var STORE = 'kr_prefill_v1';
  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  // localStorage så att sökningen följer med även efter omladdning, bakåtknapp eller ny flik.
  function load() { try { return JSON.parse(localStorage.getItem(STORE) || '{}') || {}; } catch (e) { return {}; } }
  function save(v) { try { localStorage.setItem(STORE, JSON.stringify(v)); } catch (e) {} }
  function val(sel) { var el = document.querySelector(sel); return el && typeof el.value === 'string' ? el.value.trim() : ''; }

  // Demoformuläret skickas via fetch – kom ihåg vad som angavs, även om sidan laddas om.
  document.addEventListener('submit', function (e) {
    var f = e.target;
    if (!f || f.id !== 'kr-demo-form') return;
    var s = load(), fd = new FormData(f), mail = '';
    fd.forEach(function (v, k) { if (!mail && /mail/i.test(k) && EMAIL_RE.test(String(v).trim())) mail = String(v).trim(); });
    if (fd.get('nyckelord')) s.keywords = String(fd.get('nyckelord'));
    if (fd.get('lan')) s.lan = String(fd.get('lan'));
    if (mail) s.email = mail;
    save(s);
  }, true);

  // Hero-sökningen och mejlrutan: kom ihåg det besökaren skriver, så det följer med när de sedan väljer pris.
  function remember(e) {
    var el = e.target;
    if (!el || !el.id) return;
    var s = load(), v = typeof el.value === 'string' ? el.value.trim() : '';
    if (el.id === 'q') { if (v) s.keywords = v; else delete s.keywords; }
    else if (el.id === 'lan') { s.lan = v || 'Hela Sverige'; }
    else if (el.id === 'gatemail' && EMAIL_RE.test(v)) { s.email = v; }
    else return;
    save(s);
  }
  document.addEventListener('input', remember, true);
  document.addEventListener('change', remember, true);

  function collect() {
    var s = load();
    var email = val('#gatemail') || val('#kr-demo-form input[type=email]') || s.email || '';
    var keywords = val('#q') || val('#kr-demo-form [name=nyckelord]') || s.keywords || '';
    var lan = val('#lan') || val('#kr-demo-form [name=lan]') || s.lan || '';
    // I hero-sökningen betyder tomt län "Hela Sverige" – fråga inte om det igen när sökord finns.
    if (!lan && keywords && document.getElementById('lan')) lan = 'Hela Sverige';
    return { keywords: keywords, lan: lan, email: EMAIL_RE.test(email) ? email : '' };
  }

  function withEmail(link, email) {
    return email ? link + (link.indexOf('?') < 0 ? '?' : '&') + 'prefilled_email=' + encodeURIComponent(email) : link;
  }

  // Visar direkt att något händer, och återställs när man kommer tillbaka med bakåtknappen
  // (annars låg knappen kvar "upptagen" och nästa klick gjorde ingenting).
  var busyUntil = 0, busyEl = null;
  function setBusy(el) {
    busyUntil = Date.now() + 8000;
    busyEl = el || null;
    if (busyEl) {
      busyEl.setAttribute('aria-busy', 'true');
      busyEl.dataset.krText = busyEl.dataset.krText || busyEl.textContent;
      busyEl.textContent = 'Öppnar kassan…';
    }
  }
  function clearBusy() {
    busyUntil = 0;
    if (busyEl) {
      busyEl.removeAttribute('aria-busy');
      if (busyEl.dataset.krText) busyEl.textContent = busyEl.dataset.krText;
      delete busyEl.dataset.krText;
    }
    busyEl = null;
  }
  window.addEventListener('pageshow', clearBusy);

  function go(link, el) {
    var v = collect();
    if (!v.keywords && !v.lan && !v.email) { location.href = link; return; }
    if (Date.now() < busyUntil) return;
    setBusy(el);
    var fallback = function () { location.href = withEmail(link, v.email); setTimeout(clearBusy, 3000); };
    var ctrl = window.AbortController ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, 5000);
    fetch(API, {
      method: 'POST', credentials: 'same-origin', signal: ctrl ? ctrl.signal : undefined,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ link: link, keywords: v.keywords, lan: v.lan, email: v.email, website: val('[name=website]') })
    }).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
      clearTimeout(timer);
      if (d && typeof d.url === 'string' && d.url.indexOf('https://checkout.stripe.com/') === 0) {
        if (window.gtag) gtag('event', 'checkout_prefilled');
        location.href = d.url;
        setTimeout(clearBusy, 4000);
      } else fallback();
    }).catch(function () { clearTimeout(timer); fallback(); });
  }

  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var t = e.target.closest ? e.target : e.target.parentElement;
    if (!t) return;

    // "Få alla i mejlen – gratis": gratis veckobrev med e-post från rutan.
    if (t.closest('#gatego')) {
      if (!CFG.freeLink || !EMAIL_RE.test(val('#gatemail'))) return; // sidans egen felhantering tar över
      e.preventDefault(); e.stopImmediatePropagation();
      go(CFG.freeLink, t.closest('#gatego'));
      return;
    }

    var a = t.closest('a[href^="https://buy.stripe.com/"], [data-buy], [data-checkout]');
    if (!a) return;
    var href = a.getAttribute('href') || '';
    var link = /^https:\/\/buy\.stripe\.com\/[A-Za-z0-9]+$/.test(href.split('?')[0]) ? href.split('?')[0] : CFG.paymentLink;
    if (!link) return;
    e.preventDefault(); e.stopImmediatePropagation();
    go(link, a);
  }, true);
})();

/* Kommunradar – skicka med det besökaren redan skrivit till Stripe-kassan.
 *
 * När någon klickar på en köpknapp (en buy.stripe.com-länk, [data-buy], [data-checkout] eller
 * "Få alla i mejlen – gratis") tar vi bevakningsord, län och e-post som redan finns på sidan –
 * hero-sökningen, demoformuläret "Visa mina missade upphandlingar" eller gate-mejlrutan – och ber
 * /api/checkout.php om en kassa där de är ifyllda. Svarar servern inte inom 6 sekunder, eller fel,
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

  function load() { try { return JSON.parse(sessionStorage.getItem(STORE) || '{}') || {}; } catch (e) { return {}; } }
  function save(v) { try { sessionStorage.setItem(STORE, JSON.stringify(v)); } catch (e) {} }
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

  var busy = false;
  function go(link, el) {
    var v = collect();
    if (!v.keywords && !v.lan && !v.email) { location.href = link; return; }
    if (busy) return;
    busy = true;
    if (el) { el.setAttribute('aria-busy', 'true'); el.style.opacity = '.6'; }
    var fallback = function () { busy = false; location.href = withEmail(link, v.email); };
    var ctrl = window.AbortController ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, 6000);
    fetch(API, {
      method: 'POST', credentials: 'same-origin', signal: ctrl ? ctrl.signal : undefined,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ link: link, keywords: v.keywords, lan: v.lan, email: v.email, website: val('[name=website]') })
    }).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
      clearTimeout(timer);
      if (d && typeof d.url === 'string' && d.url.indexOf('https://checkout.stripe.com/') === 0) {
        if (window.gtag) gtag('event', 'checkout_prefilled');
        location.href = d.url;
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

// Fills company details from config.js into [data-co] fields and shows a clear warning while they are empty.
(function () {
  var c = (window.KOMMUNRADAR || {}).company || {};
  var labels = { name: 'företagsnamn', orgnr: 'organisationsnummer', email: 'e-post', phone: 'telefon', address: 'adress' };
  document.querySelectorAll('[data-co]').forEach(function (el) {
    var k = el.getAttribute('data-co'), v = c[k];
    if (v) {
      el.textContent = v;
      if (k === 'email' && el.tagName === 'A') el.href = 'mailto:' + v;
    } else if (el.hasAttribute('data-optional')) {
      (el.closest('[data-row]') || el).remove();
    } else {
      el.textContent = '[fyll i ' + labels[k] + ' i config.js]';
      el.style.cssText += ';background:#fde68a;color:#111;padding:0 4px;border-radius:4px';
    }
  });
  var portal = (window.KOMMUNRADAR || {}).portalUrl;
  document.querySelectorAll('[data-portal]').forEach(function (el) { if (portal) el.href = portal; else el.removeAttribute('href'); });
  // Knapp "Ändra bevakning" till kundpanelen, i sidhuvudet bredvid köpknappen och i sidfoten.
  var head = document.querySelector('header');
  if (head && !head.querySelector('[data-konto]')) {
    var b = document.createElement('a');
    b.href = '/konto/'; b.className = 'btn sm'; b.setAttribute('data-konto', ''); b.textContent = 'Ändra bevakning';
    b.style.cssText = 'margin-left:auto;margin-right:8px;white-space:nowrap;background:transparent;border:1px solid currentColor';
    var buy = head.querySelector('[data-buy]');
    head.insertBefore(b, buy || null);
  }
  document.querySelectorAll('[data-portal]').forEach(function (el) {
    if (el.parentNode.querySelector('[data-konto]')) return;
    var a = document.createElement('a'); a.href = '/konto/'; a.setAttribute('data-konto', ''); a.textContent = 'Ändra bevakning';
    el.parentNode.insertBefore(document.createTextNode(' · '), el); el.parentNode.insertBefore(a, el.previousSibling);
  });
})();

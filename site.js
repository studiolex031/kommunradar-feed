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
})();

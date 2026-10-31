// ===== FYLL I INNAN PUBLICERING =====
// paymentLink: länken som scripts/stripe_setup.py skriver ut (https://buy.stripe.com/...)
// company: era riktiga uppgifter — visas i sidfoten, villkoren och integritetspolicyn (krävs av Stripe).
window.KOMMUNRADAR = {
  paymentLink: '',
  trialDays: 7,
  portalUrl: '',            // Stripe kundportal (Settings → Billing → Customer portal → länk)
  company: {
    name: '',               // t.ex. "Freeline AB" eller "Förnamn Efternamn (enskild firma)"
    orgnr: '',              // organisationsnummer
    email: '',              // t.ex. "hej@kommunradar.online"
    phone: '',              // valfritt
    address: ''             // postadress, t.ex. "Gatan 1, 123 45 Staden"
  }
};

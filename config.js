// ===== FYLL I INNAN PUBLICERING =====
// paymentLink: länken som scripts/stripe_setup.py skriver ut (https://buy.stripe.com/...)
// company: era riktiga uppgifter — visas i sidfoten, villkoren och integritetspolicyn (krävs av Stripe).
window.KOMMUNRADAR = {
  paymentLink: 'https://buy.stripe.com/dRm6oGbwc7QL1QF5agg7e01',
  trialDays: 0,  // den här betallänken har ingen provperiod — sätt samma antal dagar som länken har
  portalUrl: 'https://billing.stripe.com/p/login/6oUdR80Ry8UP9j7dGMg7e00',
  company: {
    name: 'Kommunradar / Alexander Pålsson (enskild firma)',
    orgnr: '19870929-3552',
    email: 'freeline031@gmail.com',
    phone: '+46 72 012 78 76',
    address: 'Rävebergsvägen 130P, 424 67 Angered'
  }
};

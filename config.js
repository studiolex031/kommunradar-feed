// ===== FYLL I INNAN PUBLICERING =====
// paymentLink: länken som scripts/stripe_setup.py skriver ut (https://buy.stripe.com/...)
// company: era riktiga uppgifter — visas i sidfoten, villkoren och integritetspolicyn (krävs av Stripe).
window.KOMMUNRADAR = {
  paymentLink: 'https://buy.stripe.com/00weVc9o4gnh0MB8msg7e02',
  trialDays: 7,  // samma antal provdagar som betallänken har (Stripe-uppsättningen skriver ut båda)
  portalUrl: 'https://billing.stripe.com/p/login/6oUdR80Ry8UP9j7dGMg7e00',
  company: {
    name: 'Kommunradar / Alexander Pålsson (enskild firma)',
    orgnr: '19870929-3552',
    email: 'freeline031@gmail.com',
    phone: '+46 72 012 78 76',
    address: 'Rävebergsvägen 130P, 424 67 Angered'
  }
};

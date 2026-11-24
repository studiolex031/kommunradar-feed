// ===== FYLL I INNAN PUBLICERING =====
// paymentLink: länken som scripts/stripe_setup.py skriver ut (https://buy.stripe.com/...)
// company: era riktiga uppgifter — visas i sidfoten, villkoren och integritetspolicyn (krävs av Stripe).
window.KOMMUNRADAR = {
  paymentLink: 'https://buy.stripe.com/00weVc9o4gnh0MB8msg7e02',
  trialDays: 7,  // samma antal provdagar som betallänken har (Stripe-uppsättningen skriver ut båda)
  checkoutApiEnabled: false,  // aktiveras först när serverfunktionen är driftsatt och verifierad
  checkoutApiUrl: '/api/create-checkout-session',
  founderLink: 'https://buy.stripe.com/7sYeVcbwc5ID9j7fOUg7e03',  // grundarpris 490 kr/mån, 7 dagar innan första dragningen, 20 platser
  blackWeekLink: 'https://buy.stripe.com/3cI6oGbwc3Avcvj6ekg7e09',  // 4 900 kr första året, betalas direkt, 10 platser
  blackWeekEnds: '2026-11-30',  // sista dagen erbjudandet visas (outbound läser detta)
  freeLink: 'https://buy.stripe.com/8x2dR857O1sn7aZ0U0g7e05',  // gratis veckobrev (0 kr, inget kort)
  portalUrl:'https://billing.stripe.com/p/login/6oUdR80Ry8UP9j7dGMg7e00',
  company: {
    name: 'Kommunradar / Alexander Pålsson (enskild firma)',
    orgnr: '19870929-3552',
    email: 'hej@kommunradar.online',
    phone: '+46 72 012 78 76',
    address: 'Rävebergsvägen 130P, 424 67 Angered'
  }
};

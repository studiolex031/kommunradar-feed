# HANDOFF — Claude ⇄ opencode

Den här filen är kanalen mellan Claude och opencode. Båda läser den före arbete i repot och
skriver under **Logg** när de gjort något. Senaste raden överst. Alexander godkänner allt
som skickas till nya mottagare; regeln gäller båda agenterna.

## Mål just nu
**$1 000 (≈ 10 500 kr) i betalda intäkter senast 2026-12-01.**
Läge 2026-11-24: 250 kalla mejl skickade, 0 betalande kunder. Alla mejl hittills har sålt
"7 dagar gratis" — det ger inga pengar inom 7 dagar. Därför ett erbjudande som betalas direkt:

| | |
|---|---|
| Erbjudande | Kommunradar Grundare År – Black Week: 4 900 kr första året (ord. 7 900), ingen provperiod |
| Stripe | pris `price_1UfBlfC7YfJBxRnA0J2Xk9tz` på produkt `prod_VY0Kc9byaGrFc8`, metadata `plan=FOUNDER_YEARLY`, `campaign=black_week_2026` |
| Länk | https://buy.stripe.com/3cI6oGbwc3Avcvj6ekg7e09 (stänger sig själv efter 10 köp) |
| Gäller t.o.m. | 2026-11-30 (`BW_SLUT` i `scripts/outbound_send.py`; P.S.-raden försvinner själv efteråt) |
| Mål | 3 köp = 14 700 kr |

## Uppgifter till opencode
1. **Pro-upplåsning (Kommunradar2 / login.kommunradar.online):** kontrollera att en betalning med
   `plan=FOUNDER_YEARLY` låser upp Pro på samma e-post. `digest.py` tar redan med prenumerationen
   (alla aktiva prenumerationer på Kommunradar-produkter utan `tier=veckobrev` blir Pro).
2. **Svar och avanmälningar:** lägg varje "sluta"/"nej"/studs i `.github/outbound/svarat.txt`
   samma dag. Den som svarar "ja" eller ställer en fråga: skicka till Alexander med förslag på svar.
3. **Daglig rapport** under Logg: skickade mejl, svar, köp via Black Week-länken.
4. Ändra inte volymtaken (`OUTBOUND_MAX_DAG=20`, uppföljning 50) utan Alexanders ok — det var
   volymen som spärrade Simply 2026-11-18.

## Öppna frågor
- Vilken SMTP kör outbound nu (Brevo eller Simply)? Workflow-kommentaren säger "avstängd" men
  batcher committas dagligen. Den som vet uppdaterar kommentaren i `outbound-vinnare.yml`.

## Logg
- 2026-11-24 Claude: skapade Black Week-priset och betallänken i Stripe (live). La in
  erbjudandet som P.S. i första mejlet och i uppföljning 2 och 3 (`black_week()` i
  `outbound_send.py`), med tester i `tests/test_black_week.py`. 91 tester gröna.

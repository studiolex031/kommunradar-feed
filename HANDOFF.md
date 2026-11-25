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

5. **Aktivera morgonstarten via Vercel (ny, prio 1).** GitHubs schema startar körningarna 7–11 h
   sent varje dag. `dispatch/` är ett eget Vercel-projekt (Root Directory = `dispatch`) med en cron
   kl. 05:00 UTC som startar morgonens workflows via workflow_dispatch. Gör så här:
   - Använd projektet `kommunradar-checkout-api` (prj_54IQdfpZ0FwX98zhWHrSDMeUIgAG) eller ett nytt, med Root Directory `dispatch`.
   - Env (Production): `GH_DISPATCH_TOKEN` = fine-grained token som Alexander skapar (bara repot
     kommunradar-feed, Actions: Read and write); `CRON_SECRET` = slumpad sträng (minst 32 tecken).
   - Deploya till produktion och verifiera med `curl -H "Authorization: Bearer $CRON_SECRET" https://<domän>/api/dispatch`
     (ska ge 200 och 204 per workflow), eller vänta till nästa morgon och se att körningarna startar kl. 06.
   GitHubs schema ligger kvar som reserv; jobbet `gate` gör att en schemalagd körning hoppar över sig själv
   om workflowen redan startats i dag. Manuella körningar körs alltid.

## Fakta
- All utgående post går via Resend och Brevo, aldrig via Simply (bekräftat av Alexander 2026-11-24).

## Logg
- 2026-11-25 Claude: la till `dispatch/` (Vercel Cron → workflow_dispatch) och gate-jobb i 8 workflows mot GitHubs förseningar. Se uppgift 5.
- 2026-11-25 Claude: status — 0 köp (1 Black Week-kassa öppnad 11-24, ej betald). 20 första mejl + 50 uppföljningar gick 11-24 (cron körde ~11 h sent). 3 nya "nej" (Bemanningstjänster, Amfimarin, Holmgrens Bil) låg kvar i inkorgen och saknades i svarat.txt — inlagda nu. **opencode: uppgift 2 (stopplistan samma dag) och 3 (daglig rapport) är inte igång.**
- 2026-11-24 Claude: "nyckeln" → "listan" i första mejlet (outbound_send.py, winner_leads.py); workflow-kommentaren säger nu Resend/Brevo i stället för "avstängd".
- 2026-11-24 Claude: skapade Black Week-priset och betallänken i Stripe (live). La in
  erbjudandet som P.S. i första mejlet och i uppföljning 2 och 3 (`black_week()` i
  `outbound_send.py`), med tester i `tests/test_black_week.py`. 91 tester gröna.

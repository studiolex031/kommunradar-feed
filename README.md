# Kommunradar

Offentliga upphandlingar i inkorgen varje morgon — filtrerade på kundens bransch och län. 990 kr/mån.

Hela tjänsten körs utan egen server:

| Del | Vad den gör |
|---|---|
| `feed.py` | Hämtar svenska TED-notiser från de senaste 45 dagarna (EU:s gratis API, högst 40 × 100 notiser), behåller öppna anbudsförfrågningar, lägger till län, kategori och uppskattat värde → `leads.json` |
| `index.html` | Säljsida med live-sök: besökaren skriver sin bransch och ser hur många affärer som finns just nu (3 visas, resten låses bakom köpknappen) |
| Stripe Payment Link | Prenumerationen. Kunden anger bevakningsord och län i kassan. **Stripe är kundregistret.** |
| `digest.py` | Körs varje morgon av GitHub Actions: hittar nya upphandlingar och mejlar varje aktiv prenumerant och provprenumerant sina träffar |
| Gratis veckobrev | `veckobrev.html` → Stripe-länk för 0 kr/mån utan kort (`freeLink` i config.js) → `tack-veckobrev.html`. Morgonen efter anmälan skickar `digest.py` senaste veckans träffar; sedan varje måndag via workflowen *kommunradar-veckobrev* (`digest.py --weekly`). Visar de 10 största träffarna och länkar till Pro (variabel `PRO_URL`, standard `SITE_URL/#pris`). Produkten har metadata `tier=veckobrev`, så gratisprenumeranter får aldrig de dagliga Pro-mejlen eller provmejlen, och den som har Pro får inget veckobrev. Skapas med workflowen *Stripe-uppsättning* med "veckobrev" ikryssat |
| `radar.html` | Den tidigare interna vyn (Peppol-poäng), oförändrad |
| Provmejl | `digest.py` mejlar den som provar dag 1 (välkommen och tips), dag 3 (får du rätt träffar?) och dag 6 (testet slutar i morgon). Bara prenumerationer som fortfarande provar får mejlen. Svar går till `REPLY_TO` (standard hej@kommunradar.online) |
| `scripts/winner_leads.py` | Säljleads: bolag som nyss vann en svensk upphandling, med kontaktadressen de angav i TED. Workflowen *vinnar-leads* mejlar listan till secret `REPORT_TO` varje vardag 06:30. Listan checkas aldrig in, eftersom repot är publikt |
| `scripts/x_daily.py` | Ett eget X-inlägg varje vardag 07:41 (workflow *x-dagligt*): gårdagens nya upphandlingar i ett län eller en bransch, med bild i sajtens stil (1200×675 och 1080×1080 för annons). Postar om secrets `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET` finns, och mejlar inlägg, bilder och annonstexter till `REPORT_TO` |
| `scripts/x_mentions.py` | Varannan timme på vardagar (workflow *x-omnamnanden*): nya omnämnanden av kontot mejlas till `REPORT_TO`. Svarar aldrig själv, eftersom X sedan feb 2026 stoppar automatiska svar och varje svar ska godkännas |

## Lansera (ca 20 min)

1. **Publicera sajten** — ladda upp filerna till webbhotellet (t.ex. Simply.com). Sajten hämtar själv morgonens `leads.json` från GitHub, så ingen FTP behövs; FTP-hemligheterna är valfria.
2. **Stripe**:
   ```bash
   STRIPE_SECRET_KEY=sk_test_... python scripts/stripe_setup.py --site https://<din-sajt> --trial-days 7
   ```
   Klistra in den utskrivna länken som `paymentLink` och samma antal provdagar som `trialDays` i `config.js`. Kör om med `sk_live_...` när du testat.
   Aktivera kundportalen (Dashboard → Settings → Billing → Customer portal) Är du momsregistrerad: lägg in registreringen under Stripe → Tax och kör uppsättningen med moms ikryssat.
3. **GitHub → Settings → Secrets and variables → Actions**
   - Secrets: `STRIPE_SECRET_KEY` (för det dagliga utskicket räcker en restricted key med läsrätt på Products, Prices, Subscriptions, Customers och Checkout Sessions; Stripe-uppsättningen behöver skrivrätt på Products, Prices och Payment Links), `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `MAIL_FROM`
   - Variables: `SITE_URL`, `PORTAL_URL`
4. **Testa**: köp med testkort `4242 4242 4242 4242`, kör sedan workflowen *kommunradar-daily* manuellt.
   Lokalt: `python digest.py --prev prev.json --dry-run`.

Ändra en kunds bevakning: sätt metadata `keywords` / `lan` på prenumerationen i Stripe (går före svaren från kassan).

## Tester
```bash
python -m unittest discover -s tests
```

## Begränsningar
TED innehåller upphandlingar **över EU:s tröskelvärden**. Mindre upphandlingar publiceras i nationella annonsdatabaser
som kräver avtal — nästa steg för större täckning. `leads.json` är publik (datan är offentlig); värdet för kunden
är filtreringen och leveransen varje morgon.

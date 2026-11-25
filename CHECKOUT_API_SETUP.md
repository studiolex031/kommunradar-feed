# Serverbaserad Stripe Checkout – driftsättningsnoteringar

## Vad koden gör

- Skapar en Stripe Checkout Session på serversidan först när kunden trycker på en köpknapp.
- Tar emot bevakningsord och valt län från den befintliga sökrutan.
- Sparar keywords och lan direkt på prenumerationens metadata, vilket är det format som digest.py redan läser.
- Tar bort behovet av att kunden fyller i samma bevakningsord och län en gång till i Stripe.
- Kontrollerar Stripe-priset vid varje checkout-försök: aktiv produkt, 99000 öre, SEK, månadsvis återkommande pris.
- Behåller 7 dagars provperiod, krav på betalningsmetod, obligatorisk faktureringsadress, villkorsgodkännande och valfri skatte-ID-insamling.
- Skapar inga kunder, prenumerationer eller betalningar förrän en besökare uttryckligen skickar checkout-förfrågan.

## Viktig driftbegränsning

Den nuvarande webbplatsen publiceras som statiska filer via FTP. En FTP-publicering kör inte Python-funktionen i api/create-checkout-session.py.

Vercel-kontot hade vid granskningen ett projekt med namnet kommunradar, men det projektet hade inga driftsättningar, ingen domän och inga miljövariabler. Den här PR:en kopplar inte om domänen, flyttar inte webbplatsen och driftsätter ingenting.

För att aktivera checkout krävs en separat serverless-host för API-funktionen eller en kontrollerad migrering av sajten till en plattform som kan köra Vercel Python Functions. Välj först hostingväg och verifiera att den inte medför nya kostnader eller påverkar den befintliga FTP-sajten.

## Miljövariabler – endast på serversidan

| Variabel | Värde |
|---|---|
| STRIPE_SECRET_KEY | Begränsad Stripe-nyckel med läsrätt för Prices/Products och skrivrätt för Checkout Sessions. Aldrig i config.js eller webbläsaren. |
| STRIPE_PRO_PRICE_ID | Befintligt aktivt pris för Kommunradar Pro. Måste vara exakt 990 SEK/mån. |
| STRIPE_EXPECT_LIVE | true i produktion. Testnycklar avvisas då. |
| CHECKOUT_ALLOWED_ORIGINS | https://kommunradar.online |

Sätt inte en live-nyckel i en previewmiljö. För testning används en separat testnyckel och ett separat testpris samt STRIPE_EXPECT_LIVE=false.

## Aktivering av frontend

config.js har checkoutApiEnabled: false som standard. Den befintliga Payment Link-vägen fortsätter därför fungera oförändrad tills API:t har driftsatts och verifierats.

Efter att API:t är driftsatt:
1. Sätt checkoutApiEnabled: true.
2. Om API:t ligger på annan origin än webbplatsen, sätt checkoutApiUrl till dess fullständiga HTTPS-adress.
3. Lägg till webbplatsens origin i API:ts CHECKOUT_ALLOWED_ORIGINS.
4. Testa i Stripe testläge med ett testpris först.
5. Verifiera att checkout.session.completed skapar en prenumeration med metadata keywords och lan, och att digest.py läser dessa värden.
6. Gör ingen liveaktivering innan pris, villkor, faktureringsadress, provperiod och uppsägning har verifierats.

## Säkerhet och begränsningar

- Stripe-hemligheten används endast i serverfunktionen.
- Endast tillåten Origin accepteras; input valideras och begränsas.
- Ett honeypotfält och en enkel tidskontroll finns.
- Funktionen har en processlokal hastighetsbegränsning. Den är endast ett extra skydd och inte en distribuerad rate limiter i serverless-miljö. Plattformsskydd/rate limiting och övervakning måste konfigureras innan publik aktivering.
- Funktionen loggar inte bevakningsord, e-postadresser eller Stripe-svar.
- Inga Stripe-inställningar, priser, Payment Links, kunder, prenumerationer eller produktionsfiler ändras av den här PR:en.

## Test

Kör:

    python -m unittest discover -s tests -p 'test_checkout_session.py' -v


## Separat Vercel-projekt skapat (2026-11-18)

Ett fristående Vercel-projekt har skapats för API:t:

- Projektnamn: `kommunradar-checkout-api`
- Project ID: `prj_54IQdfpZ0FwX98zhWHrSDMeUIgAG`
- Region för serverless-funktioner: Frankfurt (`fra1`)
- Automatisk Git-koppling: inte konfigurerad
- Anpassad domän: ingen
- Miljövariabler: inga
- Deployments: 0

Projektets standarddomän `kommunradar-checkout-api.vercel.app` finns reserverad av Vercel, men det finns ingen deployment bakom den ännu.

Git-repot har avsiktligt inte kopplats in. Att koppla en repo med `main` som produktionsgren kan utlösa automatiska byggen/deployments när framtida commits kommer in. Innan Git-koppling bör produktionsgrenen och deployment-policy ställas in så att endast en uttryckligen vald preview-branch kan byggas.

Projektet har skapats utan att koppla domän, lägga till hemligheter, ändra den befintliga sajten eller starta en deployment. Ingen användningsbaserad serverkörning har startats.

## Förifylld kassa på Simply (2026-11-25) – ersätter Vercel-vägen ovan

Sajten kör PHP på Simply, så kassan skapas nu där i stället: `api/checkout.php` + `checkout-prefill.js`,
publicerade av workflowet `checkout-forifylld`. Ingen ny hosting och ingen ändring av betallänkarna.

- Klick på en köpknapp (buy.stripe.com-länk, `[data-buy]`, `[data-checkout]`, gate-knappen "Få alla i mejlen")
  skickar bevakningsord, län och e-post som redan finns på sidan (hero-sökningen, demoformuläret, gate-mejlrutan).
- PHP slår upp betallänken i Stripe och skapar en Checkout Session med samma pris, provperiod, villkor, rabattkoder,
  text och tack-sida – men utan frågorna om bevakningsord/län när de redan är besvarade. Svaren sparas som
  `metadata[keywords]`/`metadata[lan]` på prenumerationen, som `digest.py` redan läser först.
- Begränsade länkar (grundarpris, Black Week) räknar både länkens egna köp och förifyllda köp mot platstaket.
- Svarar API:t inte inom 6 s eller med fel går besökaren till den vanliga betallänken (med e-posten ifylld).
- Nyckel: secret `STRIPE_CHECKOUT_KEY` om den finns (rekommenderas: begränsad nyckel med läsrätt på Payment Links
  och skrivrätt på Checkout Sessions), annars `STRIPE_SECRET_KEY`. Den skrivs till `kommunradar-private/` utanför
  public_html.
- Ta bort: radera `<!--cp:s-->…<!--cp:e-->` från live-startsidan, så gäller betallänkarna som förut.

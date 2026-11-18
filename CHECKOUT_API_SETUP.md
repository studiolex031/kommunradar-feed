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

    python -m unittest tests/test_checkout_session.py

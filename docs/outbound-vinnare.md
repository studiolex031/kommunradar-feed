# Outbound till upphandlingsvinnare — runbook

Kod: `scripts/outbound_campaign.py` (kedjan), `scripts/outbound_guard.py` (spärrarna),
`scripts/leadfilter.py` (målgrupp), `scripts/winner_leads.py` (TED-källan).
Workflow: `.github/workflows/outbound-vinnare.yml`. Tester: `tests/test_outbound_campaign.py`.

## NÖDSTOPP (gör ett av dessa, snabbast först)

1. **Repo-variabel:** Settings → Secrets and variables → Actions → Variables → sätt
   `OUTBOUND_ENABLED` till `false`. Gäller från nästa körning.
   CLI: `gh variable set OUTBOUND_ENABLED --body false -R studiolex031/kommunradar-feed`
2. **Avbryt en pågående körning:** `gh run list -w outbound-vinnare -R studiolex031/kommunradar-feed`,
   sedan `gh run cancel <id>`. Mejl som redan gått står i state; resten skickas inte.
3. **Spärrfil:** `python scripts/outbound_guard.py --stopp "orsak"`, committa
   `.github/outbound/SPARRAD`. Stoppar även de äldre skripten `outbound_send.py`/`followup_send.py`.
   Kampanjen skriver själv samma fil vid leverantörsvarning, studs ≥ 5 % eller ≥ 2 spamklagomål på 7 dagar.
   Ta bort filen för hand först när orsaken är utredd.
4. **Stäng av workflowen:** `gh workflow disable outbound-vinnare -R studiolex031/kommunradar-feed`.

## Innan live (Alexander bekräftar varje punkt)

| Steg | Var |
|---|---|
| Sänddomän, t.ex. `outreach.kommunradar.online`, hos Brevo/Mailgun/Postmark/SES/Resend — aldrig Simply | leverantören + DNS |
| SPF, DKIM och DMARC (`p=none` räcker för start) för sänddomänen, verifierade hos leverantören | DNS |
| Secrets: `OUTREACH_SMTP_HOST`, `OUTREACH_SMTP_PORT`, `OUTREACH_SMTP_USER`, `OUTREACH_SMTP_PASS`, `OUTREACH_MAIL_FROM` | Actions secrets |
| Secrets för svarsläsning (inkorgen där svar till hej@kommunradar.online hamnar): `IMAP_HOST`, `IMAP_USER`, `IMAP_PASS` | Actions secrets |
| Valfritt men rekommenderat: `OUTREACH_BREVO_API_KEY` (studs/spam/avanmälan från Brevo). Utan den stannar taket på 20/dag eftersom spamklagomål inte syns | Actions secrets |
| `OUTBOUND_TEST_TO` = din egen adress, för testläget | Actions secrets |
| Kör workflowen med `mode: test` och läs de tre testmejlen | Actions → outbound-vinnare → Run workflow |
| Variabler: `OUTBOUND_WARMUP_START` (första sändningsdag, ÅÅÅÅ-MM-DD), valfritt `OUTBOUND_DKIM_SELECTOR` | Actions variables |
| Sist: `OUTBOUND_ENABLED`, `OUTBOUND_PROSPECT_EMAILS_ENABLED`, `OUTBOUND_APPROVED` = `true` | Actions variables |

`python scripts/outbound_guard.py` med samma miljö visar exakt vad som saknas.

## Hur dagens mejl väljs

1. **Stoppsignaler först:** inkorgen (svar, "STOPP/sluta", studsar; autosvar ignoreras och citerad
   text räknas inte), Brevo-händelser, köp i Stripe (via `client_reference_id` i betallänken eller
   köparens e-post) och `svarat.txt`. Ett svar stoppar alla adresser på samma bolagsdomän.
2. **Tak:** sändningsdag 1–3: 10, dag 4–7: 20, dag 8+: 40 om studs < 3 %, inga spamklagomål och
   inga spärrsignaler. Taket gäller alla mejl samma dag (första mejl + uppföljningar).
3. **Ordning:** mogna uppföljningar först (äldst först), sedan nya leads.
4. **Nya leads:** vinnare de senaste 7 dagarna ur TED (svensk köpare, tilldelningsnotis), med den
   adress som står för vinnaren i notisen. Bort: ogiltig adress, domän utan MX, stora koncerner,
   anbudsavdelningar (bid@, tender@ …), myndigheter, börsbolag (publ), anbudsbyråer, egna adresser,
   stopplistan, alla som fått mejl i det äldre utskicket (`sent.json`), dubbletter på e-post,
   orgnr och bolagsdomän. Personlig adress före sälj-/offertadress före info@ före anbud@.
   Varje lead får en `target_reason`.
5. **Sändning:** 08:30–11:30 svensk tid, 60–180 s slumpad paus mellan mejlen. En egen SMTP-
   anslutning per mejl. Tre avvisade adresser i rad, eller > 10 % i körningen, stoppar allt.

## Sekvensen

| Steg | När | Innehåll |
|---|---|---|
| 1 | dag 1 | Grattis till vinsten hos köparen, smärtpunkten, vad Kommunradar är, antal öppna upphandlingar i bolagets bransch/län ur `leads.json`, en betallänk med pris och vad som ingår, gratis veckobrev som andra val |
| 2 | dag 3 | Kort påminnelse + en verklig öppen upphandling som matchar bransch/län (titel, köpare, sista dag, TED-länk) + samma betallänk |
| 3 | dag 7 | "Vill ni ha en bevakning på [bransch] i [län]?" Veckobrev eller betallänk, sedan avslutad |

Betallänk (exakt en per mejl): Black Week 4 900 kr/år t.o.m. `blackWeekEnds` i `config.js` och
så länge platser finns, annars grundarpris 490 kr/mån, annars 990 kr/mån. Alla mejl har
avsändare, org.nr och adress, varifrån adressen kommer (TED-notisen) med länk till
integritetspolicyn, raden "Svara STOPP/sluta så får du inget mer", `Reply-To: hej@kommunradar.online`
och `List-Unsubscribe`.

## Var state och rapporter finns

- `.github/outbound/kampanj.json` (committas av workflowen): per lead `lead_id` (= e-posthash),
  domänhash, TED-nummer, bransch, län, `target_reason`, `template_version`, `sent_at`,
  `followup1_at`, `followup2_at`, `status`, `stop_reason`. **Inga adresser, namn eller bolagsnamn** —
  repot är publikt. Adressen byggs om från TED vid uppföljning.
- `.github/outbound/sent.json` / `followup.json`: det äldre utskicket, används bara som spärr.
- Daglig rapport: siffror i workflow-sammanfattningen och som artifact `outbound-rapport-*`;
  hela listan med bolag och adresser bara som mejl + CSV till `REPORT_TO`.
- Lead-CSV skrivs aldrig i repot.

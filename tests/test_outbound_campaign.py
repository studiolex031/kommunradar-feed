import email, os, smtplib, sys, tempfile, unittest
from datetime import date, datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import outbound_campaign as C
import outbound_guard as G


def vinnare(epost="anna.berg@smabolaget.se", bolag="Småbolaget AB", **kw):
    r = {"bolag": bolag, "epost": epost, "adresstyp": "personlig", "ort": "Borås", "webb": "",
         "upphandling": "Lokalvård förskolor 2027", "kopare": "Borås stad", "lan": "Västra Götaland",
         "bransch": "Avfall, städ & miljö", "anbud": 4, "vinnare": 1, "ted": "123456-2026",
         "publicerad": "2026-11-20", "orgnr": "", "cpv": "90911200"}
    r.update(kw)
    return r


ÖPPNA = [{"title": "Städtjänster skolor", "buyer": "Alingsås kommun", "regions": ["Västra Götaland"],
          "categories": ["Avfall, städ & miljö"], "deadline": "2099-01-10", "published": "2026-11-22",
          "url": "https://ted.europa.eu/sv/notice/-/detail/1-2026"}]

LIVE_ENV = {"OUTBOUND_ENABLED": "true", "OUTBOUND_PROSPECT_EMAILS_ENABLED": "true", "OUTBOUND_APPROVED": "true",
            "SMTP_HOST": "smtp-relay.brevo.com", "SMTP_PORT": "587", "SMTP_USER": "u", "SMTP_PASS": "p",
            "MAIL_FROM": "alexander@outreach.kommunradar.online", "REPLY_TO": "hej@kommunradar.online",
            "OUTBOUND_WARMUP_START": "2026-11-24", "IMAP_HOST": "imap.x", "IMAP_USER": "u", "IMAP_PASS": "p"}


def dns_ok(*_):
    return {"spf": True, "dmarc": True, "dkim": None}


class Guard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.p = mock.patch.object(G, "SPÄRR_FIL", os.path.join(self.tmp, "SPARRAD"))
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_simply_och_huvuddomanen_ar_forbjudna(self):
        self.assertTrue(G.sänddomän_fel("smtp.simply.com", "a@outreach.kommunradar.online"))
        self.assertTrue(G.sänddomän_fel("smtp-relay.brevo.com", "hej@kommunradar.online"))
        self.assertEqual(G.sänddomän_fel("smtp-relay.brevo.com", "a@outreach.kommunradar.online"), [])

    def test_live_kraver_alla_flaggor_dns_och_svarslasning(self):
        live, fel, _ = G.läge(LIVE_ENV, dns=dns_ok)
        self.assertTrue(live, fel)
        for saknas in ("OUTBOUND_APPROVED", "IMAP_HOST", "OUTBOUND_WARMUP_START"):
            env = {k: v for k, v in LIVE_ENV.items() if k != saknas}
            self.assertFalse(G.läge(env, dns=dns_ok)[0], saknas)
        self.assertFalse(G.läge(LIVE_ENV, dns=lambda *_: {"spf": True, "dmarc": False, "dkim": None})[0])

    def test_sparrfil_stoppar_live(self):
        G.spärra("test")
        self.assertFalse(G.läge(LIVE_ENV, dns=dns_ok)[0])

    def test_uppvarmningstrappan(self):
        self.assertEqual([G.dagstak(d, "ok") for d in (1, 3, 4, 7, 8, 30)], [10, 10, 20, 20, 40, 40])
        self.assertEqual(G.dagstak(8, "håll"), 20)
        self.assertEqual(G.dagstak(8, "ok", klagomål_kända=False), 20)

    def test_sandningsdag_raknar_dagar_med_utskick(self):
        start = date(2026, 11, 24)
        self.assertEqual(G.sändningsdag([], start, date(2026, 11, 30)), 1)
        self.assertEqual(G.sändningsdag(["2026-11-24", "2026-11-25"], start, date(2026, 11, 30)), 3)

    def test_halsa_stoppar_vid_hog_studs_och_klagomal(self):
        idag = date(2026, 12, 1)
        leads = {str(i): {"sent_at": "2026-11-30T09:00:00", "status": "active"} for i in range(40)}
        self.assertEqual(G.hälsobeslut(G.hälsa(leads, idag))[0], "ok")
        for i in range(2):
            leads[str(i)].update(status="bounced", stopped_at="2026-11-30T10:00:00")
        self.assertEqual(G.hälsobeslut(G.hälsa(leads, idag))[0], "stopp")  # 2/40 = 5 % -> stopp
        leads["1"].update(status="active", stopped_at="")
        self.assertEqual(G.hälsobeslut(G.hälsa(leads, idag))[0], "ok")     # 1/40 = 2,5 % < 3 %
        leads.update({f"x{i}": {"sent_at": "2026-11-30T09:00:00", "status": "active"} for i in range(20)})
        leads["1"].update(status="bounced", stopped_at="2026-11-30T10:00:00")
        self.assertEqual(G.hälsobeslut(G.hälsa(leads, idag))[0], "håll")   # 2/60 = 3,3 %: håll på 20
        leads["9"].update(status="complaint", stopped_at="2026-11-30T10:00:00")
        leads["8"].update(status="complaint", stopped_at="2026-11-30T10:00:00")
        self.assertEqual(G.hälsobeslut(G.hälsa(leads, idag))[0], "stopp")


class Leads(unittest.TestCase):
    def state(self):
        return {"version": 1, "leads": {}, "dagar": {}}

    def test_filtrerar_icp_dubbletter_legacy_och_stopplista(self):
        rader = [vinnare(),
                 vinnare(epost="info@smabolaget.se"),                        # samma bolag
                 vinnare(epost="kalle@peab.se", bolag="Peab Sverige AB"),     # koncern
                 vinnare(epost="info@goteborg.se", bolag="Göteborgs kommun"),  # myndighet
                 vinnare(epost="stopp@ettbolag.se", bolag="Ett Bolag AB"),
                 vinnare(epost="gammal@tvabolag.se", bolag="Två Bolag AB"),
                 vinnare(epost="inte-en-adress", bolag="Trasig AB")]
        valda, bort = C.bygg_leads(rader, self.state(), {C.nyckel("gammal@tvabolag.se")},
                                   {C.nyckel("stopp@ettbolag.se")}, mx=lambda d: True)
        self.assertEqual([v["epost"] for v in valda], ["anna.berg@smabolaget.se"])
        orsaker = sorted(o for _, o in bort)
        self.assertIn("redan kontaktad i tidigare utskick", orsaker)
        self.assertIn("stopplistan", orsaker)
        self.assertIn("myndighet eller offentlig aktör", orsaker)
        self.assertIn("ogiltig e-post", orsaker)
        self.assertIn("TED 123456-2026", valda[0]["target_reason"])

    def test_personlig_adress_fore_anbudsadress_och_ingen_mx_hoppas_over(self):
        rader = [vinnare(epost="anbud@a-bolag.se", bolag="A AB", adresstyp="generisk"),
                 vinnare(epost="lisa@b-bolag.se", bolag="B AB"),
                 vinnare(epost="info@dod-doman.se", bolag="C AB", adresstyp="generisk")]
        valda, bort = C.bygg_leads(rader, self.state(), set(), set(), mx=lambda d: d != "dod-doman.se")
        self.assertEqual([v["epost"] for v in valda], ["lisa@b-bolag.se", "anbud@a-bolag.se"])
        self.assertIn("domänen tar inte emot e-post (ingen MX)", [o for _, o in bort])


class Mallar(unittest.TestCase):
    def test_alla_steg_har_optout_avsandare_och_exakt_en_betallank(self):
        r = {**vinnare(), "lead_id": "abc"}
        for steg in (1, 2, 3):
            ämne, text, erbj = C.mejl(r, steg, ÖPPNA, date(2026, 12, 5))
            self.assertIn(C.STOPPRAD, text)
            self.assertIn("org.nr", text)
            self.assertIn("TED-notisen 123456-2026", text)
            self.assertEqual(text.count("buy.stripe.com"), 1, text)
            self.assertIn("veckobrev.html", text)
            self.assertEqual(erbj, "grundare")
        self.assertTrue(C.mejl(r, 1, ÖPPNA, date(2026, 12, 5))[0].startswith("Nästa upphandling efter"))

    def test_black_week_bara_till_och_med_slutdatum(self):
        self.assertEqual(C.välj_erbjudande(date(2026, 11, 30))[0], "black_week")
        self.assertEqual(C.välj_erbjudande(date(2026, 12, 1))[0], "grundare")
        self.assertEqual(C.välj_erbjudande(date(2026, 11, 25), slutsålda={"black_week"})[0], "grundare")
        self.assertEqual(C.välj_erbjudande(date(2026, 12, 1), slutsålda={"grundare"})[0], "manad")

    def test_uppfoljning_1_visar_verklig_oppen_upphandling(self):
        _, text, _ = C.mejl({**vinnare(), "lead_id": "abc"}, 2, ÖPPNA, date(2026, 12, 5))
        self.assertIn("Städtjänster skolor, Alingsås kommun", text)
        self.assertIn("2099-01-10", text)

    def test_headers(self):
        msg, _ = C.bygg_meddelande({**vinnare(), "lead_id": "abc"}, 2, ÖPPNA,
                                   "a@outreach.kommunradar.online", "hej@kommunradar.online")
        self.assertEqual(msg["Reply-To"], "hej@kommunradar.online")
        self.assertEqual(msg["List-Unsubscribe"], "<mailto:hej@kommunradar.online?subject=STOPP>")
        self.assertEqual(msg["In-Reply-To"], "<kr-abc-1@outreach.kommunradar.online>")
        self.assertIn("client_reference_id=kr_abc_2", msg.get_content())


def inkommande(text, från="anna.berg@smabolaget.se", ämne="Re: Nästa upphandling", **headers):
    m = email.message.EmailMessage()
    m["From"], m["Subject"] = från, ämne
    for k, v in headers.items():
        m[k.replace("_", "-")] = v
    m.set_content(text)
    return email.message_from_bytes(m.as_bytes())


class Signaler(unittest.TestCase):
    def test_klassning(self):
        self.assertEqual(C.klassa(inkommande("Sluta mejla oss."))[0], "stopp")
        self.assertEqual(C.klassa(inkommande("Låter intressant, berätta mer!"))[0], "intresse")
        self.assertEqual(C.klassa(inkommande("Vi har redan ett system."))[0], "svar")
        self.assertEqual(C.klassa(inkommande("Jag är borta", ämne="Autosvar: borta",
                                             Auto_Submitted="auto-replied"))[0], "auto")
        dsn = inkommande("Final-Recipient: rfc822; anna.berg@smabolaget.se\nAction: failed",
                         från="MAILER-DAEMON@mx.example", ämne="Undeliverable")
        self.assertEqual(C.klassa(dsn), ("studs", ["anna.berg@smabolaget.se"]))

    def test_var_egen_stopprad_i_citatet_raknas_inte(self):
        text = f"Tack, återkommer.\n\nDen 24 nov. 2026 skrev Alexander:\n> {C.STOPPRAD}\n> sluta"
        self.assertEqual(C.klassa(inkommande(text))[0], "svar")

    def test_svar_stoppar_hela_bolaget_studs_bara_adressen(self):
        a, b = "anna.berg@smabolaget.se", "info@smabolaget.se"
        state = {"leads": {C.nyckel(a): {"status": "active", "dh": C.domänhash(a)},
                           C.nyckel(b): {"status": "active", "dh": C.domänhash(b)}}}
        C.tillämpa_signaler(state, [("studs", [a])], None, None, set())
        self.assertEqual(state["leads"][C.nyckel(b)]["status"], "active")
        C.tillämpa_signaler(state, [("stopp", ["vd@smabolaget.se"])], None, None, set())
        self.assertEqual(state["leads"][C.nyckel(b)]["status"], "unsubscribed")
        self.assertEqual(state["leads"][C.nyckel(a)]["status"], "bounced")  # allvarligare status står kvar

    def test_kop_via_client_reference_id(self):
        state = {"leads": {"abc": {"status": "active"}}}
        C.tillämpa_signaler(state, None, None, ({"kr_abc_1"}, set(), set()), set())
        self.assertEqual(state["leads"]["abc"]["status"], "customer")


class Uppfoljning(unittest.TestCase):
    def test_dag_3_och_dag_7_och_aldrig_efter_stopp(self):
        state = {"leads": {
            "a": {"status": "active", "sent_at": "2026-11-24T09:00:00"},
            "b": {"status": "active", "sent_at": "2026-11-20T09:00:00", "followup1_at": "2026-11-23T09:00:00"},
            "c": {"status": "replied", "sent_at": "2026-11-10T09:00:00"},
            "d": {"status": "completed", "sent_at": "2026-11-01T09:00:00"}}}
        self.assertEqual(C.mogna_uppföljningar(state, date(2026, 11, 26)), [])
        self.assertEqual(C.mogna_uppföljningar(state, date(2026, 11, 27)), [("b", 3), ("a", 2)])


class Korning(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patchar = [mock.patch.object(C, "STATE", os.path.join(self.tmp, "kampanj.json")),
                        mock.patch.object(C, "LEGACY_SENT", os.path.join(self.tmp, "sent.json")),
                        mock.patch.object(C, "SVARAT", os.path.join(self.tmp, "svarat.txt")),
                        mock.patch.object(G, "SPÄRR_FIL", os.path.join(self.tmp, "SPARRAD")),
                        mock.patch.object(C, "har_mx", lambda d: True),
                        mock.patch.object(C, "läs_inkorg", lambda: []),
                        mock.patch.object(C, "brevo_händelser", lambda: []),
                        mock.patch.object(C, "stripe_köp", lambda: None),
                        mock.patch.object(G, "dns_status", dns_ok),
                        mock.patch.dict(os.environ, {"OUTBOUND_REPORT_DIR": self.tmp}, clear=False)]
        for p in self.patchar:
            p.start()
        self.rader = [vinnare(epost=f"person{i}@bolag{i}.se", bolag=f"Bolag {i} AB") for i in range(30)]

    def tearDown(self):
        for p in self.patchar:
            p.stop()

    def test_torrkorning_skickar_inget_och_skriver_ingen_state(self):
        with mock.patch.object(C.Sändare, "skicka", side_effect=AssertionError("får inte skicka")):
            self.assertEqual(C.kör([], env={}, hämta=lambda d: self.rader), 0)
        self.assertFalse(os.path.exists(C.STATE))

    def test_live_utan_flaggor_nekas(self):
        env = {k: v for k, v in LIVE_ENV.items() if k != "OUTBOUND_APPROVED"}
        self.assertEqual(C.kör(["--live"], env=env, hämta=lambda d: self.rader), 2)

    def test_live_dag_1_skickar_hogst_10_och_loggar(self):
        skickat = []
        with mock.patch.object(C.Sändare, "skicka", lambda self_, m: skickat.append(m)), \
             mock.patch.object(C, "lokal_tid", lambda: datetime(2026, 11, 24, 9, 0)), \
             mock.patch.object(C, "fönster", lambda nu=None: (datetime(2026, 11, 24, 8, 30),
                                                               datetime(2026, 11, 24, 11, 30))):
            self.assertEqual(C.kör(["--live"], env=LIVE_ENV, hämta=lambda d: self.rader, sov=lambda s: None), 0)
        self.assertEqual(len(skickat), 10)
        state = C.läs_state()
        self.assertEqual(len(state["leads"]), 10)
        l = next(iter(state["leads"].values()))
        self.assertEqual(l["status"], "active")
        self.assertNotIn("epost", l)
        self.assertNotIn("@", str(state))  # inga adresser i den publika state-filen

    def test_leverantorsspärr_stoppar_allt(self):
        def spärr(self_, m):
            raise smtplib.SMTPDataError(554, b"5.7.1 Your account has been blocked")
        with mock.patch.object(C.Sändare, "skicka", spärr), \
             mock.patch.object(C, "lokal_tid", lambda: datetime(2026, 11, 24, 9, 0)), \
             mock.patch.object(C, "fönster", lambda nu=None: (datetime(2026, 11, 24, 8, 30),
                                                               datetime(2026, 11, 24, 11, 30))):
            C.kör(["--live"], env=LIVE_ENV, hämta=lambda d: self.rader, sov=lambda s: None)
        self.assertTrue(G.spärrad())

    def test_testlage_bara_till_egen_adress(self):
        env = {**LIVE_ENV, "REPORT_TO": "alexander@example.se"}
        with mock.patch.object(C.Sändare, "skicka", lambda self_, m: None):
            self.assertEqual(C.kör(["--test-to", "nagon.annan@bolag.se"], env=env, hämta=lambda d: self.rader), 5)
            self.assertEqual(C.kör(["--test-to", "alexander@example.se"], env=env, hämta=lambda d: self.rader), 0)


if __name__ == "__main__":
    unittest.main()

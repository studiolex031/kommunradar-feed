import base64, io, json, os, subprocess, sys, tempfile, unittest, zipfile
from datetime import datetime, timezone
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from leverantorsregistret import cli, data, deliver, state, stripe_sync, xlsx


def svenska(titel, cpv="72000000", plats="SE110", publicerad="2026-11-25", vinnare=None, idn=None, pid=None):
    n = {"publication-number": pid or "123-2026", "publication-date": publicerad,
         "notice-title": {"swe": [titel]}, "buyer-name": {"swe": ["Stockholms stad"]},
         "classification-cpv": [cpv], "place-of-performance": [plats],
         "total-value": 1000000, "total-value-cur": ["SEK"],
         "winner-name": {"swe": vinnare if vinnare is not None else ["Bolag AB"]},
         "winner-identifier": idn if idn is not None else ["5562186790"]}
    return n


class StripeSyncTest(unittest.TestCase):
    def test_active_products_only_and_custom_fields(self):
        sub = {"id": "sub_1", "status": "active", "customer": {"id": "cus_1", "email": "kund@example.se"},
               "metadata": {"app": "leverantorsregistret", "plan": "nya_vinnare"}}
        annan = {"id": "sub_2", "status": "active", "customer": {"id": "cus_2", "email": "annan@example.se"},
                 "metadata": {"app": "kommunradar", "plan": "pro"}}
        fields = [{"key": "bransch", "text": {"value": "cpv72"}},
                  {"key": "lan", "dropdown": {"value": "stockholm"}}]

        def get(path, params=None):
            if path == "products": return {"data": [], "has_more": False}
            if path == "subscriptions": return {"data": [sub, annan], "has_more": False}
            if path == "checkout/sessions": return {"data": [{"custom_fields": fields}]}
            raise AssertionError(path)

        result = stripe_sync.subscribers(get=get)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["email"], "kund@example.se")
        self.assertEqual(result[0]["plan"], "p1")
        self.assertEqual(result[0]["bransch"], "72")
        self.assertEqual(result[0]["lan"], "SE110")
        self.assertEqual(result[0]["customer_id"], "cus_1")

    def test_felpris_filtreras_bort(self):
        sub = {"id": "sub_3", "status": "active",
               "customer": {"id": "cus_3", "email": "fel@example.se"},
               "metadata": {"app": "leverantorsregistret", "plan": "avtal_loper_ut"},
               "items": {"data": [{"price": {"currency": "sek", "unit_amount": 99000,
                                             "recurring": {"interval": "month", "interval_count": 1}}}]}}

        def get(path, params=None):
            if path == "products": return {"data": [], "has_more": False}
            if path == "subscriptions": return {"data": [sub], "has_more": False}
            if path == "checkout/sessions": return {"data": []}
            raise AssertionError(path)

        self.assertEqual(stripe_sync.subscribers(get=get), [])


class DataTest(unittest.TestCase):
    def test_personnummer_tolknas_bortdoljs(self):
        notice = svenska("Upphandling", vinnare=["Anna Andersson", "Bolag AB"],
                         idn=["198112189876", "5562186790"])
        rader = data.p1_rows([notice], bransch=None, lan=None, today="2026-11-26")
        self.assertEqual(len(rader), 1)
        self.assertIn("Bolag AB", rader[0]["vinnande leverantör(er)"])
        self.assertNotIn("Anna", json.dumps(rader, ensure_ascii=True))
        self.assertNotIn("198112", json.dumps(rader, ensure_ascii=True))

    def test_p1_filtrerar_datum_cpv_och_lan(self):
        gamla = svenska("Gammal", publicerad="2026-11-01")
        fel_cpv = svenska("Fel bransch", cpv="45000000")
        fel_lan = svenska("Fel län", plats="SE332")
        bra = svenska("Rätt upphandling")
        rader = data.p1_rows([gamla, fel_cpv, fel_lan, bra], bransch="72", lan="SE110", today="2026-11-26")
        self.assertEqual(len(rader), 1)
        self.assertEqual(rader[0]["upphandling"], "Rätt upphandling")
        self.assertEqual(list(rader[0].keys()), data.P1_KOLUMNER)

    def test_p2_beraknar_slut_datum_och_sakerhet(self):
        explicit = svenska("Angivet slut")
        explicit["contract-duration-end-date-lot"] = ["2026-12-15+01:00"]
        explicit["contract-duration-start-date-lot"] = ["2026-01-01+01:00"]
        beraknad = svenska("Beräknat slut", pid="124-2026")
        beraknad["contract-duration-start-date-lot"] = ["2026-06-01+02:00"]
        beraknad["contract-duration-period-lot"] = [{"value": 6, "unit": "MONTH"}]
        rader = data.p2_rows([explicit, beraknad], bransch=None, lan=None, today="2026-11-26")
        self.assertEqual(len(rader), 2)
        self.assertEqual(rader[0]["säkerhet"], "Angivet slutdatum")
        self.assertEqual(rader[0]["beräknat slutdatum"], "2026-12-15")
        self.assertEqual(rader[1]["säkerhet"], "Beräknat från löptid")
        self.assertEqual(rader[1]["beräknat slutdatum"], "2026-12-01")
        self.assertEqual(list(rader[1].keys()), data.P2_KOLUMNER)

    def test_p2_fragan_tacker_start_och_slut(self):
        query = data.p2_query(today="2026-11-26")
        self.assertIn("contract-duration-end-date-lot", query)
        self.assertIn("contract-duration-start-date-lot", query)

    def test_tackningsgrad(self):
        n1 = svenska("A")
        n1["contract-duration-end-date-lot"] = ["2026-12-01Z"]
        n2 = svenska("B")
        rap = data.coverage([n1, n2])
        self.assertEqual(rap["notiser"], 2)
        self.assertEqual(rap["angivet_slutdatum"], 1)
        self.assertEqual(round(rap["tackning_slutdatum"], 2), 0.5)
        n3 = svenska("C")
        n3["contract-duration-end-date-lot"] = ["2026-12-01Z"]
        n3["contract-duration-period-lot"] = [{"value": 6, "unit": "MONTH"}]
        self.assertEqual(data.coverage([n3])["tackning_slutdatum"], 1.0)


class XlsxTest(unittest.TestCase):
    def test_skriver_giltigt_xlsx(self):
        raw = xlsx.write_xlsx([["Rubrik & A", "Rubrik B"], [1, "två"]], ["Rubrik & A", "Rubrik B"])
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            namn = set(z.namelist())
            self.assertIn("xl/workbook.xml", namn)
            self.assertIn("xl/worksheets/sheet1.xml", namn)
            sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("Rubrik &amp; A", sheet)
        self.assertIn("<v>1</v>", sheet)


class StateTest(unittest.TestCase):
    def test_forsta_och_veckoleverans_ar_idempotenta(self):
        log = state.DeliveryLog({})
        sub = {"id": "sub_1", "plan": "p1", "email": "kund@example.se", "created": 0}
        now = datetime(2026, 11, 30, 6, 5, tzinfo=timezone.utc)
        self.assertTrue(log.is_due(sub, now=now))
        log.mark(sub, "p1", "first", {"rader": 1}, now=now)
        self.assertFalse(log.is_due(sub, now=now))
        self.assertEqual(len(log.data["leveranser"]), 1)

    def test_manadsleverans_forsta_vardagen(self):
        log = state.DeliveryLog({})
        sub = {"id": "sub_2", "plan": "p2", "email": "kund@example.se", "created": 0}
        first = datetime(2026, 12, 1, 6, 5, tzinfo=timezone.utc)
        self.assertTrue(log.is_due(sub, now=first))
        log.mark(sub, "p2", "month:2026-12", {"rader": 2}, now=first)
        self.assertFalse(log.is_due(sub, now=first))
        nasta = datetime(2027, 1, 1, 6, 5, tzinfo=timezone.utc)
        self.assertTrue(log.is_due(sub, now=nasta))


class DeliveryTest(unittest.TestCase):
    def test_resend_payload_innehaller_kalla_och_bilaga(self):
        skickat = []

        def post(path, payload):
            skickat.append((path, payload))
            return {"id": "mejl_1"}

        sub = {"email": "kund@example.se", "plan": "p1", "customer_id": "cus_1", "id": "sub_1"}
        with mock.patch.object(deliver, "post_json", post), mock.patch.object(
                deliver, "portal_lank", return_value="https://example.se/avsluta"):
            deliver.send_email(sub, "p1", [{"Upphandling": "Test"}], b"xlsx", dry_run=False)
        path, payload = skickat[0]
        self.assertEqual(path, "emails")
        self.assertEqual(payload["from"], "Kommunradar <hej@kommunradar.online>")
        self.assertEqual(payload["to"], ["kund@example.se"])
        self.assertIn("TED, © Europeiska unionen, CC BY 4.0, bearbetad av Kommunradar", payload["text"])
        self.assertIn("https://example.se/avsluta", payload["text"])
        self.assertEqual(base64.b64decode(payload["attachments"][0]["content"]), b"xlsx")

    def test_live_kraver_stripe_kund_id(self):
        with self.assertRaises(RuntimeError):
            deliver.send_email({"email": "kund@example.se", "plan": "p1"}, "p1", [], b"xlsx",
                               dry_run=False, post=lambda path, payload: {"id": "mejl_2"})


class CliTest(unittest.TestCase):
    def test_torrkoring_skickar_bara_till_hej_och_anropar_inte_stripe(self):
        with mock.patch.object(cli.data, "fetch_notices", return_value=[]), mock.patch.object(
                cli.stripe_sync, "subscribers", side_effect=AssertionError("Stripe ska inte anropas")
        ), mock.patch.object(cli.deliver, "send_email", return_value={"to": ["hej@kommunradar.online"]}) as send:
            cli.main(["--dry-run", "--mode", "p1"])
        self.assertEqual(send.call_count, 1)
        self.assertTrue(send.call_args.kwargs["dry_run"])
        self.assertEqual(send.call_args.args[0]["email"], "hej@kommunradar.online")

    def test_torrkorning_skriver_inte_state_eller_rapport(self):
        with tempfile.TemporaryDirectory() as root:
            state_path = os.path.join(root, "state.json")
            rapport_path = os.path.join(root, "rapport.json")
            with mock.patch.object(cli.data, "fetch_notices", return_value=[]), mock.patch.object(
                    cli.stripe_sync, "subscribers", side_effect=AssertionError("Stripe ska inte anropas")
            ), mock.patch.object(cli.deliver, "send_email", return_value={"id": "mejl_3"}):
                cli.main(["--dry-run", "--mode", "p1", "--state", state_path, "--rapport", rapport_path])
            self.assertFalse(os.path.exists(state_path))
            self.assertFalse(os.path.exists(rapport_path))

    def test_annan_test_to_stoppas(self):
        with self.assertRaises(RuntimeError):
            cli.main(["--dry-run", "--mode", "p1", "--test-to", "annan@example.se"])

    def test_first_hoppar_over_redan_levererade(self):
        with tempfile.TemporaryDirectory() as root:
            state_path = os.path.join(root, "state.json")
            rapport_path = os.path.join(root, "rapport.json")
            with open(state_path, "w", encoding="utf-8") as handle:
                json.dump({"version": 1, "leveranser": {
                    "sub_1|p1|first": {"tid": "2026-11-30T07:00:00+01:00"}}}, handle)
            folk = [{"id": "sub_1", "email": "a@example.se", "plan": "p1", "customer_id": "cus_1"},
                    {"id": "sub_2", "email": "b@example.se", "plan": "p1", "customer_id": "cus_2"}]
            with mock.patch.object(cli.stripe_sync, "subscribers", return_value=folk), mock.patch.object(
                    cli.data, "fetch_notices", return_value=[]), mock.patch.object(
                    cli.deliver, "send_email", return_value={"id": "mejl_4"}) as send:
                cli.main(["--mode", "first", "--state", state_path, "--rapport", rapport_path])
            self.assertEqual(send.call_count, 1)
            self.assertEqual(send.call_args.args[0]["id"], "sub_2")

    def test_live_p2_lag_tackning_stoppar(self):
        with tempfile.TemporaryDirectory() as root:
            state_path = os.path.join(root, "state.json")
            rapport_path = os.path.join(root, "rapport.json")
            sub = {"id": "sub_4", "email": "kund@example.se", "plan": "p2", "customer_id": "cus_4"}
            with mock.patch.object(cli.stripe_sync, "subscribers", return_value=[sub]), mock.patch.object(
                    cli.data, "fetch_notices", return_value=[{"publication-number": "123-2026"}]), mock.patch.object(
                    cli.deliver, "send_email", side_effect=AssertionError("Ska inte skickas")):
                with self.assertRaises(RuntimeError):
                    cli.main(["--mode", "p2", "--state", state_path, "--rapport", rapport_path])


class CliEntrypointTest(unittest.TestCase):
    def test_python_m_kor_hjalp(self):
        result = subprocess.run([sys.executable, "-m", "leverantorsregistret.cli", "--help"],
                                cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage:", result.stdout)


if __name__ == "__main__":
    unittest.main()

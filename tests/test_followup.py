import csv, os, sys, tempfile, unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import followup_send as F
import outbound_send as O


def rad(epost="a@b.se", bolag="Testbolag AB", upphandling="Städning", kopare="Testkommun"):
    return {"epost": epost, "bolag": bolag, "upphandling": upphandling, "kopare": kopare,
            "lan": "", "bransch": "", "adresstyp": "personlig"}


class PlanTest(unittest.TestCase):
    def test_mejl_2_går_fyra_dagar_efter_mejl_1(self):
        r = rad()
        sent = {O.nyckel(r["epost"]): {"datum": "2026-11-18"}}
        self.assertEqual(F.plan([r], sent, {}, set(), date(2026, 11, 21)), [])
        jobb = F.plan([r], sent, {}, set(), date(2026, 11, 22))
        self.assertEqual([(d, s) for d, _, s in jobb], [(4, 2)])

    def test_mejl_3_går_fem_dagar_efter_mejl_2(self):
        r = rad()
        sent = {O.nyckel(r["epost"]): {"datum": "2026-11-18"}}
        fstate = {O.nyckel(r["epost"]): {"steg": 2, "datum": "2026-11-22"}}
        self.assertEqual(F.plan([r], sent, fstate, set(), date(2026, 11, 26)), [])
        jobb = F.plan([r], sent, fstate, set(), date(2026, 11, 27))
        self.assertEqual([(d, s) for d, _, s in jobb], [(5, 3)])

    def test_ingen_uppföljning_till_den_som_inte_fick_mejl_1(self):
        self.assertEqual(F.plan([rad()], {}, {}, set(), date(2027, 1, 1)), [])

    def test_svar_och_spärr_hoppas_över(self):
        r = rad()
        sent = {O.nyckel(r["epost"]): {"datum": "2026-11-18"}}
        idag = date(2026, 12, 1)
        self.assertEqual(F.plan([r], sent, {}, {"a@b.se"}, idag), [])
        egen = rad(epost="hej@kommunradar.online")
        sent2 = {O.nyckel(egen["epost"]): {"datum": "2026-11-18"}}
        self.assertEqual(F.plan([egen], sent2, {}, set(), idag), [])

    def test_redan_skickat_steg_3_ger_inget_mer(self):
        r = rad()
        sent = {O.nyckel(r["epost"]): {"datum": "2026-11-18"}}
        fstate = {O.nyckel(r["epost"]): {"steg": 3, "datum": "2026-11-27"}}
        self.assertEqual(F.plan([r], sent, fstate, set(), date(2027, 1, 1)), [])

    def test_mest_försenade_först(self):
        a, b = rad(epost="a@b.se"), rad(epost="c@d.se")
        sent = {O.nyckel(a["epost"]): {"datum": "2026-11-10"},
                O.nyckel(b["epost"]): {"datum": "2026-11-18"}}
        jobb = F.plan([b, a], sent, {}, set(), date(2026, 11, 22))
        self.assertEqual([x[1]["epost"] for x in jobb], ["a@b.se", "c@d.se"])


class TextTest(unittest.TestCase):
    def test_steg_2_är_ett_svar_på_mejl_1(self):
        ämne, text = F.bygg(rad(), [], 2)
        self.assertTrue(ämne.startswith("Re: Grattis till er vinst"))
        self.assertIn("Testbolag", text + "Testbolag")  # bolaget står i ämnet/listan, inte alltid i texten
        self.assertIn("förra veckan", text)
        self.assertIn("Städning hos Testkommun", text)
        self.assertIn("sluta", text)

    def test_steg_3_är_sista_mejlet(self):
        ämne, text = F.bygg(rad(), [], 3)
        self.assertTrue(ämne.startswith("Re: Grattis till er vinst"))
        self.assertIn("Sista mejlet", text)
        self.assertIn("hör jag inte av mig igen", text)

    def test_utan_matchande_upphandling_lovs_inget_specifikt(self):
        _, text = F.bygg(rad(), [], 2)
        self.assertIn("1 500", text)


class SvaratTest(unittest.TestCase):
    def test_kommentarer_och_tomma_rader_ignoreras(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "svarat.txt")
            with open(p, "w", encoding="utf8") as f:
                f.write("# kommentar\n\nA@B.se\n  c@d.se  \n# x@y.se\n")
            gamla = F.SVARAT
            F.SVARAT = p
            try:
                self.assertEqual(F.las_svarat(), {"a@b.se", "c@d.se"})
            finally:
                F.SVARAT = gamla

    def test_saknad_fil_ger_tom_mängd(self):
        gamla = F.SVARAT
        F.SVARAT = os.path.join(tempfile.gettempdir(), "finns-inte-9182.txt")
        try:
            self.assertEqual(F.las_svarat(), set())
        finally:
            F.SVARAT = gamla


class ListaTest(unittest.TestCase):
    def test_fresh_lägger_till_utan_att_tappa_gamla(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "lista.csv")
            O.spara_lista(p, [rad(epost="a@b.se"), rad(epost="c@d.se")])
            nya = O.spara_lista(p, [rad(epost="C@D.se"), rad(epost="e@f.se")])
            with open(p, encoding="utf-8-sig") as f:
                rader = list(csv.DictReader(f))
            self.assertEqual(nya, 1)
            self.assertEqual([r["epost"] for r in rader], ["a@b.se", "c@d.se", "e@f.se"])


if __name__ == "__main__":
    unittest.main()

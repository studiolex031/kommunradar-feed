import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "atlas" / "scripts"))
import build
import newsletter
import patch_home


class AtlasTest(unittest.TestCase):
    def test_slug_tar_bort_svenska_tecken(self):
        self.assertEqual(build.slug("Västra Götaland"), "vastra-gotaland")
        self.assertEqual(build.slug("Bygg & anläggning"), "bygg-och-anlaggning")

    def test_kopare_rensas(self):
        self.assertEqual(build.clean_buyer("Region Skåne, Koncernstab inköp"), "Region Skåne")
        self.assertEqual(build.clean_buyer("Trafikverket Myndighet"), "Trafikverket")

    def test_stats_raknar_ett_anbud_bland_kanda(self):
        rows = [{"bids": 1, "winners": ["A AB"], "value": None, "pub": None},
                {"bids": 3, "winners": ["B AB"], "value": None, "pub": None},
                {"bids": None, "winners": ["a ab"], "value": None, "pub": None}]
        s = build.stats(rows)
        self.assertEqual((s["n"], s["with_bids"], s["median"], s["single"], s["suppliers"]), (3, 2, 2, 0.5, 2))

    def test_bara_bolag_visas_som_vinnare(self):
        rows = [{"winners": ["Anna Andersson", "Exempel AB"]}] * 2
        self.assertEqual(build.top_winners(rows), [("Exempel AB", 2)])

    def test_vinnaretikett_raknar_alla_som_inte_visas(self):
        self.assertEqual(build.winner_label(["A AB", "Anna Andersson"]), "A AB +1")
        self.assertEqual(build.winner_label(["A AB", "B AB", "C AB", "Anna Andersson"]), "A AB, B AB +2")
        self.assertEqual(build.winner_label(["Anna Andersson"]), "1 vinnare")
        self.assertEqual(build.winner_label([]), "–")


class NewsletterTest(unittest.TestCase):
    TODAY = build.date(2026, 11, 3)

    def lead(self, i, value, buyer="Köpare", cat="IT", days=30, lans=("Skåne",)):
        return {"id": str(i), "title": f"T{i}", "url": f"https://x/{i}", "value_sek": value, "_buyer": buyer, "_cat": cat,
                "_deadline": self.TODAY + build.timedelta(days=days), "_lans": list(lans),
                "published": self.TODAY.isoformat()}

    def test_urval_kraver_tid_kvar_och_blandar_kopare(self):
        rows = [self.lead(1, 9e8), self.lead(2, 8e8), self.lead(3, 7e8), self.lead(4, 6e8, buyer="B", cat="Bygg"),
                self.lead(5, 5e8, buyer="C", cat="Vård", days=3), self.lead(6, None, buyer="D", cat="Städ")]
        self.assertEqual([l["id"] for l in newsletter.pick_top(rows, self.TODAY)], ["1", "2", "4"])

    def test_mindre_affarer_har_tak_och_upprepar_inte(self):
        rows = [self.lead(1, 9e8), self.lead(2, 5e6, buyer="B", cat="Bygg"), self.lead(3, 1e6, buyer="C", cat="Vård")]
        got = newsletter.pick_top(rows, self.TODAY, 5, 15_000_000, {"3"})
        self.assertEqual([l["id"] for l in got], ["2"])

    def test_gamla_upphandlingar_raknas_inte_som_nya(self):
        old = self.lead(1, 1e6)
        old["published"] = (self.TODAY - build.timedelta(days=8)).isoformat()
        self.assertEqual(newsletter.new_this_week([old, self.lead(2, 1e6)], self.TODAY)[0]["id"], "2")
        self.assertEqual(len(newsletter.new_this_week([old], self.TODAY)), 0)


class RobotsTest(unittest.TestCase):
    CURRENT = ("User-agent: *\nAllow: /\nSitemap: https://kommunradar.online/sitemap.xml\n"
               "Sitemap: https://kommunradar.online/sitemap-atlas-1.xml\n")

    def test_ny_vag_ger_inga_dubbletter_och_behaller_ovrigt(self):
        out = patch_home.robots_for(self.CURRENT, 2)
        self.assertEqual(out.count("sitemap-atlas-1.xml"), 1)
        self.assertIn("sitemap-atlas-2.xml", out)
        self.assertNotIn("sitemap-atlas-3.xml", out)
        self.assertIn("Sitemap: https://kommunradar.online/sitemap.xml\n", out)
        self.assertIn("Allow: /", out)


if __name__ == "__main__":
    unittest.main()

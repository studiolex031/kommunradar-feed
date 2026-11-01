import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "atlas" / "scripts"))
import build


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


if __name__ == "__main__":
    unittest.main()

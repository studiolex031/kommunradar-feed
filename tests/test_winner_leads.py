import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import winner_leads as wl

NOTICE = {"publication-number": "751105-2026", "publication-date": "2026-10-29+01:00",
          "notice-title": {"swe": ["Städ av trapphus, lokaler samt lägenheter"]}, "buyer-name": {"swe": ["Örebrobostäder AB"]},
          "buyer-country-sub": ["SE124"], "classification-cpv": ["90911200"],
          "winner-name": {"swe": ["Nytorget Clean & Facility AB", "Samhall Aktiebolag", "Utan Mejl AB"]},
          "received-submissions-type-val": ["6"], "received-submissions-type-code": ["tenders"],
          "organisation-name-tenderer": {"swe": ["Nytorget Clean & Facility AB", "Samhall Aktiebolag", "Utan Mejl AB"]},
          "organisation-email-tenderer": ["Info@NcleanFacility.se", "anbud@samhall.se", "-"],
          "organisation-city-tenderer": ["Skarpnäck", "Stockholm", "Örebro"]}


class WinnerLeadsTest(unittest.TestCase):
    def test_pairs_winner_with_own_email_and_drops_big_and_missing(self):
        rows = wl.rows_from_notice(NOTICE)
        self.assertEqual([r["bolag"] for r in rows], ["Nytorget Clean & Facility AB"])
        r = rows[0]
        self.assertEqual((r["epost"], r["adresstyp"], r["ort"], r["lan"], r["bransch"], r["anbud"], r["vinnare"]),
                         ("info@ncleanfacility.se", "generisk", "Skarpnäck", "Örebro", "Avfall, städ & miljö", 6, 3))

    def test_misaligned_lists_give_no_rows_rather_than_wrong_email(self):
        n = {**NOTICE, "organisation-email-tenderer": ["info@ncleanfacility.se"]}
        self.assertEqual(wl.rows_from_notice(n), [])

    def test_personal_address_is_marked(self):
        n = {**NOTICE, "organisation-email-tenderer": ["marika.jernberg@ncleanfacility.se", "x@samhall.se", "-"]}
        self.assertEqual(wl.rows_from_notice(n)[0]["adresstyp"], "personlig")

    def test_csv_has_header_even_when_empty(self):
        self.assertTrue(wl.to_csv([]).startswith("bolag"))
        self.assertIn("ncleanfacility", wl.to_csv(wl.rows_from_notice(NOTICE)))


if __name__ == "__main__":
    unittest.main()

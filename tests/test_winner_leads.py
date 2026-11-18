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

    def test_unescapes_names_and_strips_ted_title_prefix(self):
        n = {**NOTICE, "notice-title": {"swe": ["Sverige – Grus, sand – Grus &amp; massor Falköping"]},
             "winner-name": {"swe": ["Ramseruds Grus &amp; Åkeri AB"]},
             "organisation-name-tenderer": {"swe": ["Ramseruds Grus &amp; Åkeri AB"]},
             "organisation-email-tenderer": ["info@ramserudsgrus.se"], "organisation-city-tenderer": ["Säffle"]}
        r = wl.rows_from_notice(n)[0]
        self.assertEqual((r["bolag"], r["upphandling"]), ("Ramseruds Grus & Åkeri AB", "Grus & massor Falköping"))
        self.assertEqual(wl.clean_title("Lokalvård skolor"), "Lokalvård skolor")

    def test_email_is_not_entity_decoded(self):
        n = {**NOTICE, "organisation-email-tenderer": ["sales&copy@ncleanfacility.se", "x@samhall.se", "-"]}
        self.assertEqual(wl.rows_from_notice(n)[0]["epost"], "sales&copy@ncleanfacility.se")

    def test_names_colliding_after_normalising_get_no_email(self):
        n = {**NOTICE, "winner-name": {"swe": ["A &amp; B AB", "A B AB"]},
             "organisation-name-tenderer": {"swe": ["A &amp; B AB", "A B AB"]},
             "organisation-email-tenderer": ["info@ab-ett.se", "info@ab-tva.se"], "organisation-city-tenderer": ["X", "Y"]}
        self.assertEqual(wl.rows_from_notice(n), [])

    def test_colliding_tenderers_with_same_email_get_no_contact(self):
        n = {**NOTICE, "winner-name": {"swe": ["A &amp; B AB"]},
             "organisation-name-tenderer": {"swe": ["A &amp; B AB", "A B AB"]},
             "organisation-email-tenderer": ["info@ab.se", "info@ab.se"], "organisation-city-tenderer": ["X", "Y"]}
        self.assertEqual(wl.rows_from_notice(n), [])

    def test_colliding_winners_with_one_tenderer_contact_get_no_contact(self):
        n = {**NOTICE, "winner-name": {"swe": ["A &amp; B AB", "A B AB"]},
             "organisation-name-tenderer": {"swe": ["A &amp; B AB"]},
             "organisation-email-tenderer": ["info@ab-ett.se"], "organisation-city-tenderer": ["X"]}
        self.assertEqual(wl.rows_from_notice(n), [])

    def test_same_company_listed_twice_identically_keeps_contact(self):
        n = {**NOTICE, "winner-name": {"swe": ["Nytorget Clean & Facility AB"]},
             "organisation-name-tenderer": {"swe": ["Nytorget Clean & Facility AB", "NYTORGET CLEAN & FACILITY AB"]},
             "organisation-email-tenderer": ["info@ncleanfacility.se", "info@ncleanfacility.se"],
             "organisation-city-tenderer": ["Skarpnäck", "Skarpnäck"]}
        self.assertEqual(wl.rows_from_notice(n)[0]["epost"], "info@ncleanfacility.se")

    def test_csv_has_header_even_when_empty(self):
        self.assertTrue(wl.to_csv([]).startswith("bolag"))
        self.assertIn("ncleanfacility", wl.to_csv(wl.rows_from_notice(NOTICE)))


class StorleksfilterTest(unittest.TestCase):
    """Filtret är en lista, inte en mätning. Testerna låser beteendet, inte sanningen."""

    def test_kand_jatte_pa_doman_filtreras_bort(self):
        self.assertTrue(wl.for_stor("Manpower Aktiebolag", "bidteam@manpowergroup.se"))
        self.assertTrue(wl.for_stor("Academic Work Sweden AB", "elias.allenback@academicwork.se"))
        self.assertTrue(wl.for_stor("Medtronic Aktiebolag", "upphandling@medtronic.com"))

    def test_anbudsavdelning_filtreras_bort(self):
        for epost in ("bid@b3.se", "bidteam@randstad.se", "avrop@tengbom.se",
                      "avropa@jurek.se", "ramavtal@chas.se", "tenders@stromsholmadvokat.se"):
            self.assertTrue(wl.for_stor("Okant Bolag AB", epost), epost)

    def test_litet_bolag_med_upphandlingadress_behalles(self):
        """upphandling@ och info@ används av små bolag också — de får inte filtreras."""
        self.assertFalse(wl.for_stor("Care of Sweden AB", "upphandling@careofsweden.se"))
        self.assertFalse(wl.for_stor("Cemi AB", "upphandling@cemi.se"))
        self.assertFalse(wl.for_stor("WPcon AB", "anders.brisme@wpcon.se"))
        self.assertFalse(wl.for_stor("Markkompaniet Syd AB", "johan.slagstedt@markkompaniet.se"))

    def test_filtret_anvands_nar_listan_byggs(self):
        n = {**NOTICE, "winner-name": {"swe": ["Manpower Aktiebolag"]},
             "organisation-name-tenderer": {"swe": ["Manpower Aktiebolag"]},
             "organisation-email-tenderer": ["bidteam@manpowergroup.se"],
             "organisation-city-tenderer": ["Stockholm"]}
        self.assertEqual(wl.rows_from_notice(n), [])


if __name__ == "__main__":
    unittest.main()

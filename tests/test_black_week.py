import os, sys, unittest
from datetime import date
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import outbound_send as O
import followup_send as F


class BlackWeek(unittest.TestCase):
    def test_aktiv_under_kampanjen(self):
        ps = O.black_week(date(2026, 11, 24))
        self.assertIn(O.BW_LANK, ps)
        self.assertIn("4 900 kr", ps)

    def test_sista_dagen_ingar(self):
        self.assertIsNotNone(O.black_week(O.BW_SLUT))

    def test_slut_efter_kampanjen(self):
        self.assertIsNone(O.black_week(date(2026, 12, 1)))

    def test_ps_fore_signaturen_i_alla_mejl(self):
        if O.black_week() is None:
            self.skipTest("kampanjen är slut")
        rad = {"upphandling": "Städtjänster", "kopare": "Testkommun", "lan": "Skåne"}
        texter = [O.bygg(rad, [])[1], F.bygg(rad, [], 2)[1], F.bygg(rad, [], 3)[1]]
        for t in texter:
            self.assertLess(t.index(O.BW_LANK), t.index("Vänligen"))


if __name__ == "__main__":
    unittest.main()

import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import brevo_block as B


class StopplistaTest(unittest.TestCase):
    def skriv(self, text):
        f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
        f.write(text)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_kommentarer_och_tomma_rader_hoppas_over(self):
        p = self.skriv("# rubrik\n\n  \na@b.se\n# c@d.se\ne@f.se\n")
        self.assertEqual(B.adresser(p), ["a@b.se", "e@f.se"])

    def test_dubbletter_och_versaler_normaliseras(self):
        p = self.skriv("A@B.se\na@b.se\n a@b.se \n")
        self.assertEqual(B.adresser(p), ["a@b.se"])

    def test_kommentar_pa_samma_rad_ignoreras(self):
        p = self.skriv("a@b.se  # svarade sluta\n")
        self.assertEqual(B.adresser(p), ["a@b.se"])

    def test_rader_utan_at_hoppas_over(self):
        p = self.skriv("inte-en-adress\na@b.se\n")
        self.assertEqual(B.adresser(p), ["a@b.se"])

    def test_saknad_fil_ger_tom_lista(self):
        self.assertEqual(B.adresser(os.path.join(tempfile.gettempdir(), "finns-inte-alls.txt")), [])

    def test_torrkorning_ror_inte_natet(self):
        self.assertEqual(B.blockera("a@b.se", None, torrkorning=True), "skulle blockeras")


if __name__ == "__main__":
    unittest.main()

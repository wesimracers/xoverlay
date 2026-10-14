import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "main"))
from country_codes import ALPHA3_TO_ALPHA2, country_code


class CountryCodesTests(unittest.TestCase):
    def test_all_249_official_entries(self):
        countries = json.loads((ROOT / "tests/fixtures/iso3166-1.json").read_text(encoding="utf-8"))
        self.assertEqual(len(countries), 249)
        self.assertEqual(len(ALPHA3_TO_ALPHA2), 249)
        self.assertEqual(len(set(ALPHA3_TO_ALPHA2.values())), 249)
        for country in countries:
            for field in ("alpha_2", "alpha_3", "name", "official_name", "common_name"):
                if country.get(field):
                    with self.subTest(country=country["alpha_2"], field=field):
                        self.assertEqual(country_code(country[field]), country["alpha_2"])

    def test_real_flairs_and_normalization(self):
        for name, expected in (("Germany", "DE"), ("Niger", "NE"), ("Nigeria", "NG"),
                               ("United Kingdom", "GB"), ("England", "GB"),
                               ("Scotland", "GB"), ("Wales", "GB"),
                               (" Türkiye ", "TR"), (" gbr ", "GB"),
                               ("Côte d’Ivoire", "CI"), ("São Tomé and Príncipe", "ST")):
            self.assertEqual(country_code(name), expected)

    def test_non_countries_do_not_invent_codes(self):
        for name in (None, "", "-none-", "Global", "Europe", "Atlantis", "XXX", "ZZ"):
            self.assertEqual(country_code(name), "")


if __name__ == "__main__":
    unittest.main()

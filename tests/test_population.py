import unittest

from tw_site_analyzer.population import DistrictPopulationSource


class FakePopulationSource(DistrictPopulationSource):
    def _load(self):
        return [
            {
                "site_id": "高雄市三民區",
                "household_ordinary_m": "100",
                "household_ordinary_f": "110",
                "household_business_m": "5",
                "household_business_f": "5",
                "household_single_m": "20",
                "household_single_f": "25",
            },
            {
                "site_id": "高雄市左營區",
                "household_ordinary_m": "80",
                "household_ordinary_f": "90",
                "household_business_m": "2",
                "household_business_f": "3",
                "household_single_m": "15",
                "household_single_f": "16",
            },
        ]


class PopulationTest(unittest.TestCase):
    def test_districts_are_real_and_ranked_by_population(self):
        rows = FakePopulationSource().districts("高雄市")
        self.assertEqual([item["district"] for item in rows], ["三民區", "左營區"])
        self.assertGreater(rows[0]["population"], rows[1]["population"])


if __name__ == "__main__":
    unittest.main()

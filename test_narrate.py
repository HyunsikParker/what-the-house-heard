"""Numeric evidence checks; no model, network, or third-party packages needed."""
import json
from pathlib import Path
import unittest

from narrate import check


class EvidenceCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).parent / "docs" / "sample"
        cls.report = json.loads((root / "events.json").read_text())
        cls.sample = json.loads((root / "story.json").read_text())

    def with_reading(self, reading):
        return f"At 02:47, CO2 rises {reading}, sound reaches 53.5 dBA, and humidity is 46.7%."

    def test_published_story_retains_exact_check(self):
        self.assertEqual(check(self.sample["story"], self.report), self.sample["check"])

    def test_equivalent_numeric_spellings(self):
        for reading in ("45.6 ppm", "+45.60 ppm", "4.56e1 ppm", "0.456e+2 ppm"):
            with self.subTest(reading=reading):
                self.assertTrue(check(self.with_reading(reading), self.report)["ok"])

    def test_sign_is_not_discarded(self):
        for reading in ("-45.6 ppm", "−45.6 ppm", "-4.56e1 ppm"):
            with self.subTest(reading=reading):
                result = check(self.with_reading(reading), self.report)
                self.assertFalse(result["ok"])
                self.assertEqual(result["readings_not_in_evidence"], [reading])

    def test_numeric_prefix_is_not_discarded(self):
        for reading in ("1,045.6 ppm", "12,045.6 ppm", "1.0456e3 ppm", "1,2,45.6 ppm", "1.45.6 ppm"):
            with self.subTest(reading=reading):
                result = check(self.with_reading(reading), self.report)
                self.assertFalse(result["ok"])
                self.assertEqual(result["readings_not_in_evidence"], [reading])

    def test_negative_values_are_valid_if_evidenced(self):
        report = {"events": [{"start": "00:00", "end": "00:00", "co2_change_ppm": -45.6,
                              "sound_max_dba": 53.5, "humidity_max_pct": 46.7}]}
        story = "At 00:00: -45.6 ppm, 53.5 dBA, 46.7%."
        self.assertTrue(check(story, report)["ok"])

    def test_thousands_groups_are_valid_if_evidenced(self):
        report = {"events": [{"start": "00:00", "end": "00:00", "co2_change_ppm": 1045.6,
                              "sound_max_dba": 53.5, "humidity_max_pct": 46.7}]}
        self.assertTrue(check("At 00:00: 1,045.6 ppm, 53.5 dBA, 46.7%.", report)["ok"])

    def test_wrong_unit_is_rejected(self):
        self.assertFalse(check(self.with_reading("45.6 lux"), self.report)["ok"])

    def test_time_outside_all_events_is_rejected(self):
        story = self.with_reading("45.6 ppm").replace("02:47", "12:34")
        self.assertFalse(check(story, self.report)["ok"])

    def test_three_readings_are_still_required(self):
        self.assertFalse(check("At 02:47: 45.6 ppm and 53.5 dBA.", self.report)["ok"])

    def test_checker_does_not_claim_room_level_binding(self):
        # This value exists for the kitchen. The numeric whitelist is global,
        # not a semantic check that attributes each sentence to the right room.
        story = self.with_reading("99.3 ppm").replace("At 02:47", "At 02:47 in the living room")
        self.assertTrue(check(story, self.report)["ok"])


if __name__ == "__main__":
    unittest.main()

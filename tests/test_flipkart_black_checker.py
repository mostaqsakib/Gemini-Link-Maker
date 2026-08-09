import csv
import tempfile
import unittest
from pathlib import Path

from scripts.flipkart_black_checker import (
    CheckResult,
    append_csv_result,
    mask_phone,
    normalize_indian_phone,
    parse_membership_state,
    sanitize_text,
)


class FlipkartBlackCheckerTests(unittest.TestCase):
    def test_normalizes_common_indian_phone_formats(self):
        self.assertEqual(normalize_indian_phone("+91 98765 43210"), "9876543210")
        self.assertEqual(normalize_indian_phone("09876543210"), "9876543210")
        self.assertEqual(normalize_indian_phone("9876543210"), "9876543210")

    def test_rejects_invalid_phone(self):
        with self.assertRaises(ValueError):
            normalize_indian_phone("12345")

    def test_parses_membership_state(self):
        payload = {
            "RESPONSE": {
                "versionedData": {
                    "lockinResponse": {
                        "userMembershipState": "inactive",
                    }
                }
            }
        }
        self.assertEqual(parse_membership_state(payload), "INACTIVE")

    def test_missing_membership_state_is_unknown_to_parser(self):
        self.assertIsNone(parse_membership_state({"RESPONSE": {}}))

    def test_masks_phone_and_sensitive_error_text(self):
        phone = "9876543210"
        self.assertEqual(mask_phone(phone), "+91******3210")
        redacted = sanitize_text(
            "OTP 123456 failed for 9876543210 and person@example.com",
            phone,
            "123456",
        )
        self.assertNotIn(phone, redacted)
        self.assertNotIn("123456", redacted)
        self.assertNotIn("person@example.com", redacted)

    def test_csv_masks_phone_by_default(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "results.csv"
            result = CheckResult(
                phone="9876543210",
                membership_state="INACTIVE",
                outcome="classified",
            )
            append_csv_result(output, result)

            with output.open(newline="", encoding="utf-8") as csv_file:
                rows = list(csv.DictReader(csv_file))

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["phone"], "")
            self.assertEqual(rows[0]["phone_masked"], "+91******3210")
            self.assertEqual(rows[0]["membership_state"], "INACTIVE")
            self.assertEqual(rows[0]["black_active"], "no")

    def test_csv_can_include_full_phone_explicitly(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "results.csv"
            result = CheckResult(
                phone="9876543210",
                membership_state="ACTIVE",
                outcome="classified",
            )
            append_csv_result(output, result, include_full_phone=True)

            with output.open(newline="", encoding="utf-8") as csv_file:
                row = next(csv.DictReader(csv_file))

            self.assertEqual(row["phone"], "+919876543210")
            self.assertEqual(row["black_active"], "yes")


if __name__ == "__main__":
    unittest.main()

import unittest

from scripts.utils.master_http_tracer import redact_mapping


class MasterHttpTracerTests(unittest.TestCase):
    def test_redacts_phone_numbers_used_as_dynamic_json_keys(self):
        payload = {
            "userDetails": {
                "9876543210": {
                    "state": "VERIFIED",
                }
            }
        }

        redacted = redact_mapping(payload)

        self.assertNotIn("9876543210", redacted["userDetails"])
        self.assertEqual(
            redacted["userDetails"]["[REDACTED_PHONE]"]["state"],
            "VERIFIED",
        )

    def test_preserves_non_sensitive_membership_fields(self):
        payload = {
            "lockinResponse": {
                "userMembershipState": "INACTIVE",
            }
        }

        self.assertEqual(
            redact_mapping(payload)["lockinResponse"]["userMembershipState"],
            "INACTIVE",
        )


if __name__ == "__main__":
    unittest.main()

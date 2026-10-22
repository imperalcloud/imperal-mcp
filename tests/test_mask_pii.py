import unittest
from imperal_mcp.mask import apply_pii_redaction, PIIRedactionLevel, _PHONE_RE

class TestPIIRedaction(unittest.TestCase):
    def test_ipv4_not_masked(self):
        ips = [
            "104.224.88.155",
            "127.0.0.1",
            "10.199.3.21",
            "66.78.41.54:22",
            "10.88.0.1:8085",
        ]
        for ip in ips:
            res = apply_pii_redaction(f"Connecting to {ip} now", PIIRedactionLevel.MASK_PII)
            self.assertNotIn("<PHONE>", res, f"IP {ip} was mistakenly masked as PHONE")
            self.assertIn(ip, res, f"IP {ip} was altered")

    def test_dates_not_masked(self):
        dates = ["2026-10-12", "2024-01-01", "1999-12-31"]
        for d in dates:
            res = apply_pii_redaction(f"Deployment date is {d}", PIIRedactionLevel.MASK_PII)
            self.assertNotIn("<PHONE>", res, f"Date {d} was mistakenly masked as PHONE")
            self.assertIn(d, res, f"Date {d} was altered")

    def test_versions_not_masked(self):
        versions = ["3.11.15", "6.0.2", "1.0.0.1"]
        for v in versions:
            res = apply_pii_redaction(f"Upgraded to python {v}", PIIRedactionLevel.MASK_PII)
            self.assertNotIn("<PHONE>", res, f"Version {v} was mistakenly masked as PHONE")
            self.assertIn(v, res, f"Version {v} was altered")

    def test_port_ranges_not_masked(self):
        ranges = ["8000-8080", "22-25", "30000-32767"]
        for r in ranges:
            res = apply_pii_redaction(f"Open ports {r}", PIIRedactionLevel.MASK_PII)
            self.assertNotIn("<PHONE>", res, f"Port range {r} was mistakenly masked as PHONE")
            self.assertIn(r, res, f"Port range {r} was altered")

    def test_legitimate_phones_masked(self):
        phones = [
            "+1 (555) 123-4567",
            "+380 99 123 4567",
            "(555) 123-4567",
            "123.456.7890",
            "+49 30 12345678",
        ]
        for p in phones:
            res = apply_pii_redaction(f"Call me at {p}", PIIRedactionLevel.MASK_PII)
            self.assertIn("<PHONE>", res, f"Phone {p} was NOT masked as PHONE")

    def test_emails_masked(self):
        res = apply_pii_redaction("Reach me at support@imperal.io", PIIRedactionLevel.MASK_PII)
        self.assertIn("<EMAIL>", res)
        self.assertNotIn("support@imperal.io", res)

if __name__ == "__main__":
    unittest.main()

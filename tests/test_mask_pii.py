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

    def test_unformatted_and_foreign_numbers_masked(self):
        # the broad matcher stays: bare digit runs and national formats are phones until proven otherwise
        for p in ["380991234567", "5551234567", "030 12345678", "0049 30 12345678", "+15551234567", "099/123 45 67"]:
            res = apply_pii_redaction(f"Number {p} here", PIIRedactionLevel.MASK_PII)
            self.assertTrue("<PHONE>" in res or "<CARD>" in res, f"Number {p} was NOT masked: {res}")
            self.assertNotIn(p, res)

    def test_several_ips_in_a_row_kept(self):
        res = apply_pii_redaction("peers 10.0.0.1 10.0.0.2 104.224.88.155", PIIRedactionLevel.MASK_PII)
        self.assertNotIn("<PHONE>", res)

    def test_emails_masked(self):
        res = apply_pii_redaction("Reach me at support@imperal.io", PIIRedactionLevel.MASK_PII)
        self.assertIn("<EMAIL>", res)
        self.assertNotIn("support@imperal.io", res)

if __name__ == "__main__":
    unittest.main()


def test_a_uuid_is_never_masked_as_a_phone():
    """Live 10-26: a panel connection id reached the frame as "ssh:0f09e3ed-78eb-4c<PHONE>e4e1254bd84"."""
    from imperal_mcp.mask import PIIRedactionLevel, apply_pii_redaction
    s = "target ssh:0f09e3ed-78eb-4c78-9681-2e4e1254bd84 and call +1 (555) 013-2468"
    out = apply_pii_redaction(s, PIIRedactionLevel.MASK_PII)
    assert "ssh:0f09e3ed-78eb-4c78-9681-2e4e1254bd84" in out and "<PHONE>" in out and "555" not in out


def test_a_date_time_and_a_hash_are_never_masked_as_a_phone():
    # live 2026-11-07: `git show -s --format="%h %ci"` reached the kernel as "573a3a<PHONE>:15:12 +0000" -- every git
    # date of the session lost, so the kernel's claim check could not find a commit time the agent truly read
    for s in ["573a3a63 2026-11-07 12:15:12 +0000", "2026-11-07 12:15:12 +0000", "2026-11-07T12:15:12Z",
              "at 2026-11-07 12:15", "commit e8913896 at 2026-11-07 13:47"]:
        assert apply_pii_redaction(s, PIIRedactionLevel.MASK_PII) == s, s


def test_a_phone_beside_a_date_time_is_still_masked():
    out = apply_pii_redaction("2026-11-07 12:15:12 call +1 (555) 123-4567", PIIRedactionLevel.MASK_PII)
    assert out.startswith("2026-11-07 12:15:12 ") and "555" not in out and "<PHONE>" in out
    assert apply_pii_redaction("call 380991234567", PIIRedactionLevel.MASK_PII) == "call <PHONE>"


def test_a_tables_columns_are_not_one_phone():
    # live 2026-11-14: `ps` printed "3846258       00:55 ..." and the PID reached the kernel as "<PHONE>:55"
    from imperal_mcp.mask import defensive_scrub
    assert defensive_scrub("3846258       00:55 /opt/x -m pytest -q") == "3846258       00:55 /opt/x -m pytest -q"
    assert defensive_scrub("3846251\t00:03 bash") == "3846251\t00:03 bash"
    assert defensive_scrub("call +1 415 555 2671 or 380991234567") == "call <PHONE> or <PHONE>"
    assert "<PHONE>" in defensive_scrub("phone:  +1 415 555 2671")      # a phone in its own column is still a phone


def test_two_process_ids_are_not_a_card():
    # live 2026-11-14: `kill 3846252 3846258` reached the kernel as `kill <CARD>`
    from imperal_mcp.mask import defensive_scrub
    assert defensive_scrub("kill 3846252 3846258; sleep 2") == "kill 3846252 3846258; sleep 2"
    assert defensive_scrub("card 4111 1111 1111 1111") == "card <CARD>"
    assert defensive_scrub("amex 3782-822463-10005") == "amex <CARD>"
    assert defensive_scrub("pan 4111111111111111") == "pan <CARD>"          # unbroken: still masked


def test_two_real_numbers_side_by_side_stay_masked():
    from imperal_mcp.mask import defensive_scrub
    assert defensive_scrub("a 380991234567 380991234568 b") == "a <PHONE> <PHONE> b"
    assert defensive_scrub("x 4111111111111111 4111111111111111") == "x <CARD> <CARD>"


def test_a_date_beside_a_number_is_not_a_phone():
    from imperal_mcp.mask import defensive_scrub
    assert defensive_scrub("RELEASED package 4 2026-11-14: kernel") == "RELEASED package 4 2026-11-14: kernel"
    assert defensive_scrub("v 3 10.0.0.1 up") == "v 3 10.0.0.1 up"
    assert defensive_scrub("call +1 415 555 2671 now") == "call <PHONE> now"
    assert defensive_scrub("on 2026-11-14 call 380991234567") == "on 2026-11-14 call <PHONE>"

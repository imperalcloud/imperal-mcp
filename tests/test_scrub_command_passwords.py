"""A password given on a command line never leaves this machine (kernel a54e2f72; Ignat 11-06: `mysql -p'...'`)."""
from imperal_mcp.secrets_scrub import scrub_secrets


def test_mysql_short_option_password_is_redacted():
    for cmd in ("mysql -uroot -p'S3cr3tPass!' -h db shop", 'mysqldump -u app -p"S3cr3tPass!" shop',
                "mariadb -uroot -pS3cr3tPass shop"):
        assert "S3cr3tPass" not in scrub_secrets(cmd)


def test_sshpass_password_is_redacted():
    out = scrub_secrets("sshpass -p 'Hunter2pw' ssh root@10.0.0.1 uptime")
    assert "Hunter2pw" not in out and "uptime" in out


def test_a_bare_dash_p_of_other_programs_stays():
    assert scrub_secrets("mkdir -p /srv/app && ssh -p 2323 host") == "mkdir -p /srv/app && ssh -p 2323 host"

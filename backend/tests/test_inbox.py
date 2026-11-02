import smtplib
import time

import httpx

from agentqa import inbox
from tests.conftest import free_port


def test_extract_otp_prefers_the_labelled_code():
    assert inbox.extract_otp("Your Demo Certificate Portal login OTP is 520726. It is valid for 5 minutes.") == "520726"
    assert inbox.extract_otp("123456 is your one-time password for login") == "123456"
    assert inbox.extract_otp("Use code 7731 to verify. Ref 99887766") == "7731"
    assert inbox.extract_otp("Your OTP for txn of Rs 2500 is 884422") == "884422"


def test_extract_otp_ignores_application_and_reference_numbers():
    body = "Application 1019 received\nYour application 1019 has been received and is waiting for verification."
    assert inbox.extract_otp(body) is None
    assert inbox.extract_otp("Order no. 55667 shipped") is None


def test_custom_pattern_wins():
    assert inbox.extract_otp("PIN-AB12 then 999999", r"PIN-(\w+)") == "AB12"


def test_mobile_numbers_normalise():
    assert inbox.norm_addr("+91 98950 00001") == inbox.norm_addr("9895000001") == "9895000001"
    assert inbox.norm_addr("QA Lead <QA.Lead@Example.com>") == "qa.lead@example.com"


def test_sms_webhook_and_smtp_sink(tmp_path):
    http_port, smtp_port = free_port(), free_port()
    srv = inbox.InboxServer(tmp_path / "inbox.db", "127.0.0.1", http_port, smtp_port).start()
    try:
        client = inbox.InboxClient(f"http://127.0.0.1:{http_port}")
        assert client.alive()
        since = time.time() - 1
        r = httpx.post(f"http://127.0.0.1:{http_port}/sms", json={"to": "+91 98950 00001", "text": "Your OTP is 482913"})
        assert r.status_code < 300
        assert client.wait_otp("9895000001", since, timeout=5) == "482913"
        with smtplib.SMTP("127.0.0.1", smtp_port, timeout=5) as smtp:
            smtp.sendmail("portal@example.com", ["citizen@example.com"],
                          "Subject: Application 1004 received\r\n\r\nDear citizen,\r\nwe received application 1004.\r\n")
        mail = client.wait("citizen@example.com", since, kind="email", timeout=5)
        assert mail and mail["subject"] == "Application 1004 received"
        assert inbox.extract_otp(mail["body"]) is None
    finally:
        srv.stop()

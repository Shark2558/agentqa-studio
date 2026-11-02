from agentqa.agents.zapscan import _sig

BASE = "http://portal.test"


def test_header_alerts_merge_with_agentqa_security_header_defect():
    assert _sig({"pluginId": "10038", "url": BASE + "/"}, BASE)[0] == "security:headers"
    assert _sig({"pluginId": "10020", "url": BASE + "/apply"}, BASE)[0] == "security:headers"


def test_csrf_and_xss_map_to_the_same_signatures_as_the_tests():
    assert _sig({"pluginId": "10202", "url": BASE + "/apply"}, BASE)[0] == "security:csrf"
    sig, title = _sig({"pluginId": "40012", "url": BASE + "/search?q=x", "param": "q"}, BASE)
    assert sig == "xss:/search:q" and "q" in title


def test_unknown_alert_keeps_its_own_signature():
    assert _sig({"pluginId": "12345", "url": BASE + "/", "alert": "Something odd"}, BASE) == ("zap:12345", "Something odd (OWASP ZAP)")

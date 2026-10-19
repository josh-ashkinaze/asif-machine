import os
import time

import requests

_last_alert_sent = None  # module-level throttle state


def send_error_alert(error_type="API_ERROR", error_message="", throttle_minutes=15):
    """Post a Slack alert on any autocomplete error, throttled to once per throttle_minutes."""
    global _last_alert_sent
    now = time.time()
    if _last_alert_sent and (now - _last_alert_sent) < throttle_minutes * 60:
        return False
    url = os.getenv("SLACK_WEBHOOK_URL")
    if not url:
        return False
    text = f"{error_type} error in autocomplete.\n{error_message}" if error_message else f"{error_type} error in autocomplete."
    requests.post(url, json={"text": text})
    _last_alert_sent = now
    return True

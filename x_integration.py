import os
import sys

existing_requests = sys.modules.get("requests")
if existing_requests is not None and not hasattr(existing_requests, "__path__"):
    del sys.modules["requests"]

import requests
from requests_oauthlib import OAuth1


POSTING_ENABLED_ENV = "PARKSIGNALS_X_POSTING_ENABLED"
REQUIRED_SECRET_NAMES = [
    "X_API_KEY",
    "X_API_SECRET",
    "X_ACCESS_TOKEN",
    "X_ACCESS_TOKEN_SECRET",
]
OPTIONAL_SECRET_NAMES = [
    "X_BEARER_TOKEN",
]
VERIFY_CREDENTIALS_URL = "https://api.twitter.com/1.1/account/verify_credentials.json"
CREATE_TWEET_URL = "https://api.twitter.com/2/tweets"
MAX_POST_CHARACTERS = 280
DEFAULT_TIMEOUT_SECONDS = 15


class XIntegrationError(RuntimeError):
    pass


def env_value_present(name):
    return bool(os.getenv(name, "").strip())


def posting_enabled():
    return os.getenv(POSTING_ENABLED_ENV, "false").strip().lower() == "true"


def credential_values():
    return {name: os.getenv(name, "").strip() for name in REQUIRED_SECRET_NAMES}


def missing_required_credentials():
    return [name for name, value in credential_values().items() if not value]


def oauth1_auth():
    missing = missing_required_credentials()
    if missing:
        raise XIntegrationError("Missing required X credentials: " + ", ".join(missing))
    credentials = credential_values()
    return OAuth1(
        credentials["X_API_KEY"],
        credentials["X_API_SECRET"],
        credentials["X_ACCESS_TOKEN"],
        credentials["X_ACCESS_TOKEN_SECRET"],
    )


def safe_error_text(response):
    text = response.text or ""
    text = " ".join(text.split())
    if len(text) > 240:
        text = text[:237] + "..."
    return text


def connection_status():
    required = {name: env_value_present(name) for name in REQUIRED_SECRET_NAMES}
    optional = {name: env_value_present(name) for name in OPTIONAL_SECRET_NAMES}
    missing_required = [name for name, present in required.items() if not present]

    return {
        "posting_connected": False,
        "posting_enabled": posting_enabled(),
        "posting_transport_configured": True,
        "manual_connection_test_available": True,
        "ready_for_manual_connection_test": not missing_required,
        "required_credentials_present": required,
        "optional_credentials_present": optional,
        "missing_required_credentials": missing_required,
        "safety_mode": "posting_disabled_until_PARKSIGNALS_X_POSTING_ENABLED_true",
    }


def verify_connection(timeout=DEFAULT_TIMEOUT_SECONDS):
    status = connection_status()
    result = {
        **status,
        "connection_test_passed": False,
        "connection_test_url": VERIFY_CREDENTIALS_URL,
        "http_status": None,
        "authenticated_user": None,
        "error": None,
    }

    if status["missing_required_credentials"]:
        result["error"] = "missing_required_credentials"
        return result

    try:
        response = requests.get(
            VERIFY_CREDENTIALS_URL,
            auth=oauth1_auth(),
            params={"skip_status": "true", "include_entities": "false"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        result["error"] = exc.__class__.__name__
        return result

    result["http_status"] = response.status_code
    if response.status_code != 200:
        result["error"] = safe_error_text(response) or f"HTTP {response.status_code}"
        return result

    payload = response.json()
    result["posting_connected"] = True
    result["connection_test_passed"] = True
    result["authenticated_user"] = {
        "id": payload.get("id_str") or str(payload.get("id", "")),
        "username": payload.get("screen_name"),
        "name": payload.get("name"),
    }
    return result


def connection_status_text(status=None):
    status = status or connection_status()
    lines = ["X connection status"]
    lines.append(f"Posting connected: {str(status['posting_connected']).lower()}")
    lines.append(f"Posting enabled: {str(status['posting_enabled']).lower()}")
    lines.append(
        "Ready for manual connection test: "
        + str(status["ready_for_manual_connection_test"]).lower()
    )
    if "connection_test_passed" in status:
        lines.append("Connection test passed: " + str(status["connection_test_passed"]).lower())
    if status.get("http_status") is not None:
        lines.append(f"X HTTP status: {status['http_status']}")
    if status.get("authenticated_user"):
        user = status["authenticated_user"]
        lines.append(
            "Authenticated user: "
            + "@"
            + str(user.get("username") or "unknown")
            + " ("
            + str(user.get("name") or "unknown")
            + ")"
        )
    if status.get("error"):
        lines.append("Connection test error: " + str(status["error"]))
    lines.append("")
    lines.append("Required credentials:")
    for name, present in status["required_credentials_present"].items():
        label = "present" if present else "missing"
        lines.append(f"- {name}: {label}")
    lines.append("")
    lines.append("Optional credentials:")
    for name, present in status["optional_credentials_present"].items():
        label = "present" if present else "missing"
        lines.append(f"- {name}: {label}")
    if status["missing_required_credentials"]:
        lines.append("")
        lines.append(
            "Missing required credentials: "
            + ", ".join(status["missing_required_credentials"])
        )
    lines.append("")
    lines.append("No posts can be sent while PARKSIGNALS_X_POSTING_ENABLED is not true.")
    return "\n".join(lines)


def require_posting_enabled():
    if not posting_enabled():
        raise XIntegrationError(
            "X posting is disabled. Set PARKSIGNALS_X_POSTING_ENABLED=true "
            "only after manual approval."
        )


def publish_post(text, timeout=DEFAULT_TIMEOUT_SECONDS):
    require_posting_enabled()
    if not text or not text.strip():
        raise XIntegrationError("Post text is empty.")
    if len(text) > MAX_POST_CHARACTERS:
        raise XIntegrationError(
            f"Post text is {len(text)} characters; max is {MAX_POST_CHARACTERS}."
        )

    try:
        response = requests.post(
            CREATE_TWEET_URL,
            auth=oauth1_auth(),
            json={"text": text},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise XIntegrationError(f"X post request failed: {exc.__class__.__name__}") from exc

    if response.status_code not in {200, 201}:
        raise XIntegrationError(
            f"X post request failed with HTTP {response.status_code}: {safe_error_text(response)}"
        )

    payload = response.json()
    return {
        "posted": True,
        "tweet_id": payload.get("data", {}).get("id"),
        "text": payload.get("data", {}).get("text", text),
    }

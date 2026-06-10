import os


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


def env_value_present(name):
    return bool(os.getenv(name, "").strip())


def posting_enabled():
    return os.getenv(POSTING_ENABLED_ENV, "false").strip().lower() == "true"


def connection_status():
    required = {
        name: env_value_present(name)
        for name in REQUIRED_SECRET_NAMES
    }
    optional = {
        name: env_value_present(name)
        for name in OPTIONAL_SECRET_NAMES
    }
    missing_required = [
        name
        for name, present in required.items()
        if not present
    ]

    return {
        "posting_connected": False,
        "posting_enabled": posting_enabled(),
        "ready_for_manual_connection_test": not missing_required,
        "required_credentials_present": required,
        "optional_credentials_present": optional,
        "missing_required_credentials": missing_required,
        "safety_mode": "posting_disabled_until_PARKSIGNALS_X_POSTING_ENABLED_true",
    }


def connection_status_text(status=None):
    status = status or connection_status()
    lines = ["X connection status"]
    lines.append(f"Posting connected: {str(status['posting_connected']).lower()}")
    lines.append(f"Posting enabled: {str(status['posting_enabled']).lower()}")
    lines.append(
        "Ready for manual connection test: "
        + str(status["ready_for_manual_connection_test"]).lower()
    )
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
        raise RuntimeError(
            "X posting is disabled. Set PARKSIGNALS_X_POSTING_ENABLED=true "
            "only after manual approval."
        )


def publish_post(_text):
    require_posting_enabled()
    raise NotImplementedError("X posting transport is not connected yet.")

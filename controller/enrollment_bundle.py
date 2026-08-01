"""Short-lived, root-only Agent enrollment bundles."""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile

from node_contract import ContractError, validate_node_id


BUNDLE_VERSION = 1
MAX_LIFETIME_SECONDS = 86400


class BundleError(ValueError):
    """Raised when an Agent enrollment bundle is invalid or expired."""


def _utc(value, field):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as error:
            raise BundleError(f"{field} is not a valid timestamp") from error
    else:
        raise BundleError(f"{field} is not a valid timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BundleError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _stamp(value):
    return _utc(value, "timestamp").isoformat().replace("+00:00", "Z")


def _text(value, field, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise BundleError(f"{field} is invalid")
    if any(ord(character) < 32 for character in value):
        raise BundleError(f"{field} contains control characters")
    return value


def create_bundle(
    enrollment,
    *,
    display_name,
    broker_host,
    broker_port=1883,
    tls=False,
    ca_certificate="",
    now=None,
    lifetime_seconds=900,
):
    current = _utc(now or datetime.now(timezone.utc), "now")
    if (
        not isinstance(lifetime_seconds, int)
        or isinstance(lifetime_seconds, bool)
        or not 60 <= lifetime_seconds <= MAX_LIFETIME_SECONDS
    ):
        raise BundleError("lifetime_seconds must be between 60 and 86400")
    try:
        validate_node_id(enrollment.node_id)
    except ContractError as error:
        raise BundleError(str(error)) from error
    if not isinstance(broker_port, int) or not 1 <= broker_port <= 65535:
        raise BundleError("broker_port is invalid")
    if not isinstance(tls, bool):
        raise BundleError("tls must be boolean")
    if not isinstance(ca_certificate, str):
        raise BundleError("ca_certificate must be a string")
    return {
        "bundle_version": BUNDLE_VERSION,
        "role": "agent",
        "issued_at": _stamp(current),
        "expires_at": _stamp(current + timedelta(seconds=lifetime_seconds)),
        "node": {
            "id": enrollment.node_id,
            "display_name": _text(display_name, "display_name", 80),
        },
        "mqtt": {
            "host": _text(broker_host, "broker_host", 255),
            "port": broker_port,
            "username": _text(enrollment.username, "username", 128),
            "password": _text(enrollment.password, "password", 512),
            "tls": tls,
            "ca_certificate": ca_certificate,
        },
        "monitor": {
            "publish_interval": 15,
            "health_check_interval": 300,
            "update_check_interval": 86400,
            "monitor_network": False,
            "allow_remote_actions": False,
        },
    }


def validate_bundle(bundle, *, now=None):
    if not isinstance(bundle, dict) or set(bundle) != {
        "bundle_version",
        "role",
        "issued_at",
        "expires_at",
        "node",
        "mqtt",
        "monitor",
    }:
        raise BundleError("bundle fields do not match version 1")
    if bundle["bundle_version"] != BUNDLE_VERSION or bundle["role"] != "agent":
        raise BundleError("unsupported enrollment bundle")
    current = _utc(now or datetime.now(timezone.utc), "now")
    issued = _utc(bundle["issued_at"], "issued_at")
    expires = _utc(bundle["expires_at"], "expires_at")
    if expires <= issued or (expires - issued).total_seconds() > MAX_LIFETIME_SECONDS:
        raise BundleError("bundle lifetime is invalid")
    if issued > current + timedelta(minutes=5):
        raise BundleError("bundle issued_at is in the future")
    if current >= expires:
        raise BundleError("enrollment bundle has expired")

    node = bundle["node"]
    mqtt = bundle["mqtt"]
    monitor = bundle["monitor"]
    if not isinstance(node, dict) or set(node) != {"id", "display_name"}:
        raise BundleError("node fields are invalid")
    try:
        validate_node_id(node["id"])
    except ContractError as error:
        raise BundleError(str(error)) from error
    _text(node["display_name"], "display_name", 80)

    if not isinstance(mqtt, dict) or set(mqtt) != {
        "host",
        "port",
        "username",
        "password",
        "tls",
        "ca_certificate",
    }:
        raise BundleError("mqtt fields are invalid")
    _text(mqtt["host"], "mqtt.host", 255)
    _text(mqtt["username"], "mqtt.username", 128)
    _text(mqtt["password"], "mqtt.password", 512)
    if not isinstance(mqtt["port"], int) or not 1 <= mqtt["port"] <= 65535:
        raise BundleError("mqtt.port is invalid")
    if not isinstance(mqtt["tls"], bool) or not isinstance(
        mqtt["ca_certificate"],
        str,
    ):
        raise BundleError("mqtt TLS fields are invalid")
    if mqtt["tls"] and not mqtt["ca_certificate"].strip():
        raise BundleError("TLS enrollment requires a CA certificate")

    expected_monitor = {
        "publish_interval",
        "health_check_interval",
        "update_check_interval",
        "monitor_network",
        "allow_remote_actions",
    }
    if not isinstance(monitor, dict) or set(monitor) != expected_monitor:
        raise BundleError("monitor fields are invalid")
    for field in (
        "publish_interval",
        "health_check_interval",
        "update_check_interval",
    ):
        if not isinstance(monitor[field], int) or isinstance(monitor[field], bool):
            raise BundleError(f"monitor.{field} is invalid")
    if monitor["publish_interval"] < 10:
        raise BundleError("publish interval must be at least 10 seconds")
    for field in ("monitor_network", "allow_remote_actions"):
        if not isinstance(monitor[field], bool):
            raise BundleError(f"monitor.{field} must be boolean")
    return bundle


def write_bundle(path, bundle):
    validate_bundle(bundle, now=bundle["issued_at"])
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(bundle, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def load_bundle(path, *, now=None):
    target = Path(path)
    try:
        bundle = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BundleError("enrollment bundle cannot be read") from error
    return validate_bundle(bundle, now=now)

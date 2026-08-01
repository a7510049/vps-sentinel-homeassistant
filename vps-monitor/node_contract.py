"""Versioned VPS Sentinel node contract shared by current and future agents."""

from datetime import datetime, timezone
import re


SCHEMA_VERSION = "1.0"
TOPIC_ROOT = "vps-sentinel/v1/nodes"
MESSAGE_TYPES = frozenset({
    "availability",
    "event",
    "health",
    "metadata",
    "resources",
})
NODE_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$")
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
SENSITIVE_KEYS = frozenset({
    "authorization",
    "mqtt_password",
    "password",
    "private_key",
    "secret",
    "token",
})


class ContractError(ValueError):
    """Raised when a node message violates the public contract."""


def validate_node_id(node_id):
    """Return a stable node ID or raise without silently rewriting it."""
    if not isinstance(node_id, str) or not NODE_ID_PATTERN.fullmatch(node_id):
        raise ContractError(
            "node_id must be 1-64 lowercase letters, digits, _ or -; "
            "it must start and end with a letter or digit"
        )
    return node_id


def topic_for(node_id, message_type):
    """Return the versioned MQTT topic for one node message stream."""
    validate_node_id(node_id)
    if message_type not in MESSAGE_TYPES:
        raise ContractError(f"unsupported message_type: {message_type!r}")
    stream = "events" if message_type == "event" else message_type
    return f"{TOPIC_ROOT}/{node_id}/{stream}"


def _required_text(value, field, maximum):
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string")
    if len(value) > maximum:
        raise ContractError(f"{field} must not exceed {maximum} characters")
    if any(ord(character) < 32 for character in value):
        raise ContractError(f"{field} must not contain control characters")
    return value


def _rfc3339_utc(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as error:
            raise ContractError("observed_at must be an RFC 3339 timestamp") from error
    else:
        raise ContractError("observed_at must be a datetime or RFC 3339 string")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError("observed_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _names(values, field):
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple, set)):
        raise ContractError(f"{field} must be a list")
    normalized = []
    for value in values:
        if not isinstance(value, str) or not NAME_PATTERN.fullmatch(value):
            raise ContractError(f"{field} contains an invalid name")
        normalized.append(value)
    if len(normalized) > 64:
        raise ContractError(f"{field} must not contain more than 64 items")
    return sorted(set(normalized))


def _labels(labels):
    if labels is None:
        return {}
    if not isinstance(labels, dict) or len(labels) > 32:
        raise ContractError("labels must be an object with at most 32 entries")
    normalized = {}
    for key, value in labels.items():
        if not isinstance(key, str) or not NAME_PATTERN.fullmatch(key):
            raise ContractError("labels contains an invalid key")
        normalized[key] = _required_text(value, f"labels.{key}", 80)
    return dict(sorted(normalized.items()))


def _reject_sensitive(value, path="data"):
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized_key = str(key).lower().replace("-", "_")
            if normalized_key in SENSITIVE_KEYS:
                raise ContractError(f"{path}.{key} may expose a secret")
            _reject_sensitive(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_sensitive(nested, f"{path}[{index}]")


def build_envelope(
    *,
    node_id,
    display_name,
    agent_version,
    message_type,
    observed_at,
    sequence,
    capabilities,
    data,
    provider=None,
    region=None,
    labels=None,
):
    """Build a deterministic v1 node message after validating public fields."""
    validate_node_id(node_id)
    if message_type not in MESSAGE_TYPES:
        raise ContractError(f"unsupported message_type: {message_type!r}")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        raise ContractError("sequence must be a non-negative integer")
    if not isinstance(data, dict):
        raise ContractError("data must be an object")
    _reject_sensitive(data)

    node = {
        "id": node_id,
        "display_name": _required_text(display_name, "display_name", 80),
        "agent_version": _required_text(agent_version, "agent_version", 32),
        "capabilities": _names(capabilities, "capabilities"),
        "labels": _labels(labels),
    }
    if provider is not None:
        node["provider"] = _required_text(provider, "provider", 80)
    if region is not None:
        node["region"] = _required_text(region, "region", 80)

    return {
        "schema_version": SCHEMA_VERSION,
        "message_type": message_type,
        "node": node,
        "observed_at": _rfc3339_utc(observed_at),
        "sequence": sequence,
        "data": data,
    }

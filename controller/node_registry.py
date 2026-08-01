"""In-memory multi-node registry for the VPS Sentinel 1.0 Controller."""

from copy import deepcopy
from datetime import datetime, timezone
import json

from node_contract import ContractError, parse_topic, validate_envelope


DEFAULT_TTLS = {
    "resources": 60,
    "health": 600,
    "metadata": 86400,
}


class RegistryError(ValueError):
    """Base error for rejected Controller input."""


class IdentityMismatchError(RegistryError):
    """The MQTT topic and signed-in node claim different identities."""


class DuplicateNodeError(RegistryError):
    """One node ID is already bound to another credential."""


class StaleMessageError(RegistryError):
    """A delayed or replayed message must not replace newer state."""


def _utc_datetime(value, field):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as error:
            raise RegistryError(f"{field} is not a valid timestamp") from error
    else:
        raise RegistryError(f"{field} is not a valid timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RegistryError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


class NodeRegistry:
    """Validate, bind and summarize node streams without trusting MQTT data."""

    def __init__(self, *, clock=None, stream_ttls=None, offline_after=90):
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.stream_ttls = {**DEFAULT_TTLS, **(stream_ttls or {})}
        self.offline_after = offline_after
        self._credential_bindings = {}
        self._nodes = {}

    def ingest(self, topic, raw_payload, *, credential_id, received_at=None):
        if not isinstance(credential_id, str) or not credential_id.strip():
            raise RegistryError("credential_id is required")
        if len(credential_id) > 128:
            raise RegistryError("credential_id is too long")
        if isinstance(raw_payload, bytes):
            if len(raw_payload) > 65536:
                raise RegistryError("payload exceeds 64 KiB")
            try:
                raw_payload = raw_payload.decode("utf-8")
            except UnicodeDecodeError as error:
                raise RegistryError("payload is not UTF-8") from error
        if not isinstance(raw_payload, str) or len(raw_payload.encode("utf-8")) > 65536:
            raise RegistryError("payload must be UTF-8 JSON within 64 KiB")
        try:
            candidate = json.loads(raw_payload)
            envelope = validate_envelope(candidate)
            topic_node_id, message_type = parse_topic(topic)
        except (json.JSONDecodeError, ContractError) as error:
            raise RegistryError(str(error)) from error

        node_id = envelope["node"]["id"]
        if topic_node_id != node_id or message_type != envelope["message_type"]:
            raise IdentityMismatchError(
                "topic identity or stream does not match the envelope"
            )

        bound_credential = self._credential_bindings.get(node_id)
        if bound_credential is not None and bound_credential != credential_id:
            raise DuplicateNodeError(
                f"node_id {node_id!r} is already bound to another credential"
            )

        received = _utc_datetime(received_at or self.clock(), "received_at")
        observed = _utc_datetime(envelope["observed_at"], "observed_at")
        record = self._nodes.get(node_id)
        previous = record and record["streams"].get(message_type)
        if previous is not None:
            previous_observed = _utc_datetime(
                previous["envelope"]["observed_at"],
                "previous observed_at",
            )
            if (
                envelope["sequence"] <= previous["envelope"]["sequence"]
                and observed <= previous_observed
            ):
                raise StaleMessageError(
                    "message is older than or equal to the stored stream state"
                )

        if record is None:
            record = {
                "node": envelope["node"],
                "streams": {},
                "last_received_at": received,
            }
            self._nodes[node_id] = record
        self._credential_bindings[node_id] = credential_id
        record["node"] = envelope["node"]
        record["last_received_at"] = max(record["last_received_at"], received)
        record["streams"][message_type] = {
            "envelope": envelope,
            "received_at": received,
        }
        return self.node(node_id, now=received)

    def node(self, node_id, *, now=None):
        if node_id not in self._nodes:
            return None
        current = _utc_datetime(now or self.clock(), "now")
        record = self._nodes[node_id]
        streams = record["streams"]
        availability = streams.get("availability")
        if availability is not None:
            availability_value = availability["envelope"]["data"].get("status")
            online = availability_value == "online"
        else:
            age = (current - record["last_received_at"]).total_seconds()
            online = age <= self.offline_after

        stale_streams = []
        for stream, ttl in self.stream_ttls.items():
            state = streams.get(stream)
            if state is None:
                stale_streams.append(stream)
                continue
            age = (current - state["received_at"]).total_seconds()
            if age > ttl:
                stale_streams.append(stream)

        health = streams.get("health", {}).get("envelope", {}).get("data", {})
        if not online:
            status = "offline"
        elif "resources" in stale_streams or "health" in stale_streams:
            status = "stale"
        else:
            status = health.get("health_status", "normal")

        public_streams = {
            name: {
                "observed_at": state["envelope"]["observed_at"],
                "received_at": state["received_at"].isoformat().replace(
                    "+00:00", "Z"
                ),
                "sequence": state["envelope"]["sequence"],
                "data": deepcopy(state["envelope"]["data"]),
            }
            for name, state in streams.items()
        }
        return {
            "node": deepcopy(record["node"]),
            "online": online,
            "status": status,
            "stale_streams": sorted(stale_streams),
            "last_received_at": record["last_received_at"].isoformat().replace(
                "+00:00", "Z"
            ),
            "streams": public_streams,
        }

    def snapshot(self, *, now=None):
        current = now or self.clock()
        return [
            self.node(node_id, now=current)
            for node_id in sorted(self._nodes)
        ]

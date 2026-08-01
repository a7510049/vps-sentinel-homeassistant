"""Persistent node enrollment and least-privilege Mosquitto ACL generation."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import tempfile

from node_contract import ContractError, validate_node_id


STORE_VERSION = 1
USERNAME_PREFIX = "vps-node-"


class EnrollmentError(ValueError):
    """Raised when an enrollment operation cannot be completed safely."""


@dataclass(frozen=True, repr=False)
class Enrollment:
    node_id: str
    username: str
    password: str

    def __repr__(self):
        return (
            f"Enrollment(node_id={self.node_id!r}, "
            f"username={self.username!r}, password=<redacted>)"
        )


def _timestamp(value=None):
    current = value or datetime.now(timezone.utc)
    if not isinstance(current, datetime):
        raise EnrollmentError("now must be a datetime")
    if current.tzinfo is None or current.utcoffset() is None:
        raise EnrollmentError("now must include a timezone")
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _display_name(value):
    if not isinstance(value, str) or not value.strip():
        raise EnrollmentError("display_name must be a non-empty string")
    if len(value) > 80 or any(ord(character) < 32 for character in value):
        raise EnrollmentError("display_name is invalid")
    return value


class EnrollmentStore:
    """Store public enrollment metadata; generated passwords are returned once."""

    def __init__(self, path):
        self.path = Path(path)
        self._nodes = {}
        self.load()

    def load(self):
        if not self.path.exists():
            self._nodes = {}
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise EnrollmentError("enrollment store cannot be read") from error
        if (
            not isinstance(payload, dict)
            or payload.get("version") != STORE_VERSION
            or not isinstance(payload.get("nodes"), dict)
        ):
            raise EnrollmentError("enrollment store has an unsupported format")
        nodes = {}
        for node_id, record in payload["nodes"].items():
            try:
                validate_node_id(node_id)
            except ContractError as error:
                raise EnrollmentError("enrollment store contains an invalid node_id") from error
            expected_username = f"{USERNAME_PREFIX}{node_id}"
            if (
                not isinstance(record, dict)
                or record.get("username") != expected_username
                or not isinstance(record.get("display_name"), str)
                or not isinstance(record.get("created_at"), str)
            ):
                raise EnrollmentError("enrollment store contains an invalid record")
            if any(
                key.lower() in {"password", "secret", "token"}
                for key in record
            ):
                raise EnrollmentError("enrollment store must not contain secrets")
            nodes[node_id] = record
        self._nodes = nodes

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": STORE_VERSION,
            "nodes": {
                node_id: self._nodes[node_id]
                for node_id in sorted(self._nodes)
            },
        }
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(payload, temporary, ensure_ascii=False, indent=2)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, self.path)
            os.chmod(self.path, 0o600)
        except OSError as error:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise EnrollmentError("enrollment store cannot be saved") from error

    def register(self, node_id, display_name, *, now=None):
        try:
            validate_node_id(node_id)
        except ContractError as error:
            raise EnrollmentError(str(error)) from error
        display_name = _display_name(display_name)
        if node_id in self._nodes:
            raise EnrollmentError(f"node_id {node_id!r} is already enrolled")
        username = f"{USERNAME_PREFIX}{node_id}"
        created_at = _timestamp(now)
        self._nodes[node_id] = {
            "username": username,
            "display_name": display_name,
            "created_at": created_at,
            "rotated_at": None,
        }
        self._save()
        return Enrollment(
            node_id=node_id,
            username=username,
            password=secrets.token_urlsafe(32),
        )

    def rotate(self, node_id, *, now=None):
        if node_id not in self._nodes:
            raise EnrollmentError(f"node_id {node_id!r} is not enrolled")
        self._nodes[node_id]["rotated_at"] = _timestamp(now)
        self._save()
        return Enrollment(
            node_id=node_id,
            username=self._nodes[node_id]["username"],
            password=secrets.token_urlsafe(32),
        )

    def revoke(self, node_id):
        if node_id not in self._nodes:
            raise EnrollmentError(f"node_id {node_id!r} is not enrolled")
        record = self._nodes.pop(node_id)
        self._save()
        return record["username"]

    def credential_for(self, node_id):
        record = self._nodes.get(node_id)
        return record and record["username"]

    def nodes(self):
        return [
            {
                "node_id": node_id,
                **self._nodes[node_id],
            }
            for node_id in sorted(self._nodes)
        ]

    def acl_text(self, controller_username="vps-controller"):
        if not isinstance(controller_username, str) or not controller_username:
            raise EnrollmentError("controller_username is required")
        lines = [
            f"user {controller_username}",
            "topic read vps-sentinel/v1/nodes/+/+",
            "topic write vps-sentinel/v1/controller/#",
            "topic write homeassistant/#",
        ]
        for node_id in sorted(self._nodes):
            username = self._nodes[node_id]["username"]
            root = f"vps-sentinel/v1/nodes/{node_id}"
            lines.extend([
                "",
                f"user {username}",
                f"topic write {root}/metadata",
                f"topic write {root}/resources",
                f"topic write {root}/health",
                f"topic write {root}/availability",
                f"topic write {root}/events",
                f"topic read {root}/commands",
            ])
        return "\n".join(lines) + "\n"

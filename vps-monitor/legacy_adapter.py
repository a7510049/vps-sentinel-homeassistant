"""Compatibility adapter from retained 0.9.x payloads to the v1 contract."""

from node_contract import ContractError, build_envelope, validate_node_id


RESOURCE_FIELDS = (
    "cpu_percent",
    "memory_percent",
    "memory_used_gb",
    "memory_available_gb",
    "memory_total_gb",
    "download_mbps",
    "upload_mbps",
    "reporting",
)
HEALTH_FIELDS = (
    "disk_percent",
    "disk_used_gb",
    "disk_free_gb",
    "disk_total_gb",
    "load_1",
    "load_5",
    "load_15",
    "uptime_hours",
    "boot_time",
    "security_updates",
    "docker_running",
    "docker_unhealthy",
    "failed_services",
    "resource_overload",
    "disk_low",
    "service_problem",
    "reboot_required",
    "health_status",
)


class LegacyCompatibilityError(ContractError):
    """Raised when a 0.9.x installation needs user action before migration."""


def legacy_capabilities(*, monitor_network, docker_present, remote_actions):
    capabilities = ["health.basic", "resources.basic"]
    if monitor_network:
        capabilities.append("network.throughput")
    if docker_present:
        capabilities.append("runtime.docker")
    if remote_actions:
        capabilities.append("maintenance.actions")
    return capabilities


def migration_node_id(vps_id):
    """Validate an existing VPS_ID without changing Home Assistant identity."""
    try:
        return validate_node_id(vps_id)
    except ContractError as error:
        raise LegacyCompatibilityError(
            "現有 VPS_ID 無法直接遷移到 1.0；請先建立新的穩定 node_id，"
            "並使用 entity 遷移預覽，系統不會自動改寫識別碼"
        ) from error


def _copy_fields(payload, allowed_fields):
    if not isinstance(payload, dict):
        raise LegacyCompatibilityError("legacy payload must be an object")
    return {
        field: payload[field]
        for field in allowed_fields
        if field in payload
    }


def _observed_at(payload, observed_at):
    timestamp = observed_at or payload.get("last_report")
    if not timestamp:
        raise LegacyCompatibilityError(
            "legacy payload has no last_report; observed_at is required"
        )
    return timestamp


def _node_metadata(status_payload):
    provider = status_payload.get("provider")
    if provider in (None, "", "unknown"):
        provider = None
    country_code = status_payload.get("country_code")
    labels = {}
    if (
        isinstance(country_code, str)
        and len(country_code) == 2
        and country_code.lower() != "unknown"
    ):
        labels["country_code"] = country_code.lower()
    return provider, labels


def resource_envelope(
    *,
    vps_id,
    display_name,
    agent_version,
    payload,
    sequence,
    capabilities,
    observed_at=None,
):
    """Map the fast 0.9.x resource payload using an explicit allowlist."""
    return build_envelope(
        node_id=migration_node_id(vps_id),
        display_name=display_name,
        agent_version=agent_version,
        message_type="resources",
        observed_at=_observed_at(payload, observed_at),
        sequence=sequence,
        capabilities=capabilities,
        data=_copy_fields(payload, RESOURCE_FIELDS),
    )


def health_envelope(
    *,
    vps_id,
    display_name,
    agent_version,
    payload,
    sequence,
    capabilities,
    observed_at=None,
):
    """Map the retained 0.9.x status payload using an explicit allowlist."""
    provider, labels = _node_metadata(payload)
    return build_envelope(
        node_id=migration_node_id(vps_id),
        display_name=display_name,
        agent_version=agent_version,
        message_type="health",
        observed_at=_observed_at(payload, observed_at),
        sequence=sequence,
        capabilities=capabilities,
        data=_copy_fields(payload, HEALTH_FIELDS),
        provider=provider,
        labels=labels,
    )


def metadata_envelope(
    *,
    vps_id,
    display_name,
    agent_version,
    status_payload,
    sequence,
    capabilities,
    observed_at=None,
    architecture=None,
):
    """Map identity and platform information without copying arbitrary fields."""
    provider, labels = _node_metadata(status_payload)
    data = {}
    if status_payload.get("os_name"):
        data["os_name"] = status_payload["os_name"]
    if architecture:
        data["architecture"] = architecture
    return build_envelope(
        node_id=migration_node_id(vps_id),
        display_name=display_name,
        agent_version=agent_version,
        message_type="metadata",
        observed_at=_observed_at(status_payload, observed_at),
        sequence=sequence,
        capabilities=capabilities,
        data=data,
        provider=provider,
        labels=labels,
    )

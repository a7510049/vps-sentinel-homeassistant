import json
from pathlib import Path
import sys


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "vps-monitor"))

from node_contract import validate_envelope


envelope = validate_envelope(json.load(sys.stdin))
if envelope["message_type"] != "resources":
    raise SystemExit("Go prototype did not emit resources")
required = {
    "cpu_percent",
    "memory_percent",
    "memory_used_gb",
    "memory_available_gb",
    "memory_total_gb",
    "disk_percent",
    "disk_used_gb",
    "disk_free_gb",
    "disk_total_gb",
    "reporting",
}
missing = required - set(envelope["data"])
if missing:
    raise SystemExit(f"Go prototype is missing metrics: {sorted(missing)}")
print("Go envelope matches the Python v1 contract")

#!/usr/bin/env python3
"""Manage Agent enrollment, Broker credentials and one-time bundles together."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

CONTROLLER_DIR = Path(__file__).resolve().parent
REPO_ROOT = CONTROLLER_DIR.parent
sys.path.insert(0, str(CONTROLLER_DIR))
sys.path.insert(0, str(REPO_ROOT / "vps-monitor"))

from bootstrap import read_environment
from broker_policy import BrokerFilesTransaction, BrokerPolicy, BrokerPolicyError
from enrollment import EnrollmentError, EnrollmentStore
from enrollment_bundle import BundleError, create_bundle, write_bundle


STORE_PATH = Path("/var/lib/vps-sentinel-controller/enrollments.json")
BUNDLE_DIR = Path("/root/vps-sentinel-enrollments")


def _snapshot(path):
    if not path.exists():
        return None
    metadata = path.stat()
    return (
        path.read_bytes(),
        stat.S_IMODE(metadata.st_mode),
        metadata.st_uid,
        metadata.st_gid,
    )


def _atomic_restore(path, snapshot):
    if snapshot is None:
        path.unlink(missing_ok=True)
        return
    content, mode, uid, gid = snapshot
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        os.chown(path, uid, gid)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _secure_store_owner():
    os.chmod(STORE_PATH, 0o600)
    shutil.chown(
        STORE_PATH,
        user="vps-sentinel-controller",
        group="vps-sentinel-controller",
    )


def _run(command):
    return subprocess.run(
        command,
        timeout=60,
        check=False,
    ).returncode == 0


def _restart():
    if not _run(["systemctl", "restart", "mosquitto"]):
        return False
    if not _run(["systemctl", "restart", "vps-sentinel-controller"]):
        return False
    return _run([
        "systemctl",
        "is-active",
        "--quiet",
        "vps-sentinel-controller",
    ])


def _legacy_bindings():
    monitor = read_environment("/etc/vps-monitor.env")
    if monitor.get("VPS_ID") and monitor.get("MQTT_USERNAME"):
        return {monitor["MQTT_USERNAME"]: [monitor["VPS_ID"]]}
    return {}


def _policy(store, controller_username):
    return BrokerPolicy(
        store,
        controller_username=controller_username,
        legacy_bindings=_legacy_bindings(),
    ).render_acl()


def _display_name(store, node_id):
    for record in store.nodes():
        if record["node_id"] == node_id:
            return record["display_name"]
    raise EnrollmentError(f"node_id {node_id!r} is not enrolled")


def main():
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)

    create = subcommands.add_parser("create")
    create.add_argument("node_id")
    create.add_argument("--name", required=True)
    create.add_argument("--broker-host", required=True)
    create.add_argument("--broker-port", type=int, default=1883)
    create.add_argument("--tls", action="store_true")
    create.add_argument("--ca-file")
    create.add_argument("--expires-in", type=int, default=900)
    create.add_argument("--output")

    rotate = subcommands.add_parser("rotate")
    rotate.add_argument("node_id")
    rotate.add_argument("--broker-host", required=True)
    rotate.add_argument("--broker-port", type=int, default=1883)
    rotate.add_argument("--tls", action="store_true")
    rotate.add_argument("--ca-file")
    rotate.add_argument("--expires-in", type=int, default=900)
    rotate.add_argument("--output")

    revoke = subcommands.add_parser("revoke")
    revoke.add_argument("node_id")

    subcommands.add_parser("list")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("節點註冊管理需要 root 權限")

    controller = read_environment("/etc/vps-sentinel-controller.env")
    controller_username = controller.get("MQTT_USERNAME", "vps-controller")
    store_snapshot = _snapshot(STORE_PATH)
    store = EnrollmentStore(STORE_PATH)

    if args.command == "list":
        print(json.dumps(store.nodes(), ensure_ascii=False, indent=2))
        return

    bundle_path = None
    removed_username = None
    try:
        if args.command == "create":
            result = store.register(
                args.node_id,
                args.name,
                now=datetime.now(timezone.utc),
            )
            display_name = args.name
        elif args.command == "rotate":
            display_name = _display_name(store, args.node_id)
            result = store.rotate(
                args.node_id,
                now=datetime.now(timezone.utc),
            )
        else:
            removed_username = store.revoke(args.node_id)
            result = None
            display_name = None

        if result is not None:
            ca_certificate = ""
            if args.tls:
                if not args.ca_file:
                    raise BundleError("--tls requires --ca-file")
                ca_certificate = Path(args.ca_file).read_text(encoding="utf-8")
            bundle = create_bundle(
                result,
                display_name=display_name,
                broker_host=args.broker_host,
                broker_port=args.broker_port,
                tls=args.tls,
                ca_certificate=ca_certificate,
                lifetime_seconds=args.expires_in,
            )
            bundle_path = Path(
                args.output
                or BUNDLE_DIR / f"{args.node_id}.json"
            )
            if bundle_path.exists():
                raise BundleError(
                    f"bundle already exists: {bundle_path}; move or remove it first"
                )
            write_bundle(bundle_path, bundle)

        _secure_store_owner()
        transaction = BrokerFilesTransaction(restarter=_restart)
        transaction.apply(
            credentials=(
                {result.username: result.password}
                if result is not None
                else {}
            ),
            remove_usernames=(
                [removed_username] if removed_username else []
            ),
            acl_text=_policy(store, controller_username),
        )
    except (BrokerPolicyError, BundleError, EnrollmentError, OSError) as error:
        _atomic_restore(STORE_PATH, store_snapshot)
        if bundle_path is not None:
            bundle_path.unlink(missing_ok=True)
        _run(["systemctl", "restart", "vps-sentinel-controller"])
        raise SystemExit(str(error)) from error

    if bundle_path is not None:
        expires = json.loads(
            bundle_path.read_text(encoding="utf-8")
        )["expires_at"]
        print(f"一次性 Agent bundle：{bundle_path}")
        print(f"有效期限：{expires}")
        print("請透過安全通道傳到目標 VPS，再執行：")
        print("  sudo bash install.sh --config /path/to/bundle.json")
    else:
        print(f"節點 {args.node_id} 已撤銷，Broker ACL 已同步。")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Safely register the Fleet Card through Home Assistant frontend config."""

import argparse
import os
from pathlib import Path
import re
import stat
import tempfile


DEFAULT_URL = "/local/vps-sentinel-fleet-card.js"
TOP_LEVEL = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*:")
FRONTEND = re.compile(r"^frontend:\s*(?:#.*)?$")
EXTRA_MODULE = re.compile(r"^  extra_module_url:\s*(?:#.*)?$")


class FrontendConfigError(ValueError):
    """Raised when an existing custom frontend block is unsafe to rewrite."""


def _block_end(lines, start):
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.strip() and not line.lstrip().startswith("#") and TOP_LEVEL.match(line):
            return index
    return len(lines)


def ensure_module_url(text, url=DEFAULT_URL):
    """Return (new_text, changed) while preserving unrelated YAML text."""
    if not isinstance(url, str) or not url.startswith("/") or any(
        value in url for value in ("\n", "\r", "'", '"')
    ):
        raise FrontendConfigError("invalid frontend module URL")

    lines = text.splitlines()
    frontend_indexes = [
        index
        for index, line in enumerate(lines)
        if line.startswith("frontend:") and not line.startswith((" ", "\t"))
    ]
    if len(frontend_indexes) > 1:
        raise FrontendConfigError("configuration contains duplicate frontend keys")

    if not frontend_indexes:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["frontend:", "  extra_module_url:", f"    - {url}"])
        return "\n".join(lines) + "\n", True

    frontend_index = frontend_indexes[0]
    if not FRONTEND.fullmatch(lines[frontend_index]):
        raise FrontendConfigError(
            "frontend uses an inline value or !include and cannot be edited safely"
        )
    frontend_end = _block_end(lines, frontend_index)
    module_indexes = [
        index
        for index in range(frontend_index + 1, frontend_end)
        if lines[index].startswith("  extra_module_url:")
    ]
    if len(module_indexes) > 1:
        raise FrontendConfigError("frontend contains duplicate extra_module_url keys")

    if not module_indexes:
        lines[frontend_end:frontend_end] = [
            "  extra_module_url:",
            f"    - {url}",
        ]
        return "\n".join(lines) + "\n", True

    module_index = module_indexes[0]
    if not EXTRA_MODULE.fullmatch(lines[module_index]):
        raise FrontendConfigError(
            "extra_module_url uses an inline value and cannot be edited safely"
        )
    module_end = frontend_end
    for index in range(module_index + 1, frontend_end):
        line = lines[index]
        if line.strip() and not line.lstrip().startswith("#") and not line.startswith("    "):
            module_end = index
            break

    for line in lines[module_index + 1:module_end]:
        match = re.match(r"^\s{4,}-\s+([^#]+?)(?:\s+#.*)?$", line)
        if match and match.group(1).strip().strip("'\"") == url:
            return text, False

    lines[module_end:module_end] = [f"    - {url}"]
    return "\n".join(lines) + "\n", True


def ensure_module_file(path, url=DEFAULT_URL):
    """Atomically update a configuration file and preserve its permissions."""
    path = Path(path)
    original = path.read_text(encoding="utf-8")
    updated, changed = ensure_module_url(original, url)
    if not changed:
        return False

    metadata = path.stat()
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as output:
            output.write(updated)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, stat.S_IMODE(metadata.st_mode))
        os.replace(temporary, path)
        os.chown(path, metadata.st_uid, metadata.st_gid)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("configuration")
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()
    try:
        changed = ensure_module_file(args.configuration, args.url)
    except (FrontendConfigError, OSError) as error:
        raise SystemExit(str(error)) from error
    print("updated" if changed else "already-registered")


if __name__ == "__main__":
    main()

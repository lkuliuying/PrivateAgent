#!/usr/bin/env python3
"""Create the three local secret files required by ``compose.yaml``.

The command never prints secret values, refuses to overwrite an existing
secret, and only writes beneath this repository.  Rotate secrets as a separate
operator action after stopping the stack and backing up its data.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SECRET_FILENAMES = ("api_token", "mysql_password", "mysql_root_password")


class ContainerSecretError(RuntimeError):
    """A secret path or write was rejected."""


def generate_secret_files(
    output_dir: Path,
    *,
    project_root: Path = PROJECT_ROOT,
) -> tuple[Path, ...]:
    root = project_root.resolve()
    target = output_dir.resolve()
    if not target.is_relative_to(root) or target == root:
        raise ContainerSecretError("secret directory must be a child of the project root")

    # Python's 0o700 directory mode maps poorly to ACLs in the Windows sandbox
    # and can make the creating process unable to write its own child files.
    # Windows operators apply an explicit ACL as documented; POSIX gets 0700.
    directory_mode = 0o777 if os.name == "nt" else 0o700
    target.mkdir(parents=True, exist_ok=True, mode=directory_mode)
    if not target.is_dir():
        raise ContainerSecretError("secret target is not a directory")

    paths = tuple(target / name for name in SECRET_FILENAMES)
    existing = [path.name for path in paths if path.exists()]
    if existing:
        raise ContainerSecretError(
            "refusing to overwrite existing container secrets: " + ", ".join(existing)
        )

    created: list[Path] = []
    try:
        for path in paths:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                stream.write(secrets.token_hex(32))
            path.chmod(0o600)
            created.append(path)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=PROJECT_ROOT / ".secrets",
        help="project-local output directory (default: .secrets)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm creation; existing files are never overwritten",
    )
    args = parser.parse_args()

    if not args.yes:
        print(
            json.dumps(
                {
                    "status": "preview",
                    "directory": str(args.out_dir.resolve()),
                    "files": list(SECRET_FILENAMES),
                    "values_printed": False,
                },
                ensure_ascii=False,
            )
        )
        return 2

    try:
        paths = generate_secret_files(args.out_dir)
    except ContainerSecretError as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}, ensure_ascii=False))
        return 1

    print(
        json.dumps(
            {
                "status": "created",
                "files": [str(path) for path in paths],
                "values_printed": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

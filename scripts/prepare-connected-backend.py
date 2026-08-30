"""Prepare a five-file backend patch, or verify it without importing the application.

Only fixed source paths are read. No environment files, credentials, database,
network, package installation or service changes are involved.
"""
import argparse
import ast
import difflib
import hashlib
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path

# The deployed feature was developed against this commit, not a future HEAD.
BASE_COMMIT = "debcd81d9b6084f8ab13f4c0423b9f14696b9496"
EXISTING = (
    "src/personal_assistant/config.py",
    "src/personal_assistant/main_api.py",
)
ADDED = (
    "src/personal_assistant/api/routes_admin_logs.py",
    "src/personal_assistant/api/routes_desktop_model.py",
    "src/personal_assistant/core/admin_logs.py",
)
SOURCES = EXISTING + ADDED


def digest(data):
    return hashlib.sha256(data).hexdigest()


def source_bytes(root, relative):
    """Read only regular source files within the canonical repository root."""
    path = root / relative
    if path.is_symlink() or path.resolve() != path:
        raise ValueError(f"Refusing redirected source path: {relative}")
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError(f"Not a regular source file: {relative}")
    return path.read_bytes().replace(b"\r\n", b"\n")


def syntax_check(data, relative):
    try:
        ast.parse(data.decode("utf-8"), filename=relative)
    except (SyntaxError, UnicodeError):
        raise ValueError(f"Invalid UTF-8 Python source: {relative}") from None


def git_output(root, *args):
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=False,
    )
    if result.returncode:
        raise ValueError("Cannot read the requested Git baseline; no bundle created")
    return result.stdout


def create_bundle(root, output, base_ref=BASE_COMMIT):
    root = root.resolve(strict=True)
    base = git_output(root, "rev-parse", "--verify", f"{base_ref}^{{commit}}").decode().strip()
    entries = []
    patches = []
    for relative in SOURCES:
        before = None
        if relative in EXISTING:
            before = git_output(root, "show", f"{base}:{relative}").replace(b"\r\n", b"\n")
        after = source_bytes(root, relative)
        if after is None:
            raise ValueError(f"Missing source: {relative}")
        syntax_check(after, relative)
        if before == after:
            raise ValueError(f"Expected a feature change in: {relative}")
        if not after.endswith(b"\n") or (before is not None and not before.endswith(b"\n")):
            raise ValueError(f"Source must end with a newline: {relative}")
        patches.append(f"diff --git a/{relative} b/{relative}\n")
        if before is None:
            patches.append("new file mode 100644\n")
        patches.extend(difflib.unified_diff(
            (before or b"").decode("utf-8").splitlines(keepends=True),
            after.decode("utf-8").splitlines(keepends=True),
            fromfile=f"a/{relative}" if before is not None else "/dev/null",
            tofile=f"b/{relative}",
        ))
        entries.append({"path": relative, "before": digest(before) if before is not None else None,
                        "after": digest(after)})
    patch = "".join(patches).encode("utf-8")
    manifest = {"schema": 1, "version": "1.0.3", "base_commit": base,
                "patch_sha256": digest(patch), "files": entries}
    members = {
        "backend.patch": patch,
        "manifest.json": (json.dumps(manifest, indent=2) + "\n").encode("utf-8"),
        "backend_tool.py": Path(__file__).read_bytes(),
    }
    # Exclusive creation prevents accidentally replacing an already reviewed bundle.
    with tarfile.open(output, "x:gz") as archive:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(content))
    return manifest


def verify_bundle(root, bundle, state):
    root = root.resolve(strict=True)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    entries = manifest.get("files", [])
    if (manifest.get("schema") != 1 or len(entries) != len(SOURCES)
            or [entry.get("path") for entry in entries] != list(SOURCES)):
        raise ValueError("Manifest must contain exactly the five approved source paths")
    patch = (bundle / "backend.patch").read_bytes()
    if digest(patch) != manifest.get("patch_sha256"):
        raise ValueError("Patch checksum mismatch")
    headers = [line for line in patch.decode("utf-8").splitlines() if line.startswith("diff --git ")]
    if headers != [f"diff --git a/{path} b/{path}" for path in SOURCES]:
        raise ValueError("Patch paths differ from the approved source paths")
    for entry in entries:
        relative = entry["path"]
        for stage in ("before", "after"):
            value = entry.get(stage)
            if stage == "before" and relative in ADDED and value is None:
                continue
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError(f"Invalid manifest checksum: {relative}")
        data = source_bytes(root, relative)
        expected = entry[state]
        if (data is None) != (expected is None) or (data is not None and digest(data) != expected):
            raise ValueError(f"Source does not match {state} state; stop without overwriting: {relative}")
        if data is not None:
            syntax_check(data, relative)
    return len(entries)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    build.add_argument("--base-ref", default=BASE_COMMIT)
    build.add_argument("--output", required=True, type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("--root", required=True, type=Path)
    verify.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parent)
    verify.add_argument("--state", choices=("before", "after"), required=True)
    args = parser.parse_args()
    try:
        if args.command == "build":
            create_bundle(args.root, args.output, args.base_ref)
            print(f"Bundle: {args.output.resolve()}")
            print(f"SHA256: {digest(args.output.read_bytes())}")
        else:
            count = verify_bundle(args.root, args.bundle, args.state)
            print(f"PASS: {count} approved source files match {args.state}; Python syntax valid")
    except (ValueError, OSError) as error:
        parser.exit(1, f"STOP: {error}\n")


if __name__ == "__main__":
    main()

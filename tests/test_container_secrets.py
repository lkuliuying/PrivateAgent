"""Secret generation is bounded, non-overwriting, and privacy-safe."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from generate_container_secrets import (  # noqa: E402
    ContainerSecretError,
    SECRET_FILENAMES,
    generate_secret_files,
)


def test_generate_container_secrets_creates_distinct_bounded_values(tmp_path):
    output = tmp_path / "project" / ".secrets"
    project = tmp_path / "project"
    project.mkdir()

    paths = generate_secret_files(output, project_root=project)

    assert tuple(path.name for path in paths) == SECRET_FILENAMES
    values = [path.read_text(encoding="utf-8") for path in paths]
    assert all(len(value) == 64 for value in values)
    assert len(set(values)) == len(values)


def test_generate_container_secrets_refuses_overwrite(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    output = project / ".secrets"
    generate_secret_files(output, project_root=project)

    with pytest.raises(ContainerSecretError, match="refusing to overwrite"):
        generate_secret_files(output, project_root=project)


def test_generate_container_secrets_rejects_path_outside_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(ContainerSecretError, match="child of the project root"):
        generate_secret_files(tmp_path / "outside", project_root=project)

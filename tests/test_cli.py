from __future__ import annotations

import json
from pathlib import Path

from orbitfabric.adapter_manager.inventory import InstalledAdapterInventory
from orbitfabric.adapter_manager.models import InstalledAdapterRecord
from typer.testing import CliRunner

from orbitfabric_github_release_source import GitHubReleaseSource, cli
from orbitfabric_github_release_source.cli import app

from ._support import _happy_case

SOURCE_COORDINATE = "github.com/FAROTECH:orbitfabric/fprime"


def _write_catalog(tmp_path: Path, selection) -> Path:
    source = selection.sources[0]
    payload = {
        "kind": "orbitfabric.adapter_catalog",
        "catalog_version": "0.1-candidate",
        "adapters": [
            {
                "source_coordinate": selection.source_coordinate.model_dump(mode="json"),
                "releases": [
                    {
                        "version": selection.release_version,
                        "release_descriptor_digest": (
                            selection.release_descriptor_digest.model_dump(mode="json")
                        ),
                        "sources": [
                            {
                                "binding": source.binding.id,
                                "release_ref": source.release_ref,
                            }
                        ],
                    }
                ],
            }
        ],
        "source_bindings": [source.binding.model_dump(mode="json")],
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_lock(tmp_path: Path, selection, descriptor_bytes: bytes) -> Path:
    descriptor = json.loads(descriptor_bytes)
    artifact = descriptor["artifacts"][0]
    payload = {
        "kind": "orbitfabric.adapter_project_lock",
        "lock_version": "0.1-candidate",
        "adapters": [
            {
                "source_coordinate": selection.source_coordinate.model_dump(mode="json"),
                "release_version": selection.release_version,
                "release_descriptor": {
                    "sha256": selection.release_descriptor_digest.value,
                },
                "artifact": {
                    "id": artifact["id"],
                    "sha256": artifact["sha256"],
                },
                "installation_backend": {
                    "id": "python-wheel-managed-env",
                },
            }
        ],
    }
    path = tmp_path / "adapter-lock.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _matching_record(tmp_path: Path, selection, descriptor_bytes: bytes) -> InstalledAdapterRecord:
    descriptor = json.loads(descriptor_bytes)
    artifact = descriptor["artifacts"][0]
    root = tmp_path / "installed"
    return InstalledAdapterRecord(
        instance_id="exact",
        source_coordinate=selection.source_coordinate,
        release_version=selection.release_version,
        release_descriptor_path=root / "release_descriptor.json",
        release_descriptor_sha256=selection.release_descriptor_digest.value,
        artifact_id=artifact["id"],
        artifact_sha256=artifact["sha256"],
        backend_id="python-wheel-managed-env",
        install_root=root,
        manifest_path=root / "integration_package.json",
        manifest_sha256="1" * 64,
        execution_argv_prefix=[str(root / "adapter")],
        acceptance_policy="fixture",
        acceptance_warnings=[],
    )


def test_cli_help_exposes_resolve_and_ensure() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "resolve" in result.stdout
    assert "ensure" in result.stdout


def test_resolve_cli_materializes_exact_release(tmp_path: Path, monkeypatch) -> None:
    selection, client, _, _ = _happy_case()
    catalog = _write_catalog(tmp_path, selection)
    output = tmp_path / "resolved"
    monkeypatch.setattr(cli, "_source", lambda: GitHubReleaseSource(client=client))

    result = CliRunner().invoke(
        app,
        [
            "resolve",
            str(catalog),
            SOURCE_COORDINATE,
            "--version",
            "0.1.1",
            "--output-dir",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert f"Resolved: {SOURCE_COORDINATE}@0.1.1" in result.stdout
    assert "Provider repository: FAROTECH/orbitfabric-fprime-adapter" in result.stdout
    assert "release_descriptor_integrity=PASS" in result.stdout
    assert (output / "adapter-release.json").is_file()
    assert (output / "adapter-0.1.1-py3-none-any.whl").is_file()
    assert client.release_calls == [("FAROTECH/orbitfabric-fprime-adapter", "v0.1.1")]
    assert len(client.download_calls) == 2


def test_resolve_cli_unknown_version_fails_before_provider(tmp_path: Path, monkeypatch) -> None:
    selection, _, _, _ = _happy_case()
    catalog = _write_catalog(tmp_path, selection)

    def unexpected_source():
        raise AssertionError("provider source must not be created")

    monkeypatch.setattr(cli, "_source", unexpected_source)
    result = CliRunner().invoke(
        app,
        [
            "resolve",
            str(catalog),
            SOURCE_COORDINATE,
            "--version",
            "9.9.9",
            "--output-dir",
            str(tmp_path / "resolved"),
        ],
    )

    assert result.exit_code == 1
    assert "Expected one exact Catalog release" in result.stderr


def test_ensure_match_is_noop_without_catalog_or_provider(tmp_path: Path, monkeypatch) -> None:
    selection, _, descriptor_bytes, _ = _happy_case()
    lock = _write_lock(tmp_path, selection, descriptor_bytes)
    state_root = tmp_path / "state"
    InstalledAdapterInventory(state_root).add(
        _matching_record(tmp_path, selection, descriptor_bytes)
    )

    def unexpected_source():
        raise AssertionError("provider source must not be created for MATCH")

    monkeypatch.setattr(cli, "_source", unexpected_source)
    missing_catalog = tmp_path / "catalog-does-not-exist.json"
    result = CliRunner().invoke(
        app,
        ["ensure", str(missing_catalog), str(lock), SOURCE_COORDINATE],
        env={"ORBITFABRIC_STATE_DIR": str(state_root)},
    )

    assert result.exit_code == 0
    assert "Before: MATCH" in result.stdout
    assert "Action: NOOP" in result.stdout
    assert "After: MATCH" in result.stdout
    assert "Remote resolution: skipped" in result.stdout
    assert not missing_catalog.exists()


def test_ensure_catalog_digest_mismatch_fails_before_provider(tmp_path: Path, monkeypatch) -> None:
    selection, _, descriptor_bytes, _ = _happy_case()
    catalog = _write_catalog(tmp_path, selection)
    lock = _write_lock(tmp_path, selection, descriptor_bytes)
    lock_payload = json.loads(lock.read_text(encoding="utf-8"))
    lock_payload["adapters"][0]["release_descriptor"]["sha256"] = "0" * 64
    lock.write_text(json.dumps(lock_payload, indent=2) + "\n", encoding="utf-8")

    def unexpected_source():
        raise AssertionError("provider source must not be created before digest agreement")

    monkeypatch.setattr(cli, "_source", unexpected_source)
    result = CliRunner().invoke(
        app,
        ["ensure", str(catalog), str(lock), SOURCE_COORDINATE],
        env={"ORBITFABRIC_STATE_DIR": str(tmp_path / "empty-state")},
    )

    assert result.exit_code == 1
    assert "Catalog selection Release Descriptor digest does not match" in result.stderr


def test_ensure_missing_lock_coordinate_fails_before_provider(tmp_path: Path, monkeypatch) -> None:
    selection, _, descriptor_bytes, _ = _happy_case()
    catalog = _write_catalog(tmp_path, selection)
    lock = _write_lock(tmp_path, selection, descriptor_bytes)

    def unexpected_source():
        raise AssertionError("provider source must not be created")

    monkeypatch.setattr(cli, "_source", unexpected_source)
    result = CliRunner().invoke(
        app,
        [
            "ensure",
            str(catalog),
            str(lock),
            "github.com/FAROTECH:orbitfabric/missing",
        ],
        env={"ORBITFABRIC_STATE_DIR": str(tmp_path / "empty-state")},
    )

    assert result.exit_code == 1
    assert "does not contain exactly one requested Source Coordinate" in result.stderr

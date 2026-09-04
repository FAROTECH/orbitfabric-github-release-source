from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Annotated

import typer
from orbitfabric.adapter_manager import (
    AdapterCatalog,
    AdapterManager,
    AdapterManagerError,
    ProjectLockInstallService,
    ProjectLockService,
    select_exact_release,
)
from orbitfabric.adapter_manager.models import AdapterSourceCoordinate

from .errors import GitHubReleaseSourceError
from .source import GitHubReleaseSource

app = typer.Typer(
    name="orbitfabric-github-release-source",
    help="Resolve and ensure exact OrbitFabric adapter releases through GitHub Releases.",
    no_args_is_help=True,
)


def _fail(exc: Exception) -> None:
    typer.echo(f"GitHub Release Source error: {exc}", err=True)
    raise typer.Exit(code=1) from exc


def _load_catalog(path: Path) -> AdapterCatalog:
    try:
        return AdapterCatalog.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Invalid or unavailable Adapter Catalog {path}: {exc}") from exc


def _parse_source_coordinate(value: str) -> AdapterSourceCoordinate:
    authority, authority_separator, logical = value.partition(":")
    publisher, publisher_separator, name = logical.partition("/")
    if (
        not authority_separator
        or not publisher_separator
        or not authority.strip()
        or not publisher.strip()
        or not name.strip()
    ):
        raise ValueError("Source Coordinate must use AUTHORITY:PUBLISHER/NAME syntax")
    return AdapterSourceCoordinate(
        authority=authority.strip(),
        publisher=publisher.strip(),
        name=name.strip(),
    )


def _source() -> GitHubReleaseSource:
    return GitHubReleaseSource(token=os.environ.get("GITHUB_TOKEN"))


def _find_lock_entry(lock, coordinate: AdapterSourceCoordinate):
    matches = [entry for entry in lock.adapters if entry.source_coordinate == coordinate]
    if len(matches) != 1:
        raise ValueError(
            "Adapter Project Lock does not contain exactly one requested Source Coordinate: "
            f"{coordinate.display()}"
        )
    return matches[0]


def _find_lock_state(report, coordinate: AdapterSourceCoordinate):
    matches = [item for item in report.adapters if item.source_coordinate == coordinate]
    if len(matches) != 1:
        raise ValueError(
            "Project Lock state does not contain exactly one requested Source Coordinate: "
            f"{coordinate.display()}"
        )
    return matches[0]


@app.command("resolve")
def resolve_release(
    catalog_path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Local Adapter Catalog JSON file.",
        ),
    ],
    source_coordinate: Annotated[
        str,
        typer.Argument(help="Exact Source Coordinate as AUTHORITY:PUBLISHER/NAME."),
    ],
    release_version: Annotated[
        str,
        typer.Option("--version", help="Exact release version string."),
    ],
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            help="Empty or absent directory for verified release materialization.",
        ),
    ],
    artifact_id: Annotated[
        str | None,
        typer.Option(
            "--artifact-id",
            help="Exact descriptor-owned artifact id when a release has multiple artifacts.",
        ),
    ] = None,
) -> None:
    """Resolve one exact Catalog-selected release through GitHub Releases."""
    try:
        catalog = _load_catalog(catalog_path)
        coordinate = _parse_source_coordinate(source_coordinate)
        selection = select_exact_release(catalog, coordinate, release_version)
        resolution = _source().resolve(
            selection,
            output_dir,
            artifact_id=artifact_id,
        )
    except (AdapterManagerError, GitHubReleaseSourceError, ValueError) as exc:
        _fail(exc)
        return

    release = resolution.resolved_release
    facts = resolution.provider_facts
    typer.echo(
        f"Resolved: {release.descriptor.source_coordinate.display()}"
        f"@{release.descriptor.release_version}"
    )
    typer.echo(
        "Release Descriptor: "
        f"{release.descriptor_path} sha256:{release.descriptor_sha256}"
    )
    typer.echo(
        "Artifact: "
        f"{release.artifact.id} {release.artifact_path} sha256:{release.artifact.sha256}"
    )
    typer.echo(f"Provider repository: {facts.repository}")
    typer.echo(f"Provider release ref: {facts.release_ref}")
    typer.echo(f"Provider immutable: {facts.immutable}")
    typer.echo("Trust evidence:")
    typer.echo(
        "  release_descriptor_integrity="
        f"{release.trust_evidence.release_descriptor_integrity}"
    )
    typer.echo(f"  artifact_integrity={release.trust_evidence.artifact_integrity}")
    typer.echo(
        "  closed_release_immutability="
        f"{release.trust_evidence.closed_release_immutability}"
    )


@app.command("ensure")
def ensure_project_lock_entry(
    catalog_path: Annotated[
        Path,
        typer.Argument(
            help=(
                "Local Adapter Catalog JSON file. It is read only when the requested "
                "Project Lock entry is not already MATCH."
            ),
        ),
    ],
    lock_path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Adapter Project Lock JSON file that owns the exact desired release.",
        ),
    ],
    source_coordinate: Annotated[
        str,
        typer.Argument(help="Exact lock entry as AUTHORITY:PUBLISHER/NAME."),
    ],
) -> None:
    """Ensure one exact Project Lock entry using the GitHub Release Source when needed."""
    try:
        coordinate = _parse_source_coordinate(source_coordinate)
        manager = AdapterManager()
        locks = ProjectLockService()
        lock = locks.load(lock_path)
        entry = _find_lock_entry(lock, coordinate)
        before_report = locks.check(lock_path, manager.list())
        before = _find_lock_state(before_report, coordinate)

        if before.status == "MATCH":
            typer.echo(f"Adapter Project Lock: {lock_path}")
            typer.echo(f"Adapter: {coordinate.display()}@{entry.release_version}")
            typer.echo("Before: MATCH")
            typer.echo("Action: NOOP")
            typer.echo("After: MATCH")
            typer.echo("Remote resolution: skipped")
            return

        catalog = _load_catalog(catalog_path)
        selection = select_exact_release(
            catalog,
            coordinate,
            entry.release_version,
        )
        if selection.release_descriptor_digest.value != entry.release_descriptor.sha256:
            raise ValueError(
                "Catalog selection Release Descriptor digest does not match Project Lock"
            )

        with tempfile.TemporaryDirectory(prefix="orbitfabric-github-release-source-") as temp:
            resolution = _source().resolve(
                selection,
                Path(temp),
                artifact_id=entry.artifact.id,
            )
            result = ProjectLockInstallService(manager).install_resolved_entry(
                lock_path,
                coordinate,
                resolution.resolved_release,
            )

    except (AdapterManagerError, GitHubReleaseSourceError, ValueError) as exc:
        _fail(exc)
        return

    typer.echo(f"Adapter Project Lock: {lock_path}")
    typer.echo(f"Adapter: {coordinate.display()}@{entry.release_version}")
    typer.echo(f"Before: {result.before_status}")
    typer.echo(f"Action: {result.action}")
    if result.installed_instance_id:
        typer.echo(f"Installed instance: {result.installed_instance_id}")
    typer.echo(f"After: {result.after_status}")
    typer.echo("Acquisition workspace: removed")


__all__ = ["app"]

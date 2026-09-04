from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from orbitfabric.adapter_manager import (
    CatalogDigest,
    CatalogSourceBinding,
    ExactCatalogReleaseSelection,
    ExactCatalogReleaseSource,
)
from orbitfabric.adapter_manager.models import AdapterSourceCoordinate

from orbitfabric_github_release_source import (
    GitHubApiClient,
    GitHubReleaseSource,
    GitHubReleaseSourceError,
)

__all__ = [
    "AdapterSourceCoordinate",
    "Any",
    "CatalogDigest",
    "CatalogSourceBinding",
    "ExactCatalogReleaseSource",
    "FakeClient",
    "GitHubApiClient",
    "GitHubReleaseSource",
    "GitHubReleaseSourceError",
    "Path",
    "_artifact_payload",
    "_descriptor_bytes",
    "_happy_case",
    "_provider_asset",
    "_selection",
    "_sha256",
    "deepcopy",
    "pytest",
]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeClient:
    def __init__(
        self,
        release: dict[str, Any],
        downloads: dict[str, bytes],
    ) -> None:
        self.release = release
        self.downloads = downloads
        self.release_calls: list[tuple[str, str]] = []
        self.download_calls: list[str] = []

    def release_by_ref(self, repository: str, release_ref: str) -> dict[str, Any]:
        self.release_calls.append((repository, release_ref))
        return deepcopy(self.release)

    def download(self, url: str) -> bytes:
        self.download_calls.append(url)
        try:
            return self.downloads[url]
        except KeyError as exc:
            raise AssertionError(f"unexpected download URL: {url}") from exc


def _artifact_payload(
    *,
    artifact_id: str = "python-wheel",
    filename: str = "adapter-0.1.1-py3-none-any.whl",
    data: bytes = b"wheel-bytes",
    size: int | None = None,
    sha256: str | None = None,
) -> dict[str, Any]:
    return {
        "id": artifact_id,
        "artifact_type": "python-wheel",
        "filename": filename,
        "sha256": sha256 or _sha256(data),
        "size": len(data) if size is None else size,
        "selectors": {},
    }


def _descriptor_bytes(
    *,
    source_coordinate: dict[str, str] | None = None,
    release_version: str = "0.1.1",
    artifacts: list[dict[str, Any]] | None = None,
) -> bytes:
    payload = {
        "kind": "orbitfabric.adapter_release",
        "descriptor_version": "0.1-candidate",
        "source_coordinate": source_coordinate
        or {
            "authority": "github.com/FAROTECH",
            "publisher": "orbitfabric",
            "name": "fprime",
        },
        "release_version": release_version,
        "source_provenance": {"provider": "github-release"},
        "artifacts": artifacts or [_artifact_payload()],
        "integration_package": {"sha256": "1" * 64},
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _selection(
    descriptor_bytes: bytes,
    *,
    sources: list[ExactCatalogReleaseSource] | None = None,
    source_coordinate: AdapterSourceCoordinate | None = None,
    release_version: str = "0.1.1",
    descriptor_digest: str | None = None,
) -> ExactCatalogReleaseSelection:
    return ExactCatalogReleaseSelection(
        source_coordinate=source_coordinate
        or AdapterSourceCoordinate(
            authority="github.com/FAROTECH",
            publisher="orbitfabric",
            name="fprime",
        ),
        release_version=release_version,
        release_descriptor_digest=CatalogDigest(
            algorithm="sha256",
            value=descriptor_digest or _sha256(descriptor_bytes),
        ),
        sources=sources
        or [
            ExactCatalogReleaseSource(
                binding=CatalogSourceBinding(
                    id="github-fprime",
                    provider="github-release",
                    config={"repository": "FAROTECH/orbitfabric-fprime-adapter"},
                ),
                release_ref="v0.1.1",
            )
        ],
    )


def _provider_asset(
    name: str,
    url: str,
    *,
    digest: str | None,
    uploader: str | None = "github-actions[bot]",
) -> dict[str, Any]:
    asset: dict[str, Any] = {
        "name": name,
        "browser_download_url": url,
    }
    if digest is not None:
        asset["digest"] = digest
    if uploader is not None:
        asset["uploader"] = {"login": uploader}
    return asset


def _happy_case(
    *,
    immutable: bool | None = True,
    author_login: str | None = "github-actions[bot]",
    descriptor_provider_digest: str | None = None,
    artifact_provider_digest: str | None = None,
    descriptor_bytes: bytes | None = None,
    artifact_bytes: bytes = b"wheel-bytes",
) -> tuple[ExactCatalogReleaseSelection, FakeClient, bytes, bytes]:
    descriptor_bytes = descriptor_bytes or _descriptor_bytes(
        artifacts=[_artifact_payload(data=artifact_bytes)]
    )
    descriptor_url = "https://example.invalid/adapter-release.json"
    artifact_url = "https://example.invalid/adapter.whl"
    descriptor_provider_digest = (
        descriptor_provider_digest
        if descriptor_provider_digest is not None
        else f"sha256:{_sha256(descriptor_bytes)}"
    )
    artifact_provider_digest = (
        artifact_provider_digest
        if artifact_provider_digest is not None
        else f"sha256:{_sha256(artifact_bytes)}"
    )
    release: dict[str, Any] = {
        "id": 12345,
        "tag_name": "v0.1.1",
        "draft": False,
        "prerelease": False,
        "assets": [
            _provider_asset(
                "adapter-release.json",
                descriptor_url,
                digest=descriptor_provider_digest,
            ),
            _provider_asset(
                "adapter-0.1.1-py3-none-any.whl",
                artifact_url,
                digest=artifact_provider_digest,
            ),
        ],
    }
    if immutable is not None:
        release["immutable"] = immutable
    if author_login is not None:
        release["author"] = {"login": author_login}
    client = FakeClient(
        release,
        {
            descriptor_url: descriptor_bytes,
            artifact_url: artifact_bytes,
        },
    )
    return _selection(descriptor_bytes), client, descriptor_bytes, artifact_bytes

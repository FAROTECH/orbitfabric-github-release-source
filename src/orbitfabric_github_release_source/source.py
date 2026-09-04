from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Protocol

from orbitfabric.adapter_manager import ExactCatalogReleaseSelection
from orbitfabric.adapter_manager.models import (
    AdapterReleaseDescriptor,
    ReleaseArtifact,
    ReleaseTrustEvidence,
    ResolvedAdapterRelease,
)

from .errors import GitHubReleaseSourceError
from .models import GitHubReleaseFacts, GitHubReleaseResolution

_GITHUB_PROVIDER = "github-release"
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA256_PROVIDER_DIGEST_RE = re.compile(r"^sha256:([0-9a-fA-F]{64})$")


class _GitHubClient(Protocol):
    def release_by_ref(self, repository: str, release_ref: str) -> dict[str, Any]: ...

    def download(self, url: str) -> bytes: ...


class GitHubApiClient:
    """Minimal GitHub REST client used by the provider-specific source product."""

    def __init__(
        self,
        *,
        token: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._token = token
        self._timeout_seconds = timeout_seconds

    def release_by_ref(self, repository: str, release_ref: str) -> dict[str, Any]:
        owner, name = repository.split("/", maxsplit=1)
        owner_q = urllib.parse.quote(owner, safe="")
        name_q = urllib.parse.quote(name, safe="")
        ref_q = urllib.parse.quote(release_ref, safe="")
        url = (
            f"https://api.github.com/repos/{owner_q}/{name_q}/releases/tags/{ref_q}"
        )
        payload = self._request(url, api=True)
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise GitHubReleaseSourceError("GitHub release response is not valid JSON") from exc
        if not isinstance(decoded, dict):
            raise GitHubReleaseSourceError("GitHub release response must be a JSON object")
        return decoded

    def download(self, url: str) -> bytes:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https":
            raise GitHubReleaseSourceError("GitHub asset download URL must use https")
        return self._request(url, api=False)

    def _request(self, url: str, *, api: bool) -> bytes:
        headers = {"User-Agent": "orbitfabric-github-release-source/0.1"}
        if api:
            headers["Accept"] = "application/vnd.github+json"
            headers["X-GitHub-Api-Version"] = "2022-11-28"
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                return response.read()
        except Exception as exc:
            raise GitHubReleaseSourceError(f"GitHub request failed for {url}") from exc


class GitHubReleaseSource:
    """Acquire one exact Catalog-selected adapter release from GitHub Releases."""

    def __init__(
        self,
        *,
        token: str | None = None,
        timeout_seconds: float = 60.0,
        client: _GitHubClient | None = None,
    ) -> None:
        if client is not None and token is not None:
            raise ValueError("token and client are mutually exclusive")
        self._client = client or GitHubApiClient(
            token=token,
            timeout_seconds=timeout_seconds,
        )

    def resolve(
        self,
        selection: ExactCatalogReleaseSelection,
        materialization_root: Path,
        *,
        artifact_id: str | None = None,
    ) -> GitHubReleaseResolution:
        self._validate_materialization_root(materialization_root)
        selected_source = self._select_github_source(selection)
        repository = self._repository_from_config(selected_source.binding.config)

        provider_release = self._client.release_by_ref(
            repository,
            selected_source.release_ref,
        )
        if provider_release.get("draft") is True:
            raise GitHubReleaseSourceError("GitHub release is draft")
        if provider_release.get("prerelease") is True:
            raise GitHubReleaseSourceError("GitHub release is prerelease")

        descriptor_asset = self._unique_asset(provider_release, "adapter-release.json")
        descriptor_bytes = self._download_asset(descriptor_asset)
        descriptor_sha256 = self._sha256(descriptor_bytes)
        if selection.release_descriptor_digest.algorithm != "sha256":
            raise GitHubReleaseSourceError("Unsupported Catalog descriptor digest algorithm")
        if descriptor_sha256 != selection.release_descriptor_digest.value:
            raise GitHubReleaseSourceError(
                "Downloaded Release Descriptor digest does not match Catalog selection"
            )

        try:
            descriptor = AdapterReleaseDescriptor.model_validate_json(descriptor_bytes)
        except Exception as exc:
            raise GitHubReleaseSourceError("Release Descriptor is invalid") from exc

        if descriptor.source_coordinate != selection.source_coordinate:
            raise GitHubReleaseSourceError(
                "Release Descriptor Source Coordinate does not match Catalog selection"
            )
        if descriptor.release_version != selection.release_version:
            raise GitHubReleaseSourceError(
                "Release Descriptor version does not match Catalog selection"
            )

        artifact = self._select_artifact(descriptor, artifact_id)
        if artifact.filename is None:
            raise GitHubReleaseSourceError("Selected artifact has no provider filename")
        self._validate_asset_filename(artifact.filename)

        artifact_asset = self._unique_asset(provider_release, artifact.filename)
        artifact_bytes = self._download_asset(artifact_asset)
        if artifact.size is not None and len(artifact_bytes) != artifact.size:
            raise GitHubReleaseSourceError(
                "Downloaded artifact size does not match Release Descriptor"
            )
        artifact_sha256 = self._sha256(artifact_bytes)
        if artifact_sha256 != artifact.sha256:
            raise GitHubReleaseSourceError(
                "Downloaded artifact digest does not match Release Descriptor"
            )

        descriptor_path, artifact_path = self._materialize(
            materialization_root,
            descriptor_bytes=descriptor_bytes,
            artifact_filename=artifact.filename,
            artifact_bytes=artifact_bytes,
        )

        trust_evidence = ReleaseTrustEvidence(
            release_descriptor_integrity="PASS",
            artifact_integrity="PASS",
            closed_release_immutability=(
                "PASS" if provider_release.get("immutable") is True else "UNKNOWN"
            ),
            operational_state="unknown",
        )
        resolved = ResolvedAdapterRelease(
            descriptor=descriptor,
            descriptor_path=descriptor_path,
            descriptor_sha256=descriptor_sha256,
            artifact=artifact,
            artifact_path=artifact_path,
            trust_evidence=trust_evidence,
        )

        facts = GitHubReleaseFacts(
            repository=repository,
            release_ref=selected_source.release_ref,
            release_id=self._optional_int(provider_release.get("id")),
            tag_name=self._optional_str(provider_release.get("tag_name")),
            immutable=self._optional_bool(provider_release.get("immutable")),
            author_login=self._nested_login(provider_release.get("author")),
            descriptor_asset_uploader_login=self._nested_login(
                descriptor_asset.get("uploader")
            ),
            descriptor_provider_digest=self._optional_str(
                descriptor_asset.get("digest")
            ),
            descriptor_provider_digest_matches_downloaded=(
                self._provider_digest_match(
                    descriptor_asset.get("digest"), descriptor_sha256
                )
            ),
            artifact_asset_uploader_login=self._nested_login(
                artifact_asset.get("uploader")
            ),
            artifact_provider_digest=self._optional_str(artifact_asset.get("digest")),
            artifact_provider_digest_matches_downloaded=(
                self._provider_digest_match(artifact_asset.get("digest"), artifact_sha256)
            ),
        )
        return GitHubReleaseResolution(
            resolved_release=resolved,
            provider_facts=facts,
        )

    @staticmethod
    def _select_github_source(selection: ExactCatalogReleaseSelection):
        matches = [
            source
            for source in selection.sources
            if source.binding.provider == _GITHUB_PROVIDER
        ]
        if len(matches) != 1:
            raise GitHubReleaseSourceError(
                "Expected exactly one github-release source in Catalog selection, "
                f"found {len(matches)}"
            )
        return matches[0]

    @staticmethod
    def _repository_from_config(config: dict[str, Any]) -> str:
        if set(config) != {"repository"}:
            raise GitHubReleaseSourceError(
                "github-release binding config must contain only 'repository'"
            )
        repository = config.get("repository")
        if not isinstance(repository, str) or not _REPOSITORY_RE.fullmatch(repository):
            raise GitHubReleaseSourceError(
                "github-release repository must use exact owner/name form"
            )
        return repository

    @staticmethod
    def _unique_asset(release: dict[str, Any], filename: str) -> dict[str, Any]:
        assets = release.get("assets", [])
        if not isinstance(assets, list):
            raise GitHubReleaseSourceError("GitHub release assets must be a list")
        matches = [
            asset
            for asset in assets
            if isinstance(asset, dict) and asset.get("name") == filename
        ]
        if len(matches) != 1:
            raise GitHubReleaseSourceError(
                f"Expected exactly one GitHub release asset {filename!r}, "
                f"found {len(matches)}"
            )
        return matches[0]

    def _download_asset(self, asset: dict[str, Any]) -> bytes:
        url = asset.get("browser_download_url")
        if not isinstance(url, str) or not url:
            raise GitHubReleaseSourceError("GitHub release asset has no download URL")
        return self._client.download(url)

    @staticmethod
    def _select_artifact(
        descriptor: AdapterReleaseDescriptor,
        artifact_id: str | None,
    ) -> ReleaseArtifact:
        if artifact_id is None:
            if len(descriptor.artifacts) != 1:
                raise GitHubReleaseSourceError(
                    "Artifact id is required when Release Descriptor has multiple artifacts"
                )
            return descriptor.artifacts[0]
        matches = [artifact for artifact in descriptor.artifacts if artifact.id == artifact_id]
        if len(matches) != 1:
            raise GitHubReleaseSourceError(
                f"Expected exactly one Release Descriptor artifact {artifact_id!r}, "
                f"found {len(matches)}"
            )
        return matches[0]

    @staticmethod
    def _validate_asset_filename(filename: str) -> None:
        path = Path(filename)
        if path.name != filename or filename in {".", ".."}:
            raise GitHubReleaseSourceError("Artifact filename must be a plain file name")

    @staticmethod
    def _validate_materialization_root(root: Path) -> None:
        if root.exists():
            if not root.is_dir():
                raise GitHubReleaseSourceError("Materialization root exists and is not a directory")
            if any(root.iterdir()):
                raise GitHubReleaseSourceError("Materialization root must be empty")

    @classmethod
    def _materialize(
        cls,
        root: Path,
        *,
        descriptor_bytes: bytes,
        artifact_filename: str,
        artifact_bytes: bytes,
    ) -> tuple[Path, Path]:
        created_root = False
        descriptor_path = root / "adapter-release.json"
        artifact_path = root / artifact_filename
        created_paths: list[Path] = []
        try:
            if not root.exists():
                root.mkdir(parents=True, exist_ok=False)
                created_root = True
            cls._atomic_write(descriptor_path, descriptor_bytes)
            created_paths.append(descriptor_path)
            cls._atomic_write(artifact_path, artifact_bytes)
            created_paths.append(artifact_path)
        except Exception as exc:
            for path in reversed(created_paths):
                path.unlink(missing_ok=True)
            if created_root:
                try:
                    root.rmdir()
                except OSError:
                    pass
            if isinstance(exc, GitHubReleaseSourceError):
                raise
            raise GitHubReleaseSourceError("Failed to materialize verified release bytes") from exc
        return descriptor_path, artifact_path

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
        try:
            temporary.write_bytes(data)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _provider_digest_match(raw: Any, downloaded_sha256: str) -> bool | None:
        if not isinstance(raw, str):
            return None
        match = _SHA256_PROVIDER_DIGEST_RE.fullmatch(raw)
        if match is None:
            return None
        return match.group(1).lower() == downloaded_sha256

    @staticmethod
    def _nested_login(value: Any) -> str | None:
        if not isinstance(value, dict):
            return None
        login = value.get("login")
        return login if isinstance(login, str) and login else None

    @staticmethod
    def _optional_str(value: Any) -> str | None:
        return value if isinstance(value, str) else None

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @staticmethod
    def _optional_bool(value: Any) -> bool | None:
        return value if isinstance(value, bool) else None

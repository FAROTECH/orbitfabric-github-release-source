from __future__ import annotations

from dataclasses import dataclass

from orbitfabric.adapter_manager.models import ResolvedAdapterRelease


@dataclass(frozen=True)
class GitHubReleaseFacts:
    repository: str
    release_ref: str
    release_id: int | None
    tag_name: str | None
    immutable: bool | None
    author_login: str | None
    descriptor_asset_uploader_login: str | None
    descriptor_provider_digest: str | None
    descriptor_provider_digest_matches_downloaded: bool | None
    artifact_asset_uploader_login: str | None
    artifact_provider_digest: str | None
    artifact_provider_digest_matches_downloaded: bool | None


@dataclass(frozen=True)
class GitHubReleaseResolution:
    resolved_release: ResolvedAdapterRelease
    provider_facts: GitHubReleaseFacts

from __future__ import annotations

from ._support import (
    Any,
    CatalogDigest,
    CatalogSourceBinding,
    ExactCatalogReleaseSource,
    FakeClient,
    GitHubReleaseSource,
    GitHubReleaseSourceError,
    Path,
    _descriptor_bytes,
    _happy_case,
    _selection,
    _sha256,
    deepcopy,
    pytest,
)


def test_happy_path_materializes_exact_release_and_provider_facts(tmp_path: Path) -> None:
    selection, client, descriptor_bytes, artifact_bytes = _happy_case()
    root = tmp_path / "resolved"

    result = GitHubReleaseSource(client=client).resolve(selection, root)

    resolved = result.resolved_release
    assert resolved.descriptor.source_coordinate == selection.source_coordinate
    assert resolved.descriptor.release_version == "0.1.1"
    assert resolved.descriptor_sha256 == _sha256(descriptor_bytes)
    assert resolved.artifact.id == "python-wheel"
    assert resolved.artifact.sha256 == _sha256(artifact_bytes)
    assert resolved.descriptor_path.read_bytes() == descriptor_bytes
    assert resolved.artifact_path.read_bytes() == artifact_bytes
    assert client.release_calls == [
        ("FAROTECH/orbitfabric-fprime-adapter", "v0.1.1")
    ]
    assert len(client.download_calls) == 2

    facts = result.provider_facts
    assert facts.repository == "FAROTECH/orbitfabric-fprime-adapter"
    assert facts.release_ref == "v0.1.1"
    assert facts.release_id == 12345
    assert facts.tag_name == "v0.1.1"
    assert facts.immutable is True
    assert facts.author_login == "github-actions[bot]"
    assert facts.descriptor_asset_uploader_login == "github-actions[bot]"
    assert facts.artifact_asset_uploader_login == "github-actions[bot]"
    assert facts.descriptor_provider_digest_matches_downloaded is True
    assert facts.artifact_provider_digest_matches_downloaded is True


def test_resolution_populates_only_justified_trust_dimensions(tmp_path: Path) -> None:
    selection, client, _, _ = _happy_case(author_login="github-actions[bot]")

    evidence = GitHubReleaseSource(client=client).resolve(
        selection, tmp_path / "resolved"
    ).resolved_release.trust_evidence

    assert evidence.release_descriptor_integrity == "PASS"
    assert evidence.artifact_integrity == "PASS"
    assert evidence.closed_release_immutability == "PASS"
    assert evidence.source_authority_recognition == "UNKNOWN"
    assert evidence.publisher_namespace_binding == "UNKNOWN"
    assert evidence.publication_authentication == "UNKNOWN"
    assert evidence.source_build_provenance == "UNKNOWN"
    assert evidence.signature_attestation_verification == "UNKNOWN"
    assert evidence.orbitfabric_conformance == "UNKNOWN"
    assert evidence.policy_freshness == "UNKNOWN"
    assert evidence.operational_state == "unknown"


def test_provider_actor_never_redefines_orbitfabric_publisher_identity(tmp_path: Path) -> None:
    selection, client, _, _ = _happy_case(author_login="github-actions[bot]")

    result = GitHubReleaseSource(client=client).resolve(
        selection, tmp_path / "resolved"
    )

    assert result.provider_facts.author_login == "github-actions[bot]"
    assert result.resolved_release.descriptor.source_coordinate.publisher == "orbitfabric"
    assert result.resolved_release.trust_evidence.publisher_namespace_binding == "UNKNOWN"
    assert result.resolved_release.trust_evidence.publication_authentication == "UNKNOWN"


def test_provider_digest_mismatch_is_recorded_as_fact_not_identity_rewritten(
    tmp_path: Path,
) -> None:
    selection, client, descriptor_bytes, artifact_bytes = _happy_case(
        descriptor_provider_digest="sha256:" + "0" * 64,
        artifact_provider_digest="sha256:" + "f" * 64,
    )

    result = GitHubReleaseSource(client=client).resolve(
        selection, tmp_path / "resolved"
    )

    assert result.provider_facts.descriptor_provider_digest_matches_downloaded is False
    assert result.provider_facts.artifact_provider_digest_matches_downloaded is False
    assert result.resolved_release.descriptor_sha256 == _sha256(descriptor_bytes)
    assert result.resolved_release.artifact.sha256 == _sha256(artifact_bytes)
    assert result.resolved_release.trust_evidence.release_descriptor_integrity == "PASS"
    assert result.resolved_release.trust_evidence.artifact_integrity == "PASS"


@pytest.mark.parametrize("immutable", [False, None])
def test_nonaffirmative_provider_immutability_remains_unknown(
    tmp_path: Path,
    immutable: bool | None,
) -> None:
    selection, client, _, _ = _happy_case(immutable=immutable)

    evidence = GitHubReleaseSource(client=client).resolve(
        selection, tmp_path / "resolved"
    ).resolved_release.trust_evidence

    assert evidence.closed_release_immutability == "UNKNOWN"


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("draft", "GitHub release is draft"),
        ("prerelease", "GitHub release is prerelease"),
    ],
)
def test_draft_and_prerelease_fail_before_download_or_materialization(
    tmp_path: Path,
    field: str,
    message: str,
) -> None:
    selection, client, _, _ = _happy_case()
    client.release[field] = True
    root = tmp_path / "resolved"

    with pytest.raises(GitHubReleaseSourceError, match=message):
        GitHubReleaseSource(client=client).resolve(selection, root)

    assert client.download_calls == []
    assert not root.exists()


def test_zero_github_sources_fails_before_provider_lookup(tmp_path: Path) -> None:
    descriptor = _descriptor_bytes()
    selection = _selection(
        descriptor,
        sources=[
            ExactCatalogReleaseSource(
                binding=CatalogSourceBinding(
                    id="other", provider="other-provider", config={"x": "y"}
                ),
                release_ref="opaque",
            )
        ],
    )
    client = FakeClient({}, {})

    with pytest.raises(GitHubReleaseSourceError, match="found 0"):
        GitHubReleaseSource(client=client).resolve(selection, tmp_path / "resolved")

    assert client.release_calls == []


def test_multiple_github_sources_fail_without_inventing_provider_preference(
    tmp_path: Path,
) -> None:
    descriptor = _descriptor_bytes()
    selection = _selection(
        descriptor,
        sources=[
            ExactCatalogReleaseSource(
                binding=CatalogSourceBinding(
                    id="github-a",
                    provider="github-release",
                    config={"repository": "A/repo"},
                ),
                release_ref="r1",
            ),
            ExactCatalogReleaseSource(
                binding=CatalogSourceBinding(
                    id="github-b",
                    provider="github-release",
                    config={"repository": "B/repo"},
                ),
                release_ref="r2",
            ),
        ],
    )
    client = FakeClient({}, {})

    with pytest.raises(GitHubReleaseSourceError, match="found 2"):
        GitHubReleaseSource(client=client).resolve(selection, tmp_path / "resolved")

    assert client.release_calls == []


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"repository": "FAROTECH/repo", "extra": "not-allowed"},
        {"repository": "missing-slash"},
        {"repository": "owner/repo/extra"},
        {"repository": 123},
    ],
)
def test_github_binding_config_is_narrow_and_exact(
    tmp_path: Path,
    config: dict[str, Any],
) -> None:
    descriptor = _descriptor_bytes()
    selection = _selection(
        descriptor,
        sources=[
            ExactCatalogReleaseSource(
                binding=CatalogSourceBinding(
                    id="github", provider="github-release", config=config
                ),
                release_ref="v0.1.1",
            )
        ],
    )
    client = FakeClient({}, {})

    with pytest.raises(GitHubReleaseSourceError):
        GitHubReleaseSource(client=client).resolve(selection, tmp_path / "resolved")

    assert client.release_calls == []


def test_missing_descriptor_asset_fails_closed(tmp_path: Path) -> None:
    selection, client, _, _ = _happy_case()
    client.release["assets"] = [client.release["assets"][1]]

    with pytest.raises(GitHubReleaseSourceError, match="adapter-release.json.*found 0"):
        GitHubReleaseSource(client=client).resolve(selection, tmp_path / "resolved")

    assert not (tmp_path / "resolved").exists()


def test_duplicate_descriptor_asset_fails_closed(tmp_path: Path) -> None:
    selection, client, _, _ = _happy_case()
    client.release["assets"].append(deepcopy(client.release["assets"][0]))

    with pytest.raises(GitHubReleaseSourceError, match="adapter-release.json.*found 2"):
        GitHubReleaseSource(client=client).resolve(selection, tmp_path / "resolved")


def test_descriptor_digest_mismatch_fails_before_artifact_download(
    tmp_path: Path,
) -> None:
    selection, client, _, _ = _happy_case()
    selection = selection.model_copy(
        update={
            "release_descriptor_digest": CatalogDigest(
                algorithm="sha256", value="0" * 64
            )
        }
    )
    root = tmp_path / "resolved"

    with pytest.raises(GitHubReleaseSourceError, match="digest does not match Catalog"):
        GitHubReleaseSource(client=client).resolve(selection, root)

    assert len(client.download_calls) == 1
    assert not root.exists()

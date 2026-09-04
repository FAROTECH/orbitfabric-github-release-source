from __future__ import annotations

from ._support import (
    FakeClient,
    GitHubReleaseSource,
    GitHubReleaseSourceError,
    Path,
    _artifact_payload,
    _descriptor_bytes,
    _happy_case,
    _provider_asset,
    _selection,
    _sha256,
    deepcopy,
    pytest,
)


def test_invalid_descriptor_fails_closed(tmp_path: Path) -> None:
    bad_descriptor = b"not-json"
    selection, client, _, _ = _happy_case(descriptor_bytes=bad_descriptor)

    with pytest.raises(GitHubReleaseSourceError, match="Release Descriptor is invalid"):
        GitHubReleaseSource(client=client).resolve(selection, tmp_path / "resolved")


def test_descriptor_source_coordinate_mismatch_fails_closed(tmp_path: Path) -> None:
    descriptor = _descriptor_bytes(
        source_coordinate={
            "authority": "github.com/FAROTECH",
            "publisher": "orbitfabric",
            "name": "different",
        }
    )
    selection, client, _, _ = _happy_case(descriptor_bytes=descriptor)

    with pytest.raises(GitHubReleaseSourceError, match="Source Coordinate"):
        GitHubReleaseSource(client=client).resolve(selection, tmp_path / "resolved")


def test_descriptor_release_version_mismatch_fails_closed(tmp_path: Path) -> None:
    descriptor = _descriptor_bytes(release_version="9.9.9")
    selection, client, _, _ = _happy_case(descriptor_bytes=descriptor)

    with pytest.raises(GitHubReleaseSourceError, match="version does not match"):
        GitHubReleaseSource(client=client).resolve(selection, tmp_path / "resolved")


def test_multiple_descriptor_artifacts_require_exact_artifact_id(tmp_path: Path) -> None:
    first_data = b"first"
    second_data = b"second"
    descriptor = _descriptor_bytes(
        artifacts=[
            _artifact_payload(
                artifact_id="first", filename="first.whl", data=first_data
            ),
            _artifact_payload(
                artifact_id="second", filename="second.whl", data=second_data
            ),
        ]
    )
    descriptor_url = "https://example.invalid/descriptor"
    first_url = "https://example.invalid/first"
    second_url = "https://example.invalid/second"
    release = {
        "id": 1,
        "tag_name": "v0.1.1",
        "draft": False,
        "prerelease": False,
        "immutable": True,
        "assets": [
            _provider_asset(
                "adapter-release.json",
                descriptor_url,
                digest=f"sha256:{_sha256(descriptor)}",
            ),
            _provider_asset(
                "first.whl", first_url, digest=f"sha256:{_sha256(first_data)}"
            ),
            _provider_asset(
                "second.whl", second_url, digest=f"sha256:{_sha256(second_data)}"
            ),
        ],
    }
    selection = _selection(descriptor)
    client = FakeClient(
        release,
        {descriptor_url: descriptor, first_url: first_data, second_url: second_data},
    )
    source = GitHubReleaseSource(client=client)

    with pytest.raises(GitHubReleaseSourceError, match="Artifact id is required"):
        source.resolve(selection, tmp_path / "ambiguous")

    result = source.resolve(
        selection,
        tmp_path / "selected",
        artifact_id="second",
    )
    assert result.resolved_release.artifact.id == "second"
    assert result.resolved_release.artifact_path.name == "second.whl"
    assert result.resolved_release.artifact_path.read_bytes() == second_data


def test_unknown_exact_artifact_id_fails_closed(tmp_path: Path) -> None:
    descriptor = _descriptor_bytes()
    selection, client, _, _ = _happy_case(descriptor_bytes=descriptor)

    with pytest.raises(GitHubReleaseSourceError, match="artifact 'missing'.*found 0"):
        GitHubReleaseSource(client=client).resolve(
            selection, tmp_path / "resolved", artifact_id="missing"
        )


def test_missing_provider_artifact_fails_closed(tmp_path: Path) -> None:
    selection, client, _, _ = _happy_case()
    client.release["assets"] = [client.release["assets"][0]]

    with pytest.raises(GitHubReleaseSourceError, match="adapter-0.1.1.*found 0"):
        GitHubReleaseSource(client=client).resolve(selection, tmp_path / "resolved")


def test_duplicate_provider_artifact_fails_closed(tmp_path: Path) -> None:
    selection, client, _, _ = _happy_case()
    client.release["assets"].append(deepcopy(client.release["assets"][1]))

    with pytest.raises(GitHubReleaseSourceError, match="adapter-0.1.1.*found 2"):
        GitHubReleaseSource(client=client).resolve(selection, tmp_path / "resolved")


def test_artifact_size_mismatch_fails_without_materialization(tmp_path: Path) -> None:
    artifact_bytes = b"actual"
    descriptor = _descriptor_bytes(
        artifacts=[_artifact_payload(data=artifact_bytes, size=len(artifact_bytes) + 1)]
    )
    selection, client, _, _ = _happy_case(
        descriptor_bytes=descriptor, artifact_bytes=artifact_bytes
    )
    root = tmp_path / "resolved"

    with pytest.raises(GitHubReleaseSourceError, match="size does not match"):
        GitHubReleaseSource(client=client).resolve(selection, root)

    assert not root.exists()


def test_artifact_digest_mismatch_fails_without_materialization(tmp_path: Path) -> None:
    artifact_bytes = b"actual"
    descriptor = _descriptor_bytes(
        artifacts=[_artifact_payload(data=artifact_bytes, sha256="0" * 64)]
    )
    selection, client, _, _ = _happy_case(
        descriptor_bytes=descriptor, artifact_bytes=artifact_bytes
    )
    root = tmp_path / "resolved"

    with pytest.raises(GitHubReleaseSourceError, match="artifact digest does not match"):
        GitHubReleaseSource(client=client).resolve(selection, root)

    assert not root.exists()


def test_artifact_filename_path_traversal_is_rejected(tmp_path: Path) -> None:
    artifact_bytes = b"wheel"
    descriptor = _descriptor_bytes(
        artifacts=[
            _artifact_payload(filename="../escape.whl", data=artifact_bytes)
        ]
    )
    selection, client, _, _ = _happy_case(
        descriptor_bytes=descriptor, artifact_bytes=artifact_bytes
    )

    with pytest.raises(GitHubReleaseSourceError, match="plain file name"):
        GitHubReleaseSource(client=client).resolve(selection, tmp_path / "resolved")

    assert not (tmp_path / "escape.whl").exists()

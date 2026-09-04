from __future__ import annotations

from ._support import (
    FakeClient,
    GitHubApiClient,
    GitHubReleaseSource,
    GitHubReleaseSourceError,
    Path,
    _happy_case,
    pytest,
)


def test_nonempty_materialization_root_fails_before_network(tmp_path: Path) -> None:
    selection, client, _, _ = _happy_case()
    root = tmp_path / "resolved"
    root.mkdir()
    marker = root / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(GitHubReleaseSourceError, match="must be empty"):
        GitHubReleaseSource(client=client).resolve(selection, root)

    assert marker.read_text(encoding="utf-8") == "keep"
    assert client.release_calls == []


def test_materialization_failure_rolls_back_new_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selection, client, _, _ = _happy_case()
    source = GitHubReleaseSource(client=client)
    original = GitHubReleaseSource._atomic_write
    calls = 0

    def fail_second_write(path: Path, data: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic local failure")
        original(path, data)

    monkeypatch.setattr(GitHubReleaseSource, "_atomic_write", staticmethod(fail_second_write))
    root = tmp_path / "resolved"

    with pytest.raises(GitHubReleaseSourceError, match="Failed to materialize"):
        source.resolve(selection, root)

    assert not root.exists()


def test_materialization_failure_preserves_preexisting_empty_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selection, client, _, _ = _happy_case()
    source = GitHubReleaseSource(client=client)
    root = tmp_path / "resolved"
    root.mkdir()
    original = GitHubReleaseSource._atomic_write
    calls = 0

    def fail_second_write(path: Path, data: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic local failure")
        original(path, data)

    monkeypatch.setattr(GitHubReleaseSource, "_atomic_write", staticmethod(fail_second_write))

    with pytest.raises(GitHubReleaseSourceError, match="Failed to materialize"):
        source.resolve(selection, root)

    assert root.is_dir()
    assert list(root.iterdir()) == []


def test_provider_asset_digest_absence_or_unknown_format_remains_unknown_fact(
    tmp_path: Path,
) -> None:
    selection, client, _, _ = _happy_case(
        descriptor_provider_digest="not-a-sha256-digest",
        artifact_provider_digest="sha512:" + "a" * 128,
    )

    facts = GitHubReleaseSource(client=client).resolve(
        selection, tmp_path / "resolved"
    ).provider_facts

    assert facts.descriptor_provider_digest == "not-a-sha256-digest"
    assert facts.descriptor_provider_digest_matches_downloaded is None
    assert facts.artifact_provider_digest.startswith("sha512:")
    assert facts.artifact_provider_digest_matches_downloaded is None


def test_missing_asset_download_url_fails_closed(tmp_path: Path) -> None:
    selection, client, _, _ = _happy_case()
    client.release["assets"][0].pop("browser_download_url")

    with pytest.raises(GitHubReleaseSourceError, match="has no download URL"):
        GitHubReleaseSource(client=client).resolve(selection, tmp_path / "resolved")


def test_release_assets_must_be_list(tmp_path: Path) -> None:
    selection, client, _, _ = _happy_case()
    client.release["assets"] = "not-a-list"

    with pytest.raises(GitHubReleaseSourceError, match="assets must be a list"):
        GitHubReleaseSource(client=client).resolve(selection, tmp_path / "resolved")


def test_injected_client_and_token_are_mutually_exclusive() -> None:
    client = FakeClient({}, {})
    with pytest.raises(ValueError, match="mutually exclusive"):
        GitHubReleaseSource(token="secret", client=client)


@pytest.mark.parametrize("timeout", [0, -1, -0.5])
def test_api_client_requires_positive_timeout(timeout: float) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        GitHubApiClient(timeout_seconds=timeout)


def test_api_client_rejects_non_https_asset_url() -> None:
    client = GitHubApiClient()
    with pytest.raises(GitHubReleaseSourceError, match="must use https"):
        client.download("http://example.invalid/asset")

# OrbitFabric GitHub Release Source

Provider-specific GitHub Releases acquisition for exact OrbitFabric adapter releases.

This package consumes the provider-neutral exact Catalog selection owned by OrbitFabric Core, acquires the selected Release Descriptor and descriptor-owned artifact from GitHub Releases, verifies exact identity and bytes, and constructs the existing Core `ResolvedAdapterRelease` handoff.

```text
OrbitFabric Core Catalog selection
    -> GitHub Release source binding
    -> exact GitHub Release lookup
    -> verify adapter-release.json against Catalog digest
    -> verify Source Coordinate + Release Version
    -> select descriptor-owned artifact
    -> verify artifact size + SHA-256
    -> ResolvedAdapterRelease
```

## Boundary

This product owns GitHub-specific acquisition only. It does not own Catalog selection semantics, Project Lock, installation, Installed Adapter State, acceptance policy, publisher authority, registry topology or version solving.

GitHub release author/uploader metadata is retained as provider facts and is **not** treated as OrbitFabric publisher identity or authentication.

## Development baseline

Initial development is validated against OrbitFabric Core commit:

```text
4ba7a0b51a071b91150be4271fef6c6010bc80fd
```

That commit contains the provider-neutral Catalog API promoted by Core PR #253.

The package declares the intended first released Core dependency as `orbitfabric>=1.3,<2`. Until that Core minor release exists, development CI installs the exact Core commit first and installs this package with dependency resolution disabled.

No public package release should claim that Core `1.2.0` contains the Catalog API.

## Current status

Pre-release productization. No universal Release Source provider protocol is defined by this repository.

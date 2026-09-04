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

This product owns GitHub-specific acquisition only. It does not own Catalog selection semantics, Project Lock identity, installation semantics, Installed Adapter State, acceptance policy, publisher authority, registry topology or version solving.

GitHub release author/uploader metadata is retained as provider facts and is **not** treated as OrbitFabric publisher identity or authentication.

The consumer CLI orchestrates existing Core services. It does not redefine them.

## Consumer CLI

The package installs:

```text
orbitfabric-github-release-source
```

The CLI is intentionally provider-explicit. OrbitFabric Core does not dispatch `github-release` bindings itself.

### Resolve one exact release

```bash
orbitfabric-github-release-source resolve \
  path/to/catalog.json \
  github.com/FAROTECH:orbitfabric/fprime \
  --version 0.1.1 \
  --output-dir ./resolved-fprime
```

The command:

```text
loads the local Catalog with the Core AdapterCatalog model
    -> performs Core exact Source Coordinate + version selection
    -> resolves through GitHubReleaseSource
    -> verifies descriptor identity and digest
    -> verifies descriptor-owned artifact size and SHA-256
    -> materializes verified descriptor/artifact bytes
```

If `GITHUB_TOKEN` is present in the environment it is used for GitHub requests. No token is required for normal public release access when unauthenticated GitHub limits are sufficient.

### Ensure one Project Lock entry

```bash
orbitfabric-github-release-source ensure \
  path/to/catalog.json \
  path/to/adapter-lock.json \
  github.com/FAROTECH:orbitfabric/fprime
```

`ensure` is deliberately Project-Lock-driven. It does **not** accept a second `--version` input because the Project Lock already owns the exact desired release version.

The ordering is:

```text
load Project Lock
    -> inspect current Installed Adapter State

if MATCH
    -> NOOP
    -> do not read Catalog
    -> do not contact GitHub

otherwise
    -> load local Catalog
    -> Core exact selection using the locked version
    -> verify Catalog descriptor digest agrees with Project Lock
    -> resolve through GitHubReleaseSource
    -> hand ResolvedAdapterRelease to Core ProjectLockInstallService
    -> require final MATCH
    -> remove temporary acquisition workspace
```

This preserves the important property that an already-satisfied project does not depend on Catalog or provider availability merely to remain satisfied.

## Why this is not a Core provider dispatcher

A shorter future UX may eventually look conceptually like:

```text
orbitfabric adapter install <adapter> --version <version>
```

That requires Core to map provider identifiers to installed provider implementations.

This repository does not define that protocol. A generic provider registration/dispatch mechanism remains deferred until a second materially different provider provides enough evidence to generalize safely.

The current supported split is therefore explicit:

```text
Core
    local Catalog validate/list/select
    Project Lock / install lifecycle

GitHub Release Source
    GitHub-specific resolve/ensure orchestration
```

## Development baseline

Current development is validated against OrbitFabric Core commit:

```text
714403034b49b7b7c67fcf42ab2c14feff79295f
```

That commit includes the provider-neutral Catalog API promoted by Core PR #253 and the provider-neutral Catalog CLI promoted by Core PR #254.

The package declares the intended first released Core dependency as:

```text
orbitfabric>=1.3,<2
```

Until that Core minor release exists, development CI installs the exact Core commit first and installs this package with dependency resolution disabled.

No public package release should claim that Core `1.2.0` contains the Catalog API or consumer CLI.

## Current status

Pre-release productization. The GitHub provider implementation and provider-explicit consumer CLI are being validated before the first packaged release.

No universal Release Source provider protocol is defined by this repository.

# Architecture and Ownership

## Product role

`orbitfabric-github-release-source` is a provider-specific acquisition product.

It interprets only GitHub Releases source bindings and returns verified release material through OrbitFabric Core's provider-neutral `ResolvedAdapterRelease` handoff.

## Ownership

```text
OrbitFabric Core
    Catalog model and exact selection
    ReleaseTrustEvidence model
    acceptance policy
    Project Lock / install lifecycle

This product
    GitHub binding interpretation
    GitHub release lookup
    provider asset acquisition
    descriptor/artifact byte verification
    factual GitHub release metadata
    ResolvedAdapterRelease construction

Adapter repository
    Release Descriptor
    artifact membership
    published release bytes
```

## Explicit non-goals

This repository does not define a universal source-provider interface, provider preference/failover, registry service, version solver, update mechanism, publisher authority database, or marketplace semantics.

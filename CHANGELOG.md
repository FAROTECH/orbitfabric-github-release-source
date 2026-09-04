# Changelog

## Unreleased

- establish the first GitHub Releases source product for OrbitFabric adapter acquisition;
- consume Core exact Catalog release selections;
- verify Release Descriptor and artifact identity fail-closed;
- preserve GitHub provider facts separately from OrbitFabric trust/acceptance semantics;
- add the provider-explicit `orbitfabric-github-release-source resolve` command for exact Catalog-selected GitHub release materialization;
- add Project-Lock-driven `orbitfabric-github-release-source ensure`, including `MATCH -> NOOP` before Catalog/provider access and temporary acquisition cleanup after installation;
- validate the consumer CLI against the provider-neutral Core Catalog CLI baseline without defining a generic provider dispatch protocol.

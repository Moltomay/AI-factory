# ARCHITECTURE.md — Clean Architecture (service repos)

This repo follows Clean Architecture. This file is the only architecture you need to follow here. Replace `your_package` with the real package name in `.importlinter`.

## Layers

```
your_package/
├── domain/          # business rules and entities — pure Python
├── application/     # use cases + ports (interfaces)
├── infrastructure/  # adapters: DB, HTTP clients, Spark, file I/O, model registry
└── interfaces/      # entry points: FastAPI routers, CLI commands, composition root
```

- **`domain/`** — entities and business logic. Pure Python: no I/O, no framework imports (no Spark session, `requests`, DB client, FastAPI). Unit-tested heavily and cheaply.
- **`application/`** — use cases and orchestration. Defines **ports** (abstract interfaces) for anything that touches the outside world, and depends only on those abstractions. No direct SDK calls.
- **`infrastructure/`** — implements the ports (adapters). The only layer allowed to import external SDKs.
- **`interfaces/`** — thin entry points that call use cases. No business logic. This is also the **composition root**: the one place where adapters are wired to ports.

## The dependency rule

Dependencies point inward: `interfaces → infrastructure → application → domain`. Never the reverse. *(enforced by `.importlinter` — a violation fails CI.)*

## Rules

- A port exists to isolate I/O. Don't create ports for pure logic.
- The domain raises **domain-specific exceptions** (e.g. `InvalidFeatureSchema`), never raw library exceptions. Infrastructure adapters translate low-level errors (`SparkException`, `HTTPError`) into domain exceptions at the boundary, so callers never need to know which library failed.
- Validate untrusted input at the `interfaces/` boundary, before it reaches a use case.
- Unit-test `domain/` and `application/` with fakes for the ports; integration-test `infrastructure/` adapters.

## Adding a new use case

1. Write the spec (contract, edge cases, acceptance criteria) and wait for the go.
2. Domain entities/logic, with unit tests.
3. The port(s) the use case needs, in `application/`.
4. The use case itself, tested with fake ports.
5. The adapter in `infrastructure/`, with an integration test.
6. The thin route/command in `interfaces/`.
7. Update docs.

## Stop and ask

Stop if you need to add a new top-level package, change a layer rule, or import across layers "just this once". Don't edit `.importlinter` to make it pass.

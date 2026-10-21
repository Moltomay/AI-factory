---
name: graphify-codebase-map
description: Build a local, free codebase map with Graphify (graph.json, graph.html, GRAPH_REPORT.md) and answer architecture questions with god-nodes/explain/path. Use when the user mentions "graphify", "codebase graph", "code map", "cartographie du code", "GRAPH_REPORT" or "graph.json", or asks how a module/symbol relates to the rest of the codebase.
---

# Graphify — Local Codebase Map

## What this does

Parses a codebase with tree-sitter (AST only), clusters symbols into communities and writes a fixed set of artifacts:

- `graphify-out/graph.json` — machine-readable graph
- `graphify-out/graph.html` — interactive visualization
- `graphify-out/GRAPH_REPORT.md` — god nodes, communities, import cycles, suggested questions

The output directory is fixed: `graphify-out/` at the codebase root.

## Requirements

- Run from the codebase root.
- Graphify CLI installed locally: `graphifyy==0.9.92` (dev-only, pinned; never add it to project requirements or CI).
- Install if missing (inside the project venv or any local environment):
  `pip install graphifyy==0.9.92`
- If `graphify` is not on PATH:
  - Windows: `.venv/Scripts/graphify.exe`
  - Unix: `.venv/bin/graphify`

## Generate the map

POSIX shells:

```sh
GRAPHIFY_BACKEND=none graphify extract . --code-only
GRAPHIFY_BACKEND=none graphify cluster-only . --no-label
```

PowerShell:

```powershell
$env:GRAPHIFY_BACKEND = "none"
graphify extract . --code-only
graphify cluster-only . --no-label
```

- `--code-only` — AST extraction only; skips docs/papers/images; no API key, no network, no tokens.
- `--no-label` — keeps deterministic `Community N` names; avoids LLM calls.
- `extract --help` is not supported; use `graphify --help`.

## Explore

```sh
graphify god-nodes --top 10          # most connected nodes (architecture hubs)
graphify explain "ProcessTicket"     # explain a node and its connections
graphify path "A" "B"                # shortest path between two nodes
```

These commands default to `graphify-out/graph.json`. Exit codes: `0` answer, `3` ambiguous name (candidates listed), `4` unknown node. Read `graphify-out/GRAPH_REPORT.md` for communities, surprising connections, import cycles and suggested questions.

## Refresh after code changes

Re-run the two generation commands above (the manifest/incremental cache reuses unchanged files). If files were deleted and the graph shrinks, force a full re-scan with `--force` (or `GRAPHIFY_FORCE=1`).

## Verify

- `graphify-out/graph.json` is non-empty and `GRAPH_REPORT.md` contains a "God Nodes" section.
- `graph.html` opens in a browser.
- Reference run on AI-factory (2026-10): 541 nodes, 1269 edges, 18 communities, ~13 s, 0 tokens.

## Do not

- No LLM backend or API key for extraction (no semantic naming).
- No `graphify install`, `watch`, or other commands that modify the repository or agent configuration.
- Never commit `graphify-out/` artifacts.
- Do not add Graphify to project requirements or CI.

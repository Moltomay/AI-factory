# Spec 03 — `infrastructure-adapters` (Étape 3)

> Les specs sont numérotées dans l'ordre d'exécution des étapes : `specs/NN-<task>.md`.

## Contexte

- Étape 2 mergée (PR #3) : ports + use case testés avec des fakes, mais aucune implémentation réelle.
- Cette étape branche le monde extérieur : Trello (tickets), GitHub (git + PR), OpenRouter (agents LLM).
- Livraison en 3 commits verts sur une branche unique, **une seule PR** : 03a Trello -> 03b GitHub -> 03c LLM.

## Objectifs

1. Les ports de l'étape 2 ont une implémentation réelle, dans `infrastructure/` uniquement.
2. Les vrais tests sont possibles en local dès cette étape, sans jamais les faire tourner en CI.
3. Aucun secret ne fuit : ni dans le code, ni dans les logs, ni dans les messages d'erreur.

## Périmètre — inclus

1. `domain/errors.py` : + `ExternalServiceError(DomainError)` — traduction des erreurs techniques au boundary (cf. `ARCHITECTURE.md`).
2. `application/ports.py` : + `TicketSource.fetch_next_ticket() -> Ticket | None` — amendement de la spec 02 (prévu à l'étape 4, avancé ici pour livrer un vrai test Trello).
3. `infrastructure/trello.py` — `TrelloBoard(api_key, token, list_id, base_url=...)` :
   - `fetch_next_ticket` : 1ʳᵉ carte de la liste configurée -> `Ticket` (id/name/desc) ; liste vide -> `None`.
   - `report_result` : commentaire sur la carte du ticket.
   - HTTP en stdlib (`urllib`), timeout ; erreurs HTTP/JSON -> `ExternalServiceError` **sans clé/token dans le message** (ils passent en query string).
4. `infrastructure/github.py` — `GitHubVersionControl(token, repository, workdir, base_branch="main")` :
   - Workdir cloné au 1er usage si absent ; auth git via `-c http.extraHeader` (token jamais écrit dans `.git/config` ni dans les messages d'erreur).
   - `create_branch` : `fetch` puis branche (re)créée depuis `origin/<base>` (idempotent pour les reruns).
   - `publish_pull_request` : `add`/`commit`/`push` + REST `POST /repos/{repo}/pulls` -> `html_url` ; identité de commit fixée par le code.
5. `infrastructure/openrouter_agent.py` — `OpenRouterAgent(api_key, model, workdir, ...)` implémentant `CodeAgent` via le SDK `openai` (`base_url` OpenRouter) :
   - Outils dev : `read_file`, `list_files`, `write_file`, `run_command` ; reviews : lecture seule (`read_file`, `list_files`, `run_command`).
   - Confinement strict au workdir (anti path-traversal), timeout des commandes, budget `MAX_AGENT_TURNS` -> `ExternalServiceError`.
   - Verdict de review = JSON `{approved, summary, findings}` -> `StageOutcome` ; JSON ou schéma invalide -> `ExternalServiceError`.
6. Config locale/tests : `tests/conftest.py` charge `AI-factory/.env` (gitignoré) sans écraser l'environnement ; marker `integration` enregistré dans `pyproject.toml` ; tests réels `skipif` si variables absentes.
7. Dépendance : `openai` (pinnée) dans `requirements.txt` — seule nouvelle dépendance ; Trello/GitHub restent en stdlib.
8. README : ligne « Status ».

## Périmètre — exclu

- CLI / composition root (étape 4), E2E complet (étape 5), optimisation des prompts.
- Retries réseau (propagent en `ExternalServiceError`).
- Transitions de statut Trello (le résultat est un commentaire).

## Critères d'acceptation

| # | Critère |
|---|---|
| AC1 | Trello : 1ʳᵉ carte -> `Ticket` (id/name/desc) ; liste vide -> `None` |
| AC2 | Trello : `report_result` poste le commentaire ; erreur HTTP -> `ExternalServiceError`, message sans token |
| AC3 | GitHub : `create_branch` part de `origin/main` ; `publish_pull_request` commit + push + PR et retourne l'URL |
| AC4 | GitHub : échec git/HTTP -> `ExternalServiceError` ; token absent des messages d'erreur |
| AC5 | LLM : la boucle exécute les tool calls dans le workdir (write effectif) et s'arrête quand le modèle ne demande plus d'outil |
| AC6 | LLM : budget de tours dépassé -> `ExternalServiceError` ; outils d'écriture absents en review |
| AC7 | LLM : verdict JSON -> `StageOutcome` ; JSON invalide -> `ExternalServiceError` |
| AC8 | Réels (marker `integration`, env) : commentaire Trello vérifié via API ; PR sandbox ouverte puis nettoyée ; 1 appel chat OpenRouter non vide |

## Hypothèses

- `.env` local = source des secrets pour les tests réels (jamais commité, chargé par `conftest.py`).
- CI inchangée : `pytest tests/unit` ; les réels ne tournent qu'en local via `pytest tests/integration -m integration`.
- Repo sandbox : `Moltomay/ai-factory-sandbox` (privé, base `main`) ; board Trello sandbox, liste « To Do », 1 carte test.
- Branche : `feat/03-infrastructure-adapters` depuis `main` (`bd91a47`) ; 1 PR, 3 commits ; spec enregistrée sous `specs/03-infrastructure-adapters.md`.

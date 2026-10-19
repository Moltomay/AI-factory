# Spec 02 — `process-ticket` (Étape 2)

> Les specs sont numérotées dans l'ordre d'exécution des étapes : `specs/NN-<task>.md`.

## Contexte

- Étape 1 mergée (PR #2) : le domaine sait *quoi* faire (machine à états, gate QA) mais rien ne l'orchestre ; `ai_factory/application/` est vide.
- Cette étape pose la couche **application** : les **ports** (`typing.Protocol`) qui isolent le use case du monde extérieur, et le use case `ProcessTicket` qui traite un ticket de bout en bout (dev -> checks + QA -> review -> PR).
- Le use case dépend du domaine et des ports uniquement ; les tests utilisent des fakes in-memory (zéro réseau, zéro git réel).

## Objectifs

1. Un ticket traverse tout le pipeline en un appel : `ProcessTicket.execute(ticket)`.
2. Toute I/O passe par un port testable ; aucune nouvelle dépendance.
3. Le retry (findings d'un échec -> tentative suivante) est câblé et testé.

## Périmètre — inclus

1. `ai_factory/application/ports.py` — 4 ports :

| Port | Méthode | Contrat |
|---|---|---|
| `TicketSource` | `report_result(ticket, message) -> None` | Dépose le résultat final sur le ticket (commentaire) |
| `CodeAgent` | `implement(ticket, feedback: tuple[str, ...]) -> None` | Modifie la copie de travail |
| | `quality_review(ticket, feedback) -> StageOutcome` | Verdict de l'agent QA |
| | `final_review(ticket, feedback) -> StageOutcome` | Verdict de l'agent relecteur |
| `QualityRunner` | `run_checks() -> bool` | Checks déterministes (lint/tests) du working copy |
| `VersionControl` | `create_branch(branch_name) -> None` | Crée la branche de travail |
| | `publish_pull_request(branch_name, title, body) -> str` | Commit + push + PR, retourne l'URL |

2. `ai_factory/application/process_ticket.py` — use case :
   - `ProcessTicketResult` (frozen) : `run: PipelineRun`, `pull_request_url: str | None`.
   - `ProcessTicket.execute(ticket)` : `run.start()` ; `create_branch("factory/<ticket_id>")` une seule fois avant le 1er dev ; boucle tant que non terminal :
     - `IMPLEMENTING` -> `implement(ticket, feedback)` puis `development_completed()`
     - `QUALITY_CHECK` -> `verdict = combine_quality_results(run_checks(), quality_review(ticket, feedback))` ; `record_quality_outcome(verdict.approved)` ; feedback = findings
     - `FINAL_REVIEW` -> `verdict = final_review(ticket, feedback)` ; `record_review_outcome(verdict.approved)` ; feedback = findings
   - Terminal : `PULL_REQUEST_OPENED` -> `publish_pull_request(branch, ticket.title, ticket.description)` + `report_result("Pull request opened: <url>")` ; `FAILED` -> `report_result("Automated processing failed: <raison>")`, aucune PR.
   - `feedback` = findings du dernier échec (vide au 1er tour), réinjectés dans la tentative suivante.
   - Toute exception d'un port propage telle quelle : pas de PR, pas de report.
3. Tests `tests/unit/application/` : fakes in-memory + un test par AC (< 1 s).
4. README : ligne « Status ».

## Périmètre — exclu

- Fetch des tickets (`TicketSource.fetch_next_ticket`) : ajouté à l'étape 4 quand le CLI en aura besoin.
- Adapters réels Trello/LLM/GitHub (étape 3), CLI (étape 4), tests d'intégration.
- Transitions de statut Trello (le résultat est un simple commentaire au MVP).
- Retries réseau / erreurs transitoires des ports (propagent telles quelles).

## Critères d'acceptation

| # | Critère |
|---|---|
| AC1 | Happy path : ordre des appels `create_branch -> implement -> run_checks -> quality_review -> final_review -> publish_pull_request -> report_result` ; `PULL_REQUEST_OPENED` ; URL retournée ; title/body de PR = ticket |
| AC2 | Échec QA puis succès : la 2ᵉ tentative de dev reçoit les findings du 1er échec ; `development_attempts = 2` ; PR ouverte |
| AC3 | Checks KO + review QA OK -> refus combiné ; le finding synthétique est transmis au retry |
| AC4 | Échec review -> retry avec ses findings, puis succès -> PR |
| AC5 | Budget épuisé (3 échecs) : `FAILED`, `failure_reason` rempli, aucune PR, report avec la raison |
| AC6 | `report_result` appelé exactement une fois, dans les deux états terminaux |
| AC7 | Exception d'un port -> propagée, aucune PR, aucun report |
| AC8 | Branche créée une seule fois malgré les retries |

## Hypothèses

- Messages reportés : `Pull request opened: <url>` et `Automated processing failed: <raison>` (constantes nommées).
- Branche : `factory/<ticket_id>` (constante `BRANCH_NAME_TEMPLATE`).
- Corps de PR = `ticket.description` telle quelle ; titre = `ticket.title`.
- Aucune modification du domaine ; aucune nouvelle dépendance.
- Branche : `feat/02-process-ticket` depuis `main` (`bd91a47`) ; spec enregistrée sous `specs/02-process-ticket.md`.

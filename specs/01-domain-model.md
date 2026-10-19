# Spec 01 — `domain-model` (Étape 1)

> Les specs sont numérotées dans l'ordre d'exécution des étapes : `specs/NN-<task>.md`.

## Contexte

- Étape 0 mergée (PR #1) : package `ai_factory` + contrat layers actif (`lint-imports`).
- Cette étape pose le **cœur métier** du pipeline MVP, en Python pur (`ai_factory/domain/`, aucune I/O, aucun framework) : ce que le pipeline a le droit de faire, dans quel ordre, et quand il échoue.
- Pipeline MVP modélisé : **Dev** (implémentation) -> **QA** (vérif qualité) -> **Reviewer** (revue finale) -> **PR ouverte** ; un rejet QA ou review renvoie au Dev dans la limite d'un **budget de tentatives** ; budget épuisé -> échec définitif.

## Objectifs

1. Le modèle métier est explicite et enforceé : toute transition illégale lève une exception domaine.
2. Le budget de tentatives est une règle nommée et testée (pas un chiffre magique).
3. Le contrat de sortie des agents (`StageOutcome`) est figé pour les étapes 2–3.

## Périmètre — inclus

Types dans `ai_factory/domain/` :

1. `errors.py` — `DomainError` (base) ; `InvalidTicketError`, `InvalidStageOutcomeError`, `InvalidStageTransitionError`, avec messages explicites.
2. `ticket.py` — `Ticket` (dataclass frozen) : `ticket_id: str`, `title: str`, `description: str`. Invariants : `ticket_id` et `title` non vides (sinon `InvalidTicketError`).
3. `outcomes.py` — `StageOutcome` (frozen) : `approved: bool`, `summary: str` (non vide, sinon `InvalidStageOutcomeError`), `findings: tuple[str, ...] = ()`.
4. `quality_gate.py` — `combine_quality_results(checks_passed: bool, review_outcome: StageOutcome) -> StageOutcome` : règle métier **approved = checks ET review** ; si checks KO, ajoute un finding synthétique (constante nommée) ; si checks OK, résultat = celui du review.
5. `pipeline.py` :
   - `AgentRole` (enum) : `DEVELOPER`, `QUALITY_ANALYST`, `REVIEWER`.
   - `PipelineStage` (enum) : `NEW`, `IMPLEMENTING`, `QUALITY_CHECK`, `FINAL_REVIEW`, `PULL_REQUEST_OPENED`, `FAILED` + propriété `role` (`AgentRole | None`) : `IMPLEMENTING`->`DEVELOPER`, `QUALITY_CHECK`->`QUALITY_ANALYST`, `FINAL_REVIEW`->`REVIEWER`, autres -> `None`.
   - `PipelineRun` (dataclass) : `ticket: Ticket`, `stage = NEW`, `development_attempts: int = 0`, `failure_reason: str | None = None` + propriété `is_finished`.
   - `MAX_DEVELOPMENT_ATTEMPTS = 3` (constante nommée, première tentative incluse).

Table de transitions (toute méthode appelée dans un mauvais état -> `InvalidStageTransitionError`) :

| Méthode | État requis | Résultat |
|---|---|---|
| `start()` | `NEW` | `IMPLEMENTING`, attempts = 1 |
| `development_completed()` | `IMPLEMENTING` | `QUALITY_CHECK` |
| `record_quality_outcome(approved=True)` | `QUALITY_CHECK` | `FINAL_REVIEW` |
| `record_quality_outcome(approved=False)` | `QUALITY_CHECK` | attempts < MAX : `IMPLEMENTING` (attempts+1) ; sinon `FAILED` + `failure_reason` |
| `record_review_outcome(approved=True)` | `FINAL_REVIEW` | `PULL_REQUEST_OPENED` |
| `record_review_outcome(approved=False)` | `FINAL_REVIEW` | attempts < MAX : `IMPLEMENTING` (attempts+1) ; sinon `FAILED` + `failure_reason` |

6. Tests `tests/unit/domain/` (purs, < 1 s) : une règle = un test, cas limites inclus.
7. README : mise à jour de la ligne « Status ».

## Périmètre — exclu

Ports et use case (étape 2), adapters Trello/LLM/GitHub (étape 3), CLI (étape 4), prompts LLM, nommage de branche, gestion des erreurs techniques des agents (étape 2, pas du métier).

## Critères d'acceptation

| # | Critère |
|---|---|
| AC1 | `Ticket` valide se construit ; `ticket_id`/`title` vides ou blancs -> `InvalidTicketError` |
| AC2 | `StageOutcome` : `summary` vide/blanc -> `InvalidStageOutcomeError` ; `findings` par défaut vide ; objets immuables |
| AC3 | Gate QA : approuvé seulement si checks ET review ; finding synthétique si checks KO ; sinon outcome du review |
| AC4 | Happy path complet : `NEW -> IMPLEMENTING -> QUALITY_CHECK -> FINAL_REVIEW -> PULL_REQUEST_OPENED`, `is_finished`, attempts = 1 |
| AC5 | Rejet QA et rejet review : retour `IMPLEMENTING` + incrément des attempts |
| AC6 | Budget épuisé (à la MAX-ième tentative) : rejet -> `FAILED`, `failure_reason` contient le nombre de tentatives, `is_finished` |
| AC7 | Méthode appelée dans un mauvais état -> `InvalidStageTransitionError` |
| AC8 | `PipelineStage.role` : mapping correct, `None` pour les états sans agent |

## Hypothèses

- `MAX_DEVELOPMENT_ATTEMPTS = 3`, rejets QA et review partagent le même budget (pas de budget séparé au MVP).
- `FAILED` est un **résultat métier** (pas une exception) ; les erreurs techniques des agents le seront à l'étape 2.
- Messages d'échec et finding synthétique en anglais (constantes nommées), cohérents avec le code.
- Branche : `feat/01-domain-model` depuis `main` (`3ca19cf`) ; spec enregistrée sous `specs/01-domain-model.md`.

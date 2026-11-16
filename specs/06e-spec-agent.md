# Spec 06e — `spec-agent` (Étape 6e)

> Les specs sont numérotées dans l'ordre d'exécution des étapes : `specs/NN-<task>.md`.
> 06e complète l'équipe après 07 : 07 reste la référence pour la consolidation
> 4 → 3 et les policies Coding/Code Review ; 06e ajoute le Spec agent, le stage
> `SPECIFYING`, l'artefact d'ACs et son validateur.

## Contexte

- 07 a livré deux agents actifs, Coding et Code Review, et un pipeline
  `NEW -> IMPLEMENTING -> REVIEW -> PULL_REQUEST_OPENED`.
- Le ticket brut est la seule source d'exigences. Coding et Code Review
  reconstruisent chacun leur interprétation des ACs : la conformité reviewée
  n'est pas traçable mécaniquement, et deux runs peuvent diverger.
- 06e ajoute un **Spec agent** qui transforme le ticket en artefact borné :
  problème cité, périmètre inclus/exclu, ACs numérotés et traçables, unknowns,
  definition of done. Le même artefact est lu par Coding et Code Review.
- L'artefact est un **état de la factory en mémoire**
  (`PipelineRun.specification`), jamais un fichier du clone cible. La persistance
  et l'audit sont cadrés par la **Spec 10 — Logging & audit trail** (TODO), pas
  par 06e.
- Le gate déterministe et les contrats de review de 07 ne changent pas.

## Objectifs

1. Ajouter le stage `SPECIFYING` avant `IMPLEMENTING` et le rôle `SPEC_WRITER`.
2. Produire un artefact déterministe, borné et validé avant tout code.
3. Garantir des ACs numérotés, testables et traçables à une phrase du ticket.
4. Passer le même artefact à Coding et à Code Review, y compris après retry.
5. Refuser un ticket ambigu par `needs_clarification`, sans invention.
6. Préserver le gate `ruff check` + `pytest` et les contrats 07.
7. Ne pas ajouter de dépendance, de configuration ou de changement CI.

## Périmètre — inclus

1. `ai_factory/domain/pipeline.py`
   - `AgentRole` : `SPEC_WRITER`, `DEVELOPER`, `CODE_REVIEWER`.
   - `PipelineStage` : `NEW`, `SPECIFYING`, `IMPLEMENTING`, `REVIEW`,
     `PULL_REQUEST_OPENED`, `FAILED`.
   - `PipelineStage.role` : `SPECIFYING` → `SPEC_WRITER`,
     `IMPLEMENTING` → `DEVELOPER`, `REVIEW` → `CODE_REVIEWER`.
   - `PipelineRun.specification: Specification | None`.
   - `start()` : `NEW` → `SPECIFYING`, `development_attempts = 0`.
   - `specification_completed(specification)` : `SPECIFYING` → `IMPLEMENTING`,
     stocke la spec, `development_attempts = 1`.
   - `clarification_requested(questions)` : `SPECIFYING` → `FAILED`, raison
     formatée à partir des questions.
   - `development_completed()` et `record_review_outcome(approved)` inchangés.
   - `MAX_DEVELOPMENT_ATTEMPTS` reste `3`.

2. `ai_factory/domain/specification.py` — nouveau module
   - `AcceptanceCriterion` : `id`, `statement`, `ticket_quote`.
   - `Specification` : `problem`, `scope_in`, `scope_out`,
     `acceptance_criteria`, `unknowns`, `definition_of_done`.
   - `SpecOutcome` : soit une `Specification`, soit des `questions` ; exactement
     un des deux.
   - Constantes de bornes (table ci-dessous).
   - `Specification.render()` et `SpecOutcome.render()` : rendus déterministes,
     sections dans un ordre fixe.
   - `validate_spec_outcome(payload, ticket) -> SpecOutcome` : validateur pur,
     sans I/O, qui accepte `ready` et `needs_clarification`.
   - Aucun accès fichier, réseau ou repo cible.

3. `ai_factory/domain/errors.py`
   - `InvalidSpecificationError(DomainError)`.

4. `ai_factory/domain/agent_policies.py`
   - `SPEC_WRITER_POLICY` et `SPEC_OUTPUT_CONTRACT` / `SPEC_SCHEMA`.
   - `AGENT_POLICIES` et `policy_for` couvrent les trois rôles.
   - La policy est factory-owned, statique, sans contenu du repo cible.

5. `ai_factory/application/ports.py`
   - `SpecAgent.specify(ticket) -> SpecOutcome`.
   - `CodeAgent.implement(ticket, specification, feedback)` et
     `review(ticket, specification, feedback) -> StageOutcome`.
   - Aucun autre changement de port.

6. `ai_factory/application/process_ticket.py`
   - `ProcessTicket` reçoit `spec_agent`.
   - `execute` : `start()` → `specify` → validation → création de branche →
     boucle `IMPLEMENTING`/`REVIEW`.
   - Clarification : `FAILED`, aucune branche, aucune PR, questions reportées.
   - La spec est passée à chaque `implement` et à chaque `review` ; elle survit
     au retry après rejet.
   - Le corps de PR gagne une section `## Acceptance criteria` (id + statement).

7. `ai_factory/infrastructure/openrouter_agent.py`
   - `specify(ticket)` : policy Spec, **sans outil**, parse JSON, un seul retry
     correctif, puis `ExternalServiceError`.
   - `implement`/`review` : rendent la spec dans le message utilisateur.
   - Le parseur de verdict, le retry correctif de review et les listes d'outils
     existants ne changent pas.

8. `ai_factory/interfaces/composition.py`
   - Câble le même `OpenRouterAgent` comme `spec_agent` et `code_agent`.

9. Tests unitaires + `README.md`.

## Périmètre — exclu

- Persistance, fichiers physiques, logs, SQLite, audit des specs (Spec 10).
- Commentaire de PR ou fichier de spec dans le clone cible.
- Modèle OpenRouter par agent.
- Nouveaux checks déterministes, changement du gate ou du port `QualityRunner`.
- Lecture de `AGENTS.md`, `ARCHITECTURE.md`, `ruff.toml` ou CI du repo cible ;
  digest du repo cible.
- Modification des specs historiques `01`, `02`, `06d`, `07`.
- Nouvelle dépendance, changement de configuration ou de CI.
- Édition de l'artefact par Coding ou Code Review (lecture seule).

## Contrat

### Pipeline et rôles

| Agent | Stage | Mandat |
|---|---|---|
| Spec | `SPECIFYING` | ticket → problème, périmètre, ACs, unknowns, DoD ; clarification si ambigu |
| Coding | `IMPLEMENTING` | implémente la spec/les ACs, écrit les tests, répond au feedback |
| Code Review | `REVIEW` | gate final : conformité spec/ACs, tests, sécurité, design, erreurs, scope, opérabilité, clean code |

```text
NEW -> SPECIFYING -> IMPLEMENTING -> REVIEW -> PULL_REQUEST_OPENED
                          ^              |
                          |              v
                          +--------- IMPLEMENTING (retry) -> FAILED (budget épuisé)

SPECIFYING -> FAILED (needs_clarification)
```

- Une clarification est terminale : pas de retry de développement, pas de branche.
- Un artefact malformé déclenche un seul retry correctif dans l'adapter, puis
  `ExternalServiceError`.
- `MAX_DEVELOPMENT_ATTEMPTS` reste `3` ; la spec ne consomme pas ce budget.

### Artefact — mode `ready`

```json
{
  "status": "ready",
  "problem": "problème reformulé, cité du ticket",
  "scope_in": ["ce qui est inclus"],
  "scope_out": ["ce qui est explicitement exclu"],
  "acceptance_criteria": [
    {
      "id": "AC1",
      "statement": "comportement attendu, observable et testable",
      "ticket_quote": "phrase exacte du ticket"
    }
  ],
  "unknowns": ["hypothèse ou point non tranché"],
  "definition_of_done": ["vérification attendue avant la PR"]
}
```

### Artefact — mode `needs_clarification`

```json
{
  "status": "needs_clarification",
  "questions": ["question actionnable pour le demandeur"]
}
```

### Bornes

| Constante | Valeur |
|---|---:|
| `MAX_ACCEPTANCE_CRITERIA` | 20 |
| `MIN_ACCEPTANCE_CRITERIA` | 1 |
| `MAX_SPEC_CHARS` (rendu) | 16 000 |
| `MAX_PROBLEM_CHARS` | 1 500 |
| `MAX_AC_STATEMENT_CHARS` | 300 |
| `MAX_TICKET_QUOTE_CHARS` | 300 |
| `MAX_SCOPE_ITEMS` (par liste) | 15 |
| `MAX_SCOPE_ITEM_CHARS` | 200 |
| `MAX_UNKNOWNS` | 10 |
| `MAX_UNKNOWN_CHARS` | 200 |
| `MAX_DEFINITION_OF_DONE_ITEMS` | 10 |
| `MAX_DEFINITION_OF_DONE_CHARS` | 200 |
| `MAX_CLARIFICATION_QUESTIONS` | 5 |
| `MAX_QUESTION_CHARS` | 300 |
| `MAX_CLARIFICATION_CHARS` | 2 000 |

Justification : les specs du repo font 2,4–20,6 KB ; 16 000 caractères est entre
`06b` (16,5 KB, 25 ACs) et `07` (20,6 KB, ACs verbeux), ≈ 4 k tokens. Le total
est le plafond dur ; les plafonds par item évitent qu'un champ mange tout le
budget. Chaque tentative est une conversation neuve : la spec est rendue une
fois par appel, pas accumulée sur les trois tentatives.

### Validateur

`validate_spec_outcome(payload, ticket)` :

1. Le payload est un objet JSON.
2. `status` vaut exactement `ready` ou `needs_clarification`.
3. Mode `ready` : clés exactement `status`, `problem`, `scope_in`, `scope_out`,
   `acceptance_criteria`, `unknowns`, `definition_of_done`.
4. `problem` : chaîne non vide, ≤ `MAX_PROBLEM_CHARS`.
5. `scope_in` : 1–15 chaînes non vides, ≤ 200 caractères chacune.
   `scope_out`, `unknowns` : 0–15 / 0–10 chaînes non vides, mêmes bornes.
6. `acceptance_criteria` : 1–20 objets, clés exactement `id`, `statement`,
   `ticket_quote`.
   - `id` vaut `AC1`, `AC2`, …, `ACn` dans cet ordre.
   - `statement` non vide, ≤ 300 caractères, unique après normalisation des
     espaces et `casefold`.
   - `ticket_quote` non vide, ≤ 300 caractères, et **sous-chaîne verbatim** de
     `ticket.title + "\n" + ticket.description` après normalisation des espaces ;
     la comparaison est sensible à la casse.
7. `definition_of_done` : 1–10 chaînes non vides, ≤ 200 caractères chacune.
8. `len(specification.render()) ≤ MAX_SPEC_CHARS`.
9. Mode `needs_clarification` : clés exactement `status`, `questions` ;
   1–5 questions non vides, ≤ 300 caractères chacune ;
   `len(spec_outcome.render()) ≤ MAX_CLARIFICATION_CHARS`.
10. Toute violation lève `InvalidSpecificationError` avec un message qui nomme
    le champ fautif et la règle violée.

Le validateur ne juge pas la testabilité sémantique d'un AC : il vérifie la
structure, les bornes et la traçabilité. La policy et le Code Review jugent le
sens.

### Ports et ordre

```python
class SpecAgent(Protocol):
    def specify(self, ticket: Ticket) -> SpecOutcome: ...


class CodeAgent(Protocol):
    def implement(
        self, ticket: Ticket, specification: Specification, feedback: ReviewFeedback
    ) -> None: ...

    def review(
        self, ticket: Ticket, specification: Specification, feedback: ReviewFeedback
    ) -> StageOutcome: ...
```

- `ProcessTicket.execute` appelle `specify` **avant** `create_branch`.
- Une spec valide est stockée dans le run ; la branche est créée ensuite.
- Chaque `implement` et chaque `review` reçoit la même `Specification`.
- Un rejet de review renvoie vers `IMPLEMENTING` avec le feedback ; la spec est
  conservée telle quelle.
- Une clarification termine le run en `FAILED` ; `_finish` reporte la raison sur
  le ticket et ne publie rien.

### Policy Spec

- Reformuler le problème en citant les phrases du ticket.
- Définir le périmètre inclus et exclu.
- Produire 1–20 ACs numérotés, testables, observables, traçables à une phrase
  du ticket.
- Déclarer les hypothèses et les unknowns.
- Définir la definition of done.
- Pas d'invention : ticket ambigu ou contradictoire → `needs_clarification`.
- Ne pas coder, ne pas review, ne pas choisir l'implémentation au-delà du
  contrat.
- Ne mettre ni secret ni donnée personnelle dans l'artefact.
- Répondre avec un seul objet JSON, sans texte autour.
- Respecter les bornes ; condenser plutôt que dépasser.
- Aucun outil : le ticket est la seule entrée, pas d'accès au repo.

### PR

Le corps de PR devient :

```text
<description du ticket>

## Acceptance criteria

- AC1: <statement>
- AC2: <statement>

## Automated review

<findings minor, si présents>
```

Les `ticket_quote` ne sont pas recopiés dans la PR : ils restent dans
l'artefact en mémoire. La section ACs est omise quand aucune spec n'est
disponible.

### Gate et retry

- Gate inchangé : `ruff check .` puis `pytest` dans le clone, `pytest` sauté
  seulement sans dossier `tests/`.
- Gate rouge → aucun appel au Code Review, feedback direct vers `IMPLEMENTING`.
- La spec n'est jamais recalculée pendant les retries de développement.
- Un artefact invalide → un retry correctif dans l'adapter, puis échec bruyant ;
  ce n'est pas un retry de développement.

### Erreurs

- `InvalidSpecificationError` : payload invalide, borne dépassée, AC non
  traçable, mode incohérent.
- `InvalidStageTransitionError` : transition depuis un mauvais stage.
- `ExternalServiceError` : artefact toujours invalide après le retry correctif,
  ou échec OpenRouter.

## Critères d'acceptation

| # | Critère |
|---|---|
| AC1 | `AgentRole` contient exactement `SPEC_WRITER`, `DEVELOPER`, `CODE_REVIEWER` ; `PipelineStage` contient exactement `NEW`, `SPECIFYING`, `IMPLEMENTING`, `REVIEW`, `PULL_REQUEST_OPENED`, `FAILED` ; `SPECIFYING` est mappé à `SPEC_WRITER`, `IMPLEMENTING` à `DEVELOPER`, `REVIEW` à `CODE_REVIEWER` ; `MAX_DEVELOPMENT_ATTEMPTS` reste `3`. |
| AC2 | `start()` passe de `NEW` à `SPECIFYING` avec 0 tentative ; `specification_completed(spec)` passe à `IMPLEMENTING` avec 1 tentative et stocke la spec ; `clarification_requested(questions)` passe à `FAILED` avec une raison contenant les questions ; un appel depuis un mauvais stage lève `InvalidStageTransitionError` ; `development_completed` et `record_review_outcome` gardent le comportement 07. |
| AC3 | `AcceptanceCriterion` et `Specification` sont des value objects gelés avec les champs exacts ; `SpecOutcome` porte exactement une spec ou des questions (les deux ou aucun lève `InvalidSpecificationError`) ; `Specification.render()` et `SpecOutcome.render()` sont déterministes, incluent tous les champs dans un ordre fixe et ne font aucune I/O. |
| AC4 | `validate_spec_outcome` accepte un payload `ready` valide, retourne une `Specification` équivalente, et applique 1–20 ACs, ids `AC1..ACn` dans l'ordre, statements uniques, quotes verbatim du ticket (espaces normalisés, casse respectée) et toutes les bornes par item et totales. |
| AC5 | `validate_spec_outcome` rejette chaque payload `ready` malformé — clés manquantes ou inconnues, mauvais types, chaînes vides, ids non séquentiels ou dupliqués, statements dupliqués, quote absente du ticket, 0 ou 21 ACs, bornes par item ou total dépassées — avec `InvalidSpecificationError` nommant le champ fautif. |
| AC6 | `validate_spec_outcome` accepte un payload `needs_clarification` valide (1–5 questions non vides, ≤ 300 caractères chacune, total ≤ 2 000) et retourne un `SpecOutcome` avec les questions ; il rejette les payloads de clarification malformés et les `SpecOutcome` incohérents. |
| AC7 | Dans `ProcessTicket`, une clarification termine le run en `FAILED`, ne crée aucune branche, n'ouvre aucune PR, n'appelle ni `implement` ni `review`, et reporte les questions sur le ticket. |
| AC8 | `SpecAgent` expose `specify(ticket) -> SpecOutcome` ; `CodeAgent` expose `implement(ticket, specification, feedback)` et `review(ticket, specification, feedback)` ; le use case passe la même `Specification` à chaque tentative d'implémentation et à sa review, y compris après un rejet ; les fakes et tests sont adaptés ; aucun autre changement de port. |
| AC9 | `ProcessTicket` appelle `specify` avant `implement` ; `create_branch` n'a lieu qu'après une spec valide ; une clarification ne crée aucune branche ; le gate déterministe tourne toujours avant `review` ; un gate vert appelle `review` une fois avec la spec. |
| AC10 | `AgentRole.SPEC_WRITER` a une `SPEC_WRITER_POLICY` factory-owned ; `policy_for` retourne une policy pour les trois rôles ; la policy contient les règles validées (citations du ticket, périmètre, 1–20 ACs, unknowns, DoD, pas d'invention, clarification, pas de code/review, pas de secret/PII, JSON seul, sans outil, bornes) et le contrat de sortie avec les deux schémas JSON ; elle ne contient aucun contenu du repo cible. |
| AC11 | `OpenRouterAgent.specify` utilise la policy Spec sans outil, parse le JSON, fait un seul retry correctif sur une sortie invalide, puis lève `ExternalServiceError` ; `implement` et `review` rendent la spec dans le message utilisateur ; le parseur de verdict, le retry correctif de review et les listes d'outils restent inchangés. |
| AC12 | Quand une spec est présente, le corps de PR contient une section `## Acceptance criteria` listant `ACn: statement` pour chaque AC, après la description du ticket et avant la section de review automatique ; les `ticket_quote` ne sont pas incluses ; aucune section n'est émise sans spec. |
| AC13 | Le README documente trois agents (Spec, Coding, Code Review), les quatre stages (`SPECIFYING`, `IMPLEMENTING`, `REVIEW`, PR), l'artefact en mémoire, le validateur et le chemin de clarification, le gate inchangé, et le report de la persistance/audit à la Spec 10. |
| AC14 | La suite unitaire reste verte, la couverture de lignes reste ≥ 90 %, la sonde mutation sur le diff ne laisse aucun survivant actionnel (allowlist uniquement pour des mutants équivalents avec validation humaine), aucun test existant n'est supprimé ou affaibli sans remplacement équivalent listé dans la PR, et aucune dépendance, configuration ou CI ne change. |

Chaque AC est couvert par au moins un test nommé `test_spec06e_acN_<behavior>`.
Le mapping AC → test est reporté dans la PR.

### Remplacements et adaptations de tests

| Test existant | Traitement 06e |
|---|---|
| `test_spec07_ac1_pipeline_shape_and_roles` | Remplacé par `test_spec06e_ac1_pipeline_shape_and_roles` (le test 07 assertait l'absence de `SPECIFYING`/`SPEC_WRITER`). |
| `test_spec07_ac2_development_completed_enters_review` | Adapté : setup `start()` → `specification_completed()` → `IMPLEMENTING`, puis comportement 07 inchangé. |
| `test_spec07_ac2_review_outcome_opens_pull_request` | Adapté au setup avec spec ; comportement 07 inchangé. |
| `test_spec07_ac2_rejection_retries_then_exhausts_budget` | Adapté au setup avec spec ; comportement 07 inchangé. |
| `test_spec07_ac3_red_gate_skips_the_review_agent` | Adapté : le fake `review` reçoit la spec ; l'assertion « zéro appel » reste. |
| `test_spec07_ac3_green_gate_calls_review_once` | Adapté : la review reçoit la spec ; l'assertion « un appel » reste. |
| `test_spec07_ac4_code_agent_port_exposes_implement_and_review_only` | Adapté aux signatures avec `specification` ; l'assertion « implement + review seulement » reste. |
| `test_spec07_ac5_policy_for_every_role` | Adapté : trois rôles au lieu de deux. |
| `test_spec07_ac8_implement_uses_the_developer_policy` | Adapté : la spec est rendue dans le message ; la policy Developer reste. |
| `test_spec07_ac8_review_uses_the_code_review_policy` | Adapté : la spec est rendue dans le message ; la policy Review reste. |
| `test_spec07_ac8_system_prompt_contains_no_target_repository_content` | Assertion inchangée ; setup adapté. |
| `test_spec07_ac9_*` | Inchangés (gate). |
| `test_spec07_ac10_*` | Inchangés (outcomes). |
| `test_spec07_ac11_readme_documents_three_agents` | Adapté : le README ne dit plus que 06e « arrive » ; l'assertion trois agents reste. |
| Tests 06d/07 des policies Developer/Review | Inchangés. |

Aucun test n'est supprimé, skipé ou affaibli ; les remplacements ci-dessus sont
listés dans la PR.

## Hypothèses

- Le Spec agent tourne sans outil : ticket uniquement, pas d'accès au repo.
- L'artefact est en mémoire ; la persistance/audit est la Spec 10.
- Le validateur vérifie structure, bornes et traçabilité, pas la testabilité
  sémantique.
- La quote est sensible à la casse après normalisation des espaces ; une
  paraphrase est refusée.
- Un seul retry correctif pour l'artefact ; une clarification n'est pas une
  erreur.
- Le même `OpenRouterAgent` implémente `SpecAgent` et `CodeAgent`.
- Le gate reste `ruff check` + `pytest`.
- `MAX_DEVELOPMENT_ATTEMPTS` reste `3`.
- La borne 16 000 caractères est un budget de contexte, pas une mesure de
  qualité.

## Limites

- La testabilité sémantique n'est pas vérifiée mécaniquement.
- La quote prouve la citation, pas la justesse de l'AC ; un modèle peut citer
  une phrase non pertinente.
- La prompt injection via le ticket ou l'artefact reste possible ; le gate et la
  review humaine sont les garde-fous ; pas de durcissement dédié en 06e
  (backlog).
- Pas de persistance : un crash perd l'artefact ; 08b/10 traitent la reprise et
  l'audit.
- La borne 16 000 peut rejeter une spec légitime trop verbeuse ; le modèle doit
  condenser.
- L'artefact n'est visible humainement que par la section ACs de la PR.
- Le taux de `needs_clarification` n'est pas mesuré (Spec 10).
- La spec est rendue dans deux appels par tentative (Coding, Review), ce qui
  consomme des tokens.

## Plan de livraison

Branche `feat/06e-spec-agent`, une PR, commits verts successifs :

1. `domain/pipeline.py` + tests : rôles, stages, transitions, stockage de la
   spec (AC1-AC2).
2. `domain/specification.py` + `domain/errors.py` + tests : value objects,
   bornes, validateur, clarification (AC3-AC6).
3. `application/ports.py`, `application/process_ticket.py`, fakes et tests :
   `SpecAgent`, ordre, clarification, propagation de la spec (AC7-AC9).
4. `domain/agent_policies.py` + tests : policy Spec et contrat de sortie (AC10).
5. `infrastructure/openrouter_agent.py`, `interfaces/composition.py` + tests :
   `specify`, rendu, retry correctif (AC11).
6. Corps de PR, README, tests de documentation (AC12-AC13).
7. Vérifications finales : suite unitaire, couverture, mutation, mapping
   AC → test, rapport de PR (AC14).

Chaque commit laisse `ruff check`, `ruff format --check`, `lint-imports` et
`pytest tests/unit` verts. Aucun commit direct sur `main`.

## Décisions

1. Artefact en mémoire, pas de fichier dans le clone.
2. Clarification → `FAILED`, pas de nouveau stage terminal.
3. Section ACs dans la PR, sans les quotes.
4. 20 ACs max ; 16 000 caractères max pour le rendu.
5. Persistance/audit → Spec 10.

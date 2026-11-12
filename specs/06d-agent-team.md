# Spec 06d — `agent-team` (Étape 6d)

> Les specs sont numérotées dans l'ordre d'exécution des étapes : `specs/NN-<task>.md`.
> Cette spec est la charte de l'équipe d'agents. Le quatrième agent (Spec) est livré
> en 06e : son mandat est décrit ici pour que la charte soit complète, mais aucun
> critère d'acceptation ne porte sur son code.

## Contexte

- La spec 06 est éclatée en 06a (runtime), 06b (cycle de vie Trello), 06c (review
  JSON retry), 06d (équipe d'agents) et 06e (spec agent). 06a et 06b sont livrées.
  **06c est fusionnée dans 06d** : le parseur de verdict est commun aux deux
  reviewers, le polir avant d'avoir défini le schéma serait à refaire.
- `OpenRouterAgent` porte aujourd'hui trois prompts (`DEVELOPER_PROMPT`,
  `QUALITY_PROMPT`, `REVIEWER_PROMPT`). Les deux derniers se ressemblent :
  « correctness, tests and style » contre « as a strict senior reviewer ». Ils
  produisent le même JSON à trois champs, sans localisation ni preuve.
- `StageOutcome.findings` est un `tuple[str, ...]` : un finding est une phrase
  libre. Le développeur reçoit ce texte sans pouvoir le relier à un AC ni à un
  fichier, et rien ne distingue un blocage d'une remarque cosmétique.
- `StageOutcome.approved` vient du modèle et le code le prend au mot. Un
  `approved: true` accompagné de findings bloquants est accepté.
- `combine_quality_results` reçoit les deux entrées déjà évaluées : l'agent
  quality tourne même quand `ruff` ou `pytest` sont rouges. Le gate déterministe
  est autoritaire en droit, mais l'agent est appelé quand même et peut le
  contredire.
- La forme du pipeline ne change pas : mêmes stages (`IMPLEMENTING`,
  `QUALITY_CHECK`, `FINAL_REVIEW`), mêmes transitions, même
  `MAX_DEVELOPMENT_ATTEMPTS = 3`. 06d change les mandats et le contrat de sortie,
  pas le state machine.

## Objectifs

1. Deux reviewers aux mandats disjoints : Quality & Security et Code Review.
2. Un schéma de finding unique, partagé par les deux, localisé et priorisé.
3. L'approbation est **dérivée** des findings, jamais lue dans la réponse du modèle.
4. Le gate déterministe court-circuite l'agent : on ne paie pas une review sur un
   build rouge.
5. Un verdict illisible est corrigé **une fois**, puis échoue proprement.
6. Un plafond de findings borne le coût et le bruit du feedback.
7. Les findings `minor` restent visibles pour l'humain (corps de la PR).
8. Aucune nouvelle dépendance, aucun nouveau stage, aucun changement de la CLI.

## Périmètre — inclus

1. `domain/findings.py` — nouveau module : `FindingSeverity` (`BLOCKER`, `MAJOR`,
   `MINOR`), `FindingCategory` (`SPEC_CONFORMANCE`, `TESTS`, `SECURITY`,
   `DESIGN`, `ERROR_HANDLING`, `SCOPE`, `OPERABILITY`, `OTHER`), `FindingStatus`
   (`VERIFIED`, `UNVERIFIED`), `Finding`, `MAX_FINDINGS = 20`.
2. `domain/outcomes.py` — `StageOutcome` : `findings: tuple[Finding, ...]`,
   `omitted_findings: int`, `approved` devient une propriété dérivée. Le tri et
   le plafond sont appliqués à la construction.
3. `domain/errors.py` — `InvalidFindingError(DomainError)`.
4. `domain/quality_gate.py` — `combine_quality_results` est remplacé par
   `failed_checks_outcome()`, qui construit le verdict déterministe.
5. `domain/pipeline.py` — `AgentRole.QUALITY_ANALYST` devient
   `QUALITY_AND_SECURITY`, `AgentRole.REVIEWER` devient `CODE_REVIEWER`. Stages,
   transitions et budget de développement inchangés.
6. `application/ports.py` — `feedback: tuple[Finding, ...]` sur `implement`,
   `quality_review` et `final_review`. Aucune méthode ajoutée ni retirée.
7. `application/process_ticket.py` — court-circuit du gate déterministe,
   accumulation des findings `minor`, corps de PR enrichi.
8. `infrastructure/openrouter_agent.py` — prompts des deux reviewers réécrits,
   parseur strict, un retry correctif, rendu du feedback développeur.
9. `tests/unit/application/fakes.py` — `FakeCodeAgent` typé sur `Finding` ;
   `FakeQualityRunner` inchangé.
10. Tests unitaires : `test_findings.py` (nouveau), `test_outcomes.py`,
    `test_quality_gate.py`, `test_process_ticket.py`, `test_openrouter_agent.py`.
11. `README.md` — section « Agent team ».

## Périmètre — exclu

- Stage `SPECIFYING`, artefact d'AC, validateur de format, port du Spec agent (06e).
- Élargissement du gate déterministe de la factory : `ruff format --check`,
  `lint-imports`, Bandit, pip-audit (07). En 06d le gate reste
  `CommandQualityRunner` tel quel.
- Boucle implémentation ↔ review au-delà de `MAX_DEVELOPMENT_ATTEMPTS`.
- Réécriture du titre ou de la description de la PR au-delà de la section de
  review.
- Artifact de review persisté sur disque, historique, métriques, coût par run.
- Prompt injection, sandbox OS, nouvelle dépendance.
- Jira / Azure DevOps, trigger automatique, idempotence branche/PR (08, 08b).

## Contrat

### Équipe et mandats

| Agent | Stage | Possède | Ne possède pas |
|---|---|---|---|
| Spec *(06e)* | `SPECIFYING` *(06e)* | problème, périmètre, ACs numérotés et testables, unknowns, `needs_clarification` | code, review, définition du DoD du repo cible |
| Coding | `IMPLEMENTING` | implémentation, lecture du repo, exécution locale des checks, réponse au feedback | review de son propre travail, définition des ACs |
| Quality & Security | `QUALITY_CHECK` | pertinence et conformité des tests, assertions significatives vs tautologiques, edge cases, tests skippés/affaiblis, conventions hors ruff, sécurité que les outils ne voient pas (secrets, injection, `eval`/`exec`, subprocess, authz, dépendances) | lint/format et sécurité outillée (déterministes), design, ACs, code |
| Code Review | `FINAL_REVIEW` | **conformité du code à la spec/ACs**, puis design, contrats, compatibilité, gestion d'erreur, scope, couverture du risque, opérabilité. Gate final | lint/format, exécution des tests, duplication des findings Q&S, ACs, code |

Le Code Review peut **référencer** un risque sécurité déjà signalé par Quality &
Security, jamais le re-signaler comme nouveau. Aucun des deux ne fait confiance au
résumé du développeur : la preuve est le code et la sortie des commandes.

### Gate déterministe

`ruff check` et `pytest` (via `CommandQualityRunner`) restent **autoritaires**.
Les agents les consomment, ils ne les remplacent pas. Dans 06d, le gate
court-circuite : un check rouge n'appelle pas l'agent et produit directement un
finding bloquant. `ruff format --check`, `lint-imports`, Bandit et pip-audit
rejoignent le gate en 07 ; les reviewers ne les invoquent pas eux-mêmes.

### Schéma de finding

| Champ | Type | Règle |
|---|---|---|
| `severity` | `blocker` \| `major` \| `minor` | `blocker` et `major` bloquent ; `minor` est rapporté sans bloquer |
| `category` | `spec_conformance` \| `tests` \| `security` \| `design` \| `error_handling` \| `scope` \| `operability` \| `other` | vocabulaire fermé ; `other` est l'échappatoire, pas le défaut |
| `location` | texte non vide | `chemin:ligne` quand le finding pointe du code ; sinon un nom de périmètre (`deterministic-checks`) |
| `message` | texte non vide | ce qui est faux, en une phrase actionnable |
| `evidence` | texte | extrait du diff, sortie de commande ou observation ; **obligatoire** quand `status` est `verified` |
| `ac` | texte, optionnel | identifiant d'AC quand le ticket en énonce, sinon absent |
| `status` | `verified` \| `unverified` | `unverified` = le reviewer n'a pas pu prouver ; ne débloque rien et n'invente pas de preuve |

### Verdict et approbation

Réponse attendue du modèle, et rien d'autre :

```json
{
  "summary": "one-line verdict",
  "findings": [
    {
      "severity": "blocker",
      "category": "tests",
      "location": "tests/test_parser.py:42",
      "message": "The assertion holds for any implementation.",
      "evidence": "- assert result is not None",
      "status": "verified",
      "ac": "AC3"
    }
  ]
}
```

- `approved` n'est **pas** demandé au modèle. S'il est émis, il est ignoré : un
  `approved: true` avec un `blocker` donne un verdict non approuvé.
- `StageOutcome.approved` = aucun finding `blocker` ou `major`.
- Un rejet sans finding bloquant est impossible : c'est ce qui rend le feedback
  actionnable.
- `findings: []` avec un `summary` non vide est une approbation valide.
- Les findings sont triés par sévérité (`blocker`, `major`, `minor`, ordre stable
  à sévérité égale) et plafonnés à `MAX_FINDINGS = 20`. Les écartés sont comptés
  dans `omitted_findings` et jamais perdus silencieusement.

### Séquence d'un stage de review

1. Le gate déterministe tourne. Rouge -> `failed_checks_outcome()`, l'agent n'est
   pas appelé, la transition est un retry.
2. Vert -> l'agent review travaille en lecture seule avec ses outils.
3. La réponse est parsée strictement. Invalide -> **un** retry correctif.
4. Toujours invalide -> `ExternalServiceError` nommant l'erreur de validation : le
   run échoue proprement, la carte reste en To Do, aucun développement n'est
   relancé.

### Retry correctif

Un seul retry, jamais deux. Il est **hors** de la boucle d'outils : il ne consomme
pas `MAX_AGENT_TURNS`, n'expose aucun outil, et reconstruit une conversation
courte (prompt système, message du ticket, réponse invalide, consigne de
correction contenant l'erreur de validation). Le transcript d'outils n'est pas
rejoué : on ne demande qu'une remise au format. Le message d'erreur final ne
contient ni la réponse brute du modèle ni de secret.

### Feedback développeur

`implement` reçoit `tuple[Finding, ...]`, rendu une ligne par finding :

```
- [blocker][tests] tests/test_parser.py:42 — The assertion holds for any implementation. (AC3)
- [major][security] src/io.py:88 — eval() on unvalidated input [unverified]
```

Quand des findings ont été écartés, une dernière ligne indique `+N more`. Un
feedback vide ne produit aucune section. `evidence` n'est pas répétée dans le
feedback : elle sert la review humaine, pas la correction.

### Corps de la PR

La description du ticket est conservée. Quand une review a produit des `minor`,
une section « Automated review » les liste (sévérité, catégorie, localisation,
message, `ac`, preuve quand elle existe). Sans `minor`, le corps reste la
description du ticket. Un run qui ouvre une PR n'a, par construction, ni
`blocker` ni `major`.

## Critères d'acceptation

| # | Critère |
|---|---|
| AC1 | `Finding` refuse un `location` ou un `message` vide, un `severity`/`category`/`status` hors enum, et un `evidence` vide quand `status` est `verified` ; il accepte un `evidence` vide quand `status` est `unverified` ; un `ac` vide devient `None` |
| AC2 | `StageOutcome.approved` est une propriété dérivée : aucun `blocker`/`major` -> `True` ; au moins un -> `False` ; `StageOutcome` n'accepte plus d'argument `approved` |
| AC3 | `StageOutcome` trie les findings par sévérité et n'en garde que 20 ; les écartés sont comptés dans `omitted_findings` ; aucun `blocker`/`major` n'est écarté avant un `minor` ; 21 `minor` -> 20 gardés et `omitted_findings == 1` |
| AC4 | `QUALITY_CHECK` : `run_checks()` faux -> `quality_review` n'est pas appelé (zéro appel), le verdict n'est pas approuvé et le feedback contient exactement le finding déterministe (`severity=blocker`, `location=deterministic-checks`, message nommant les checks) ; `run_checks()` vrai -> `quality_review` est appelé une fois et son verdict fait foi |
| AC5 | Parseur, cas valides : les champs sont mappés sur un `Finding`, une clé inconnue est ignorée, un champ `approved` émis par le modèle est ignoré (`approved: true` + `blocker` -> verdict non approuvé), `findings: []` + `summary` non vide -> verdict approuvé |
| AC6 | Parseur, cas invalides : JSON invalide, racine non-objet, `summary` absent/vide/non-string, `findings` absent ou non-liste, finding non-objet, `severity`/`category`/`status` inconnus, `location`/`message` manquants, `verified` sans `evidence` -> verdict invalide ; l'erreur nomme le champ fautif, sans la réponse brute |
| AC7 | Retry : première réponse invalide -> exactement un appel supplémentaire, sans outils, contenant l'erreur de validation ; deuxième réponse valide -> le stage continue ; deuxième réponse invalide -> `ExternalServiceError` citant l'erreur de validation, aucun troisième appel ; le retry fonctionne avec `max_turns=1` |
| AC8 | Les deux prompts énoncent un mandat disjoint et leurs exclusions : Q&S = tests/ACs, edge cases, conventions hors ruff, sécurité non outillée, sans lint/format ni écriture de code ; Code Review = conformité spec/ACs **d'abord**, puis design/contrats/erreurs/scope/opérabilité, sans lint/format ni exécution des tests ni duplication des findings Q&S ; les deux exigent une preuve et interdisent de se fier au résumé du développeur ; un test de contenu vérifie ces marqueurs |
| AC9 | Feedback : les trois méthodes du port reçoivent `tuple[Finding, ...]` ; chaque finding est rendu `- [severity][category] location — message (AC)`, avec `[unverified]` quand le statut l'est ; les écartés produisent une ligne `+N more` ; un feedback vide ne produit aucune section |
| AC10 | Corps de PR : description du ticket conservée ; des `minor` produisent une section « Automated review » avec sévérité, catégorie, localisation, message, `ac` et preuve ; sans `minor` le corps reste la description ; un run qui ouvre une PR n'a ni `blocker` ni `major` |
| AC11 | La forme du pipeline ne change pas : mêmes stages et mêmes transitions qu'avant 06d, `MAX_DEVELOPMENT_ATTEMPTS` reste 3 ; seuls les noms de rôles changent (`QUALITY_AND_SECURITY`, `CODE_REVIEWER`) et `PipelineStage.role` reste cohérent |
| AC12 | README : section « Agent team » décrivant les 4 agents, l'ordre du pipeline, le gate déterministe autoritaire et court-circuitant, le schéma de finding, l'approbation dérivée, le retry unique et le plafond de 20 findings ; le Spec agent renvoie à 06e |
| AC13 | La suite unitaire reste verte ; `combine_quality_results` est remplacé par `failed_checks_outcome` et la règle « checks rouges -> non approuvé » reste couverte ; aucun test existant n'est affaibli, supprimé ou skippé en dehors de ceux de la fonction remplacée, des tests de l'ancien schéma de verdict (`approved` + findings texte) et de l'ancien feedback (`tuple[str, ...]`), tous listés dans la PR avec leur remplacement |

Chaque AC est couvert par un test `test_spec06d_acN_<behavior>` (convention
`AGENTS.md`) ; le mapping AC -> test est reporté dans la PR.

## Hypothèses

- Un review sans finding est une approbation valide : `findings: []` et un
  `summary` non vide suffisent.
- Le modèle peut encore émettre `approved` (habitude, ou prompt voisin) : le
  parseur l'ignore au lieu d'échouer, pour ne pas transformer un champ obsolète
  en échec de run.
- Le plafond de 20 s'applique à **tout** `StageOutcome`, y compris le verdict
  déterministe.
- Le retry correctif ne rejoue pas le transcript d'outils : il ne corrige que le
  format, pas le jugement.
- Les tests de prompts sont des tests de contenu (marqueurs obligatoires), pas une
  mesure de qualité de prompt ; celle-ci se juge en review et sur le sandbox.
- `ac` reste une chaîne libre en 06d (le ticket n'a pas d'AC numérotés) ; 06e le
  remplace par un identifiant d'AC structuré sans changer le schéma de finding.
- Pas de nouvelle dépendance ; `ruff.toml`, `.importlinter`,
  `.pre-commit-config.yaml` et la CI ne changent pas.

## Limites

- Un review qui produit plus de 20 findings est tronqué ; `omitted_findings` est
  la seule trace des écartés.
- `evidence` n'est pas vérifiée mécaniquement : un reviewer peut citer un extrait
  inexistant. Seul un gate déterministe prouve quelque chose.
- Un verdict valide mais faux (mauvais jugement) n'est pas rattrapé par le retry :
  c'est le rôle de la review humaine avant merge.
- Les `minor` ne bloquent pas, ne sont pas re-testés et ne vivent que dans le
  corps de la PR.
- Le gate de la factory reste `ruff check` + `pytest` ; `ruff format --check`,
  `lint-imports`, Bandit et pip-audit restent côté CI jusqu'à 07. `pytest` tourne
  avec l'interpréteur de la factory, donc le clone cible doit avoir ses
  dépendances dans ce venv (limite existante).
- En 06d le Code Review compare au ticket et à ses ACs éventuels ; l'artefact
  structuré arrive en 06e.
- Un verdict invalide après retry fait échouer le run : la carte reste en To Do,
  aucun nouveau cycle de développement n'est lancé.

## Plan de livraison

Une branche `feat/06d-agent-team`, une PR, commits verts successifs :

1. `domain/findings.py`, `StageOutcome` dérivé, tri et plafond (AC1-AC3).
2. `failed_checks_outcome` + court-circuit du gate dans le use case (AC4).
3. Parseur strict et retry correctif (AC5-AC7).
4. Prompts et mandats des deux reviewers (AC8).
5. Rendu du feedback et section de review dans la PR (AC9-AC10).
6. Noms de rôles, README, mapping AC -> test et rapport de mutation (AC11-AC13).

Chaque commit laisse `ruff check`, `ruff format --check`, `lint-imports` et
`pytest tests/unit` verts.

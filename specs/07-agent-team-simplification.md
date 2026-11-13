# Spec 07 — `agent-team-simplification` (Étape 7)

> Les specs sont numérotées dans l'ordre d'exécution des étapes : `specs/NN-<task>.md`.
> Cette spec remplace les parties « deux reviewers » de 06d. 06d reste le compte
> rendu de l'état livré ; 07 est la référence pour la suite.

## Contexte

- 06d a livré quatre agents : Spec (06e), Coding, Quality & Security et Code
  Review. Les deux reviewers ont des mandats différents sur le papier, mais la
  même forme : lecture seule, même schéma de finding, même retry correctif, même
  boucle de feedback.
- Le gate déterministe couvre déjà le lint et les tests outillés. Pour le MVP, un
  second stage de review coûte un appel LLM, un stage, une méthode de port et un
  second endroit où accumuler les findings `minor`, sans séparation assez nette
  pour le justifier.
- Décision : passer à **trois agents** — Spec, Coding, Code Review. La checklist
  Quality & Security est intégrée au Code Review, pas supprimée.
- 07 livre la consolidation 4 → 3 et le modèle de policies pour les agents
  actifs (Coding et Code Review). 06e ajoutera le stage `SPECIFYING`, la policy
  Spec, l'artefact d'ACs et son validateur.
- Le repo cible n'est **pas** lu : ses fichiers de règles sont personnels et
  mono-agent. Les policies sont factory-owned, statiques et versionnées avec la
  factory. Aucun digest de repo cible n'est introduit.
- Le gate de la factory reste volontairement minimal : `ruff check .` puis
  `pytest`, exécuté dans le clone cible avec l'interpréteur du venv de la
  factory. Les checks plus riches sont reportés.

## Objectifs

1. Cible à trois agents : Spec, Coding, Code Review.
2. Un seul stage de review et un seul appel reviewer par tentative.
3. Des policies factory-owned, explicites, testables et sélectionnées par rôle.
4. Préserver les contrats 06d : findings structurés, approbation dérivée,
   retry correctif unique, findings `minor` dans la PR, court-circuit du gate.
5. Garder le gate `ruff check` + `pytest`, sans nouvelle dépendance.
6. Laisser un point d'extension propre pour 06e, sans code mort en 07.

## Périmètre — inclus

1. `ai_factory/domain/pipeline.py`
   - `AgentRole` : `DEVELOPER`, `CODE_REVIEWER`.
   - `PipelineStage` : `NEW`, `IMPLEMENTING`, `REVIEW`,
     `PULL_REQUEST_OPENED`, `FAILED`.
   - `PipelineStage.role` : `IMPLEMENTING` → `DEVELOPER`,
     `REVIEW` → `CODE_REVIEWER`.
   - `PipelineRun.development_completed()` : `IMPLEMENTING` → `REVIEW`.
   - `PipelineRun.record_review_outcome(approved)` : `REVIEW` →
     `PULL_REQUEST_OPENED` ou retry/`FAILED`.
   - Suppression de `record_quality_outcome` et de `QUALITY_CHECK`.
   - `MAX_DEVELOPMENT_ATTEMPTS` reste `3`.

2. `ai_factory/application/ports.py`
   - `CodeAgent` expose `implement(ticket, feedback)` et
     `review(ticket, feedback) -> StageOutcome`.
   - Suppression de `quality_review` et `final_review`.

3. `ai_factory/application/process_ticket.py`
   - Un seul branchement `REVIEW` : le gate déterministe tourne d'abord, puis
     `review` est appelé si le gate est vert.
   - Le verdict du gate ou du reviewer passe par
     `record_review_outcome(verdict.approved)`.
   - Les findings `minor` ne sont accumulés qu'à un seul endroit et sont remis à
     zéro au début de chaque nouvelle tentative d'implémentation.

4. `ai_factory/domain/agent_policies.py` — nouveau module
   - `AgentPolicy` immuable : `role`, `title`, `mission`, `owns`,
     `does_not_own`, `rules`, `output_contract`.
   - `render()` déterministe, sections dans un ordre fixe.
   - `policy_for(role)` retourne la policy du rôle.
   - `DEVELOPER_POLICY` et `CODE_REVIEW_POLICY` pour les deux agents actifs.
   - Le contrat de sortie de review (schéma JSON + règles de preuve) est la
     source unique utilisée par la policy et par le retry correctif.
   - La policy Spec est décrite dans cette spec mais **implémentée en 06e**,
     pour éviter du code inutilisé entre 07 et 06e.

5. `ai_factory/infrastructure/openrouter_agent.py`
   - `implement()` utilise `DEVELOPER_POLICY.render()`.
   - `review()` utilise `CODE_REVIEW_POLICY.render()`.
   - Suppression de `QUALITY_PROMPT` et de `quality_review` ; `final_review`
     devient `review`.
   - Les listes d'outils restent inchangées : developer avec `write_file`,
     reviewer en lecture seule.
   - Le parseur strict, le retry correctif unique et le rendu du feedback
     restent inchangés.

6. Tests unitaires
   - Adapter les tests du pipeline, du use case, des fakes et de l'adapter.
   - Remplacer les tests spécifiques Quality & Security par des tests
     single-review équivalents.
   - Ajouter les tests de policies et les tests de non-régression du gate.

7. `README.md`
   - Trois agents, un seul stage Code Review, checklist Q&S intégrée.
   - Aucun digest du repo cible.
   - Gate `ruff check` + `pytest`.
   - 06e pour le Spec agent.

## Périmètre — exclu

- Stage `SPECIFYING`, artefact d'ACs, validateur de format, policy Spec
  implémentée, port du Spec agent (06e).
- Lecture de `AGENTS.md`, `ARCHITECTURE.md`, `ruff.toml` ou des workflows CI du
  repo cible ; tout digest de repo cible.
- `ruff format --check`, `lint-imports`, Bandit, pip-audit dans le gate.
- Preuve structurée des commandes, `CheckReport`, changement du port
  `QualityRunner.run_checks() -> bool`.
- Modèle OpenRouter par agent.
- Nouveau stage, nouvelle transition ou changement de
  `MAX_DEVELOPMENT_ATTEMPTS`.
- Nouvelle dépendance, changement de configuration, changement de CI.
- Modification des specs historiques `01`, `02` et `06d` : 07 documente ce
  qu'elle remplace, sans réécrire l'historique.

## Contrat

### Équipe et stages

| Agent | Stage après 07 | Mandat |
|---|---|---|
| Spec *(06e)* | `SPECIFYING` *(06e)* | transforme le ticket en problème, périmètre, ACs numérotés et testables, unknowns ; `needs_clarification` si ambigu |
| Coding | `IMPLEMENTING` | implémente la spec/les ACs, écrit les tests, répond au feedback, lance les checks |
| Code Review | `REVIEW` | gate final : conformité spec/ACs, tests, sécurité, design/architecture, erreurs, scope, opérabilité, clean code |

Séquence après 07 :

```text
NEW -> IMPLEMENTING -> REVIEW -> PULL_REQUEST_OPENED
                              \-> IMPLEMENTING (retry) -> FAILED (budget épuisé)
```

Séquence après 06e :

```text
NEW -> SPECIFYING -> IMPLEMENTING -> REVIEW -> PULL_REQUEST_OPENED
```

### Modèle de policy

`AgentPolicy` est un value object pur, sans I/O. `render()` produit un prompt
système stable avec les sections suivantes, dans cet ordre :

1. `ROLE`
2. `MISSION`
3. `OWNS`
4. `DOES NOT OWN`
5. `RULES`
6. `OUTPUT CONTRACT`

`policy_for(role)` est la seule façon de sélectionner une policy. Chaque
`AgentRole` doit avoir exactement une policy ; un rôle manquant est une erreur de
programmation, pas un cas d'exécution.

Le texte des policies est **factory-owned**. Il n'est jamais lu depuis le repo
cible, n'est jamais exécuté comme une commande, et ne contient ni secret ni
donnée client.

### Policy Coding — règles

- Relire la spec/les ACs et reformuler ce qui est attendu ; si ambigu, s'arrêter
  au lieu de deviner.
- Chercher les patterns existants avant d'écrire ; faire le plus petit
  changement qui satisfait la demande.
- Ne pas réécrire un fichier entier ; préserver la logique existante et les
  valeurs calibrées.
- Écrire ou mettre à jour les tests : ils assertent le comportement, pas
  l'implémentation. Ne jamais supprimer, skipper ou affaiblir un test existant.
- Respecter `ARCHITECTURE.md` : dépendances vers l'intérieur, domaine pur,
  ports pour l'I/O, pas de SDK dans l'application, composition root pour le
  câblage.
- Imports en haut du fichier, type hints, docstrings, pas de magic numbers,
  nesting ≤ 3, pas de code mort, pas de duplication inutile.
- Aucune nouvelle dépendance sans validation ; versions pinnées.
- Jamais de secret, token ou credential dans le code ; valider les entrées non
  fiables à la frontière ; ne jamais logger de secret ou de donnée personnelle.
- Échouer bruyamment : pas de `except:` nu, pas de `except Exception: pass`, pas
  d'exception avalée ; attraper le type spécifique.
- Pas de suppression (`# noqa`, `# type: ignore`, `# pragma: no cover`) sans
  justification et validation.
- Ne pas toucher aux fichiers human-owned (`ruff.toml`, `.importlinter`,
  `.pre-commit-config.yaml`, CI, `AGENTS.md`, `ARCHITECTURE.md`) ; ne pas
  commit/push : la factory s'en charge.
- Lancer `ruff check .` et `pytest` dans le clone cible, avec le venv de la
  factory, et rapporter les résultats réels ; ne jamais inventer une commande ou
  une sortie.
- Handoff : résumé du changement, tests ajoutés, commandes exécutées,
  hypothèses et hors-scope.

La policy Coding ne possède pas : la review de son propre travail, la définition
des ACs, la modification des règles de la factory.

### Policy Code Review — règles

La review suit cet ordre :

1. **Conformité spec/ACs** : le code fait-il exactement ce qui est demandé ?
   Comportement manquant, extra ou divergent.
2. **Tests** : couvrent-ils les ACs ? Assertions réelles ou tautologiques ?
   Edge cases ? Tests skippés, affaiblis, supprimés ? Régression ?
3. **Sécurité** : secrets dans le diff, injection, `eval`/`exec`, subprocess non
   sûr, autorisation manquante, dépendances, logs de données personnelles.
4. **Design/architecture** : couches, ports, contrats, couplage, compatibilité,
   frontières.
5. **Gestion d'erreur** : modes de défaillance, exceptions spécifiques, pas
   d'avalement.
6. **Scope** : pas de refactor opportuniste, changement minimal.
7. **Opérabilité** : configuration, logs sans secrets, rollback,
   documentation/README.
8. **Clean code** : noms, magic values, duplication, nesting, type hints,
   docstrings, code mort.

Règles :

- Lecture seule : ne jamais modifier le code ou les tests, ne pas corriger les
  findings soi-même.
- Ne pas relancer lint/format ni toute la suite de tests : le gate déterministe
  est autoritaire. Des inspections read-only restent possibles.
- Chaque finding a une preuve : extrait de diff, code ou sortie de commande.
  Sans preuve → `unverified`, jamais de preuve inventée.
- Ne pas faire confiance au résumé du développeur : lire le code.
- Ne pas redéfinir les ACs ; une ambiguïté est un finding.
- Une seule review, un seul JSON, pas de duplication de findings.
- `blocker`/`major` bloquent ; `minor` est rapporté dans la PR.
- L'approbation est dérivée des findings, jamais lue dans la réponse du modèle.
- Un verdict invalide déclenche un seul retry correctif, puis un échec propre.

La policy Code Review intègre la checklist Quality & Security. Elle ne possède
pas : le lint/format outillé, l'exécution de la suite de tests complète, la
définition des ACs, l'écriture du code.

### Policy Spec — spécifiée ici, livrée en 06e

- Reformuler le problème à partir du ticket, en citant les phrases du ticket.
- Définir le périmètre inclus et exclu.
- Produire des ACs **numérotés, testables, observables et traçables** à une
  phrase du ticket.
- Déclarer les hypothèses et les unknowns.
- Pas d'invention : si le ticket est ambigu ou contradictoire →
  `needs_clarification`, arrêt.
- Ne pas coder, ne pas review, ne pas choisir l'implémentation au-delà du
  nécessaire.
- Produire un artefact déterministe, borné, validé avant handoff.
- Ne mettre ni secret ni donnée personnelle dans l'artefact.

Cette policy n'est pas implémentée en 07 : 06e ajoute `AgentRole.SPEC_WRITER`,
`PipelineStage.SPECIFYING`, l'artefact d'ACs et son validateur. 07 doit laisser
cet ajout possible sans changer le chemin `IMPLEMENTING -> REVIEW`.

### Gate déterministe

- `ruff check .` puis `pytest` dans le clone cible.
- `pytest` est lancé avec `sys.executable -m pytest -q`, donc l'interpréteur du
  venv de la factory ; le clone cible n'a pas besoin de son propre venv.
- Le CWD des deux commandes est le clone cible, jamais la racine de la factory.
- `pytest` est sauté uniquement quand le clone n'a pas de dossier `tests/`.
- Un check rouge produit `failed_checks_outcome()` : un seul finding
  `blocker`, `location=deterministic-checks`, preuve = le gate a échoué.
- Un check rouge ne déclenche **aucun** appel au Code Review agent ; le feedback
  repart directement vers une nouvelle tentative d'implémentation.
- Aucun autre check n'est ajouté en 07.

### Pipeline et retry

- Le gate et la review partagent le même stage `REVIEW` et la même transition
  `record_review_outcome`.
- Une tentative d'implémentation est suivie d'au plus une review agent.
- `MAX_DEVELOPMENT_ATTEMPTS` reste `3`.
- Un rejet du gate ou du reviewer incrémente la tentative et renvoie vers
  `IMPLEMENTING`, ou termine en `FAILED` quand le budget est épuisé.
- Les `minor` d'une tentative rejetée ne sont pas publiés ; ils sont remis à
  zéro au début de la tentative suivante.
- `findings.py`, `outcomes.py` et `quality_gate.py` ne changent pas de
  comportement : schéma, tri, plafond, approbation dérivée et finding
  déterministe restent ceux de 06d.

## Critères d'acceptation

| # | Critère |
|---|---|
| AC1 | Après 07, `AgentRole` contient exactement `DEVELOPER` et `CODE_REVIEWER` ; `PipelineStage` contient `NEW`, `IMPLEMENTING`, `REVIEW`, `PULL_REQUEST_OPENED`, `FAILED` ; `REVIEW` est mappé à `CODE_REVIEWER` et `IMPLEMENTING` à `DEVELOPER` ; `MAX_DEVELOPMENT_ATTEMPTS` reste `3` ; `SPECIFYING`/`SPEC_WRITER` ne sont pas ajoutés en 07. |
| AC2 | `development_completed()` passe de `IMPLEMENTING` à `REVIEW` ; `record_review_outcome(True)` passe à `PULL_REQUEST_OPENED` ; `record_review_outcome(False)` renvoie à `IMPLEMENTING` avec une tentative de plus, ou à `FAILED` après trois tentatives ; `record_quality_outcome` n'existe plus ; un appel depuis un mauvais stage lève `InvalidStageTransitionError`. |
| AC3 | Dans `REVIEW`, `ProcessTicket` lance le gate d'abord : gate rouge → `review` n'est pas appelé (zéro appel) et le finding déterministe est renvoyé au développeur ; gate vert → `review` est appelé exactement une fois et son verdict pilote `record_review_outcome`. |
| AC4 | Le port `CodeAgent` expose `implement(ticket, feedback)` et `review(ticket, feedback) -> StageOutcome` ; `quality_review` et `final_review` sont supprimés ; les fakes et les tests sont adaptés ; aucun autre changement de port. |
| AC5 | `AgentPolicy` est un value object immuable avec `role`, `title`, `mission`, `owns`, `does_not_own`, `rules`, `output_contract` ; `render()` est déterministe et produit les six sections dans l'ordre fixe ; `policy_for(role)` retourne la policy de chaque `AgentRole` ; le module ne fait aucune I/O et ne lit aucun fichier du repo cible. |
| AC6 | La policy Coding contient les règles validées : implémentation dans le clone, scope minimal, préservation de l'existant, tests de comportement sans affaiblissement, respect de l'architecture, imports en haut, type hints, docstrings, pas de magic values, nesting ≤ 3, pas de code mort, pas de nouvelle dépendance, pas de secret/PII, échec bruyant, pas de suppression, fichiers human-owned intouchés, `ruff check .` + `pytest`, résumé de handoff. Elle ne possède ni la review ni la définition des ACs. |
| AC7 | La policy Code Review contient la checklist ordonnée : conformité ACs d'abord, puis tests, sécurité, design/architecture, gestion d'erreur, scope, opérabilité, clean code. Elle est read-only, ne relance pas lint/format ni la suite complète, traite le gate comme autoritaire, exige une preuve, ne fait pas confiance au résumé du développeur, ne redéfinit pas les ACs, produit un seul JSON et une approbation dérivée. La checklist Q&S est intégrée et les findings ne sont pas dupliqués. |
| AC8 | `OpenRouterAgent.implement` utilise `DEVELOPER_POLICY.render()` et `review` utilise `CODE_REVIEW_POLICY.render()` ; le prompt système ne contient aucun contenu du repo cible ni digest ; le developer garde `write_file`, le reviewer reste en lecture seule ; le parseur strict et le retry correctif unique sont inchangés. |
| AC9 | Le gate reste `ruff check .` puis `pytest` ; `pytest` utilise `sys.executable -m pytest -q` dans le clone cible et n'est sauté que sans dossier `tests/` ; aucun `ruff format`, `lint-imports`, Bandit, pip-audit, `CheckReport` ou changement de port n'est ajouté ; un gate rouge court-circuite le reviewer. |
| AC10 | Les contrats 06d restent inchangés : schéma `Finding`, tri et plafond, approbation dérivée de `StageOutcome`, feedback développeur, findings `minor` dans le corps de PR et finding déterministe. `findings.py`, `outcomes.py` et `quality_gate.py` ne changent pas de comportement. |
| AC11 | Le README décrit trois agents, un seul stage Code Review avec la checklist Q&S intégrée, l'absence de digest du repo cible, le gate `ruff check` + `pytest`, et le fait que 06e ajoute le Spec agent. Il ne prétend plus que 07 enrichit le gate ou lit les fichiers du repo cible. |
| AC12 | La suite unitaire reste verte, la couverture de lignes reste ≥ 90 %, la sonde mutation sur le diff ne laisse aucun survivant actionnel, aucun test existant n'est supprimé ou affaibli sans remplacement équivalent listé dans la PR, aucune dépendance n'est ajoutée, et la configuration/CI ne changent pas. |

Chaque AC est couvert par au moins un test nommé `test_spec07_acN_<behavior>`.
Le mapping AC → test est reporté dans la PR.

### Remplacements de tests 06d

Les tests suivants sont superseded par la consolidation ; leurs remplacements
sont listés ici pour ne pas les supprimer silencieusement :

| Test 06d | Remplacement 07 |
|---|---|
| `test_spec06d_ac4_failed_checks_skip_the_quality_agent` | `test_spec07_ac3_red_gate_skips_the_review_agent` |
| `test_spec06d_ac8_quality_prompt_owns_tests_and_security` | `test_spec07_ac7_review_policy_covers_quality_security` |
| `test_spec06d_ac8_review_prompt_checks_conformance_first` | `test_spec07_ac7_review_policy_checks_conformance_first` |
| `test_spec06d_ac8_both_prompts_require_evidence` | `test_spec07_ac7_review_policy_requires_evidence` |
| `test_spec06d_ac11_pipeline_shape_is_unchanged` | `test_spec07_ac1_pipeline_shape_and_roles` |
| `test_spec06d_ac12_readme_documents_the_agent_team` | `test_spec07_ac11_readme_documents_three_agents` |
| Tests Q&S de `test_process_ticket.py` | Tests single-review équivalents (ordre des appels, feedback, retry, minors) |
| Tests Q&S de `test_openrouter_agent.py` | Tests single-review équivalents (tools read-only, policy, parseur, retry) |

## Hypothèses

- Un seul reviewer suffit pour le MVP ; la review humaine et la CI restent les
  garde-fous finaux. Un re-split Q&S/Code Review pourra être proposé plus tard
  si les runs montrent un angle mort, dans une spec séparée.
- Le gate reste `ruff check` + `pytest` ; les checks plus riches sont reportés.
- Le modèle OpenRouter reste global ; un modèle par agent est hors scope.
- Le clone cible doit avoir ses dépendances dans le venv de la factory, comme
  aujourd'hui.
- Les specs `01`, `02` et `06d` restent historiques ; 07 est la référence pour
  le pipeline et les policies après consolidation.
- La policy Spec est rédigée maintenant pour validation, mais son code et son
  stage arrivent en 06e.

## Limites

- Un reviewer unique est moins spécialisé que deux ; la checklist compense, mais
  ne garantit pas la même profondeur qu'un reviewer dédié.
- Aucune preuve structurée n'est attachée aux findings : la preuve reste du texte
  fourni par le modèle et n'est pas vérifiée mécaniquement.
- Le gate ne vérifie pas les dépendances du repo cible ; si elles manquent dans
  le venv de la factory, `pytest` échoue.
- 07 ne livre pas encore le Spec agent : à la fin de 07, deux agents sont
  actifs ; 06e complète l'équipe à trois.
- Le probe mutation peut voir ses lignes changer ; l'allowlist sera revalidée
  avec validation humaine si une entrée doit être mise à jour.

## Plan de livraison

Branche `feat/07-agent-team-simplification`, une PR, commits verts successifs :

1. `domain/pipeline.py` + tests : rôles, stages, transitions et budget
   (AC1-AC2).
2. `application/ports.py`, `application/process_ticket.py`, fakes et tests :
   port `review`, gate puis review, retry unique (AC3-AC4).
3. `domain/agent_policies.py` + tests : modèle, rendu déterministe, policies
   Coding et Code Review (AC5-AC7).
4. `infrastructure/openrouter_agent.py` + tests : sélection par policy, tools,
   parseur et retry (AC8).
5. README, tests de non-régression du gate et de documentation (AC9-AC11).
6. Vérifications finales : suite unitaire, couverture, mutation, mapping AC →
   test, rapport de PR (AC12).

Chaque commit laisse `ruff check`, `ruff format --check`, `lint-imports` et
`pytest tests/unit` verts. Aucun commit direct sur `main`.

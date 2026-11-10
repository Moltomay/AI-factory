# Spec 06b — `trello-lifecycle` (Étape 6b)

> Les specs sont numérotées dans l'ordre d'exécution des étapes : `specs/NN-<task>.md`.

## Contexte

- La spec 06 est éclatée en 5 sous-parties : 06a sécurité runtime, 06b cycle de vie Trello, 06c review JSON retry, 06d QA vs Reviewer, 06e spec agent. 06a est livrée.
- Aujourd'hui `run` traite la première carte de `TRELLO_LIST_ID`, ouvre la PR et poste un commentaire. La carte reste dans la liste To Do : le board ne reflète ni la revue en cours, ni le merge, ni l'abandon.
- `ProcessTicket` nomme ses branches `factory/{ticket_id}` (`BRANCH_NAME_TEMPLATE`), ce qui donne une clé stable pour retrouver la PR d'une carte.
- GitHub `GET /repos/{repo}/pulls?head={owner}:{branch}&state=all&base={base}` retrouve les PR d'une branche supprimée (vérifié sur les PR #9 et #11 du dépôt) : pas besoin de fallback. Le filtre `base` évite de confondre deux PR homonymes visant des branches de base différentes.
- Livraison en une branche + une PR, plusieurs commits verts. Pilot de mesure décrit plus bas ; ses règles RED-first et mutation ont depuis été promues dans `AGENTS.md` §4 et outillées dans `ci.yml`.

## Objectifs

1. Le board reflète le cycle de vie : To Do -> In Review -> Done ou retour en To Do.
2. `run` ne détecte jamais un merge : il ne fait que publier et déplacer en In Review.
3. Une commande `reconcile` séparée, ré-exécutable, applique le sort des PR.
4. Aucune nouvelle dépendance runtime, aucune base de données, aucun webhook.
5. Le comportement est testé sur des ports factices, sans écriture réelle sur Trello.

## Périmètre — inclus

1. `interfaces/config.py` — `TRELLO_REVIEW_LIST_ID` et `TRELLO_DONE_LIST_ID` rejoignent `REQUIRED_VARIABLES`. Les trois identifiants de liste doivent être distincts deux à deux ; sinon `ConfigurationError` (message listant des noms, jamais des valeurs). `FactoryConfig` gagne les deux champs.
2. `application/ports.py` — enums `TicketStatus` (`TODO`, `IN_REVIEW`, `DONE`) et `PullRequestState` (`OPEN`, `MERGED`, `CLOSED`, `NOT_FOUND`). `TicketSource` gagne `list_by_status` et `set_status`. `VersionControl` gagne `pull_request_state` et `delete_branch`.
3. `infrastructure/trello.py` — `TrelloLists` (trois identifiants), `set_status` (`PUT /cards/{id}` avec `idList`), `list_by_status`. `TrelloBoard` reçoit `TrelloLists` au lieu d'un `list_id` unique.
4. `infrastructure/github.py` — `pull_request_state(branch_name)` filtré sur la branche de base configurée. Plusieurs PR sur la même branche : priorité `MERGED` > `OPEN` > `CLOSED`. `delete_branch(branch_name)` supprime la branche distante et réussit si elle est déjà absente.
5. `application/process_ticket.py` — sur succès : PR ouverte -> `set_status(IN_REVIEW)` -> commentaire avec l'URL. Sur échec : comportement inchangé (commentaire d'échec, pas de déplacement).
6. `application/reconcile_tickets.py` — nouveau cas d'usage `ReconcileTickets` : parcourt les cartes In Review, applique la transition, agrège le résultat.
7. `interfaces/cli.py` — sous-commande `reconcile`, distincte de `run`. Exit `0` succès, `1` si au moins une PR est introuvable, `2` erreur de configuration.
8. `interfaces/composition.py` — `build_trello_lists`, `build_reconcile_tickets`, câblage du `TrelloBoard` avec les trois listes.
9. `tests/unit/application/fakes.py` — `FakeTicketSource` gagne trois listes et les deux méthodes ; `FakeVersionControl` gagne `pull_request_state`.
10. `README.md` — variables, cycle de vie, `reconcile`, exit codes, limite de ré-exécution.
11. `specs/04-cli.md` — ajout des deux variables à la liste des variables requises (amendement autorisé).

## Périmètre — exclu

- Webhook Trello, polling, tâche planifiée.
- Détection de merge ou de fermeture dans `run`.
- Base de données, historique, métriques.
- Nouvelle dépendance runtime.
- Écriture réelle sur le board Trello dans les tests (les tests d'intégration Trello restent en lecture seule).
- Reprise après crash, verrou de concurrence, idempotence de `POST /pulls` (spec 08).

## Contrat

### Cycle de vie

1. Carte dans To Do (`TRELLO_LIST_ID`).
2. `run` : pipeline -> PR ouverte -> carte en In Review (`TRELLO_REVIEW_LIST_ID`) -> commentaire avec l'URL.
3. `reconcile`, sur chaque carte de In Review :
   - `MERGED` -> carte en Done (`TRELLO_DONE_LIST_ID`), **aucun commentaire** ;
   - `CLOSED` -> suppression de la branche distante, carte en To Do, **puis** commentaire mentionnant la branche ;
   - `OPEN` -> aucune action ;
   - `NOT_FOUND` -> carte ignorée, les autres cartes restent traitées, sortie `1`.

### Ordre des opérations

- `run` déplace **avant** de commenter : un échec de commentaire ne laisse pas une carte en To Do avec un commentaire trompeur.
- `reconcile` supprime la branche **avant** de déplacer sur `CLOSED` : une carte revenue en To Do est immédiatement rejouable, sans collision de branche distante.
- `reconcile` déplace **avant** de commenter sur `CLOSED`, pour la même raison qu'en `run`.

### Idempotence

`reconcile` ne scanne que In Review. Une carte déplacée en Done ou en To Do n'est plus vue au passage suivant : deux exécutions consécutives sans changement d'état ne produisent ni déplacement ni commentaire. La suppression de branche est elle-même idempotente : une branche déjà absente n'est pas une erreur.

## Critères d'acceptation

| # | Critère |
|---|---|
| AC1 | Config : les deux nouvelles variables sont requises ; absentes ou vides -> `ConfigurationError` nommant les variables ; trois identifiants identiques ou deux identiques -> `ConfigurationError` |
| AC2 | Trello : `set_status` envoie `idList` de la liste correspondant au statut ; erreur HTTP -> `ExternalServiceError` dont le message ne contient ni clé ni token |
| AC3 | Trello : `list_by_status(IN_REVIEW)` lit la liste de revue et retourne les cartes sous forme de `Ticket` |
| AC4 | GitHub : `pull_request_state` interroge la branche de base configurée, mappe `OPEN`, `MERGED`, `CLOSED`, `NOT_FOUND` ; plusieurs PR -> `MERGED` prioritaire, puis `OPEN`, puis `CLOSED` |
| AC5 | `run` sur succès : `set_status(IN_REVIEW)` appelé avant `report_result`, puis commentaire avec l'URL ; sur échec : commentaire d'échec et aucun déplacement |
| AC6 | `reconcile` : carte In Review + PR `MERGED` -> Done, aucun commentaire |
| AC7 | `reconcile` : carte In Review + PR `CLOSED` -> branche distante supprimée, To Do puis commentaire contenant le nom de la branche |
| AC8 | `reconcile` : carte In Review + PR `OPEN` -> aucun déplacement, aucun commentaire |
| AC9 | `reconcile` : PR `NOT_FOUND` -> carte ignorée, les autres traitées, résultat agrégé marque l'échec, CLI sort `1` |
| AC10 | `reconcile` est idempotent : deux exécutions sans changement d'état ne produisent aucun déplacement ni commentaire |
| AC11 | CLI : `run` et `reconcile` sont deux sous-commandes distinctes ; `reconcile` n'est pas exécuté par `run` ; erreur de config -> `2` |
| AC12 | README : documente les deux variables, le cycle de vie, `reconcile`, les exit codes et la limite de ré-exécution |
| AC13 | `reconcile` : suppression idempotente de la branche distante (branche déjà absente = succès) ; échec de suppression -> carte laissée en In Review, les autres cartes traitées, résultat agrégé marque l'échec, CLI sort `1` |

Chaque AC est couvert par un test `test_spec06b_acN_<behavior>` (convention `AGENTS.md`) ; le mapping AC -> test et le rapport des sondes sont reportés dans la PR.

## Pilot — règles de test, puis adoption

Ce pilot a mesuré si les règles méritent d'entrer dans `AGENTS.md` §4. Les règles P1 (RED first) et P4 (mutation) y sont désormais promues ; P2, P3 et P5 restent des consignes de revue.

- **P0** — Un AC = une phrase observable, approuvée avant le code.
- **P1** — Test d'abord pour chaque AC de comportement nouveau ; RED classifié dans la PR (`missing API`, `wrong behavior`, `missing documentation`). Un rouge sur une assertion factice ne compte pas.
- **P2** — Assertions sur le contrat observable uniquement : valeur retournée, exception, octets/fichiers produits, appel à un port. Interdit : attribut privé, ordre d'appels internes, position dans `argv`, encodage interne exact, et valeur attendue dérivée d'un symbole de l'implémentation.
- **P3** — Tests de non-régression déclarés, verts dès le départ, jamais affaiblis.
- **P4** — Mutation probe (cosmic-ray, `cosmic-ray.toml`, modules du diff) après le vert. Chaque survivant est trié `actionnable` (assertion manquante) ou `équivalent` (justifié en une ligne). Aucun survivant actionnable ne passe en revue. Le score n'est pas un objectif ; la liste des diffs est le livrable.
- **P5** — Refactor probe par AC : un changement à comportement constant, tests verts. Un test rouge est un miroir à reframer avant la revue.

### Mesures reportées dans la PR, par tranche

- survivants actionnables / équivalents ;
- refactor probes verts / rouges, et tests reframés ;
- findings par source : RED, mutation, refactor, revue, CI ;
- coût des sondes (secondes) rapporté au temps de la tranche ;
- faux positifs des sondes (sonde rouge sur un test finalement correct).

### Critère d'adoption, figé avant le code

Un mécanisme est promu dans `AGENTS.md` s'il produit **au moins un finding actionnable que la revue aurait laissé passer**. Le coût et les faux positifs sont mesurés et discutés à la fin, sans veto préalable.

### Artefacts du pilot et du gate

- `requirements-mutation.txt` : `cosmic-ray==8.7.0`, installé localement et par le job CI de mutation.
- `cosmic-ray.toml` : modules du diff uniquement, via `cr-filter-git` contre `origin/main` ; `python -X utf8 -B` pour l'encodage et le cache.
- `mutation-allowlist.toml` : allowlist human-owned des survivants sémantiquement équivalents, identifiés par fichier, ligne, opérateur et occurrence, avec une justification obligatoire.
- `ai_factory/interfaces/mutation_gate.py` : lit la base sqlite de cosmic-ray et échoue sur tout survivant actionnable, tout résultat invalide et toute mutation non exécutée ; les mutants filtrés (`SKIPPED`) sont ignorés.
- Job CI `Mutation testing` : initialise, filtre sur le diff, exécute puis applique le gate. Le job est la porte faisant autorité ; la règle locale d'`AGENTS.md` §4 impose la même sonde avant de déclarer une tâche terminée.

### Résultat du pilot

Mesures des sondes, par AC. Les survivants sont comptés par module de tranche :
la ligne qui porte le coût porte aussi le total de la tranche.

| AC | RED | Survivants actionnables | Survivants équivalents | Refactor probe | Coût (s) |
|---|---|---|---|---|---|
| AC1 | 3 échecs (1 `missing API`, 2 `wrong behavior`) | 0 | 3 | vert | 98,3 (T1) |
| AC2 | erreur de collecte (`missing API`) | 0 | 1 | vert | — |
| AC3 | erreur de collecte (`missing API`) | 0 | 0 | vert | — |
| AC4 | 7 échecs (`missing API`) | 1 | 4 | vert | 96,4 (T2, 2 runs) |
| AC5 | 2 échecs (`wrong behavior`) | 0 | 5 | vert | 42,5 (T3) |
| AC6 | erreur de collecte (`missing API`) | 0 | 4 | vert | 237,4 (T4, 2 runs) |
| AC7 | — | 0 | 0 | vert | — |
| AC8 | — | 0 | 0 | vert | — |
| AC9 | test corrigé (le fake répondait `OPEN` au lieu de `NOT_FOUND`) | 0 | 0 | vert | — |
| AC10 | — | 0 | 0 | vert | — |
| AC11 | erreur de collecte (`missing API`) | 3 familles (8 mutants) | 1 | vert | — |
| AC12 | n/a (documentation) | 0 | 0 | n/a | — |

Détail des sondes :

| Tranche | Modules | Mutants | Tués | Actionnables | Équivalents | Coût (s) |
|---|---|---|---|---|---|---|
| T1 | `trello.py`, `config.py` | 97 | 93 | 0 | 4 | 98,3 |
| T2, 1er run | `github.py` | 47 | 41 | 1 (`parents=True`) | 4 | 46,2 |
| T2, après test | `github.py` | 47 | 41 | 0 | 4 | 50,2 |
| T3 | `process_ticket.py` | 47 | 42 | 0 | 5 | 42,5 |
| T4, 1er run | `reconcile_tickets.py`, `cli.py` | 70 | 57 | 3 familles (8 mutants) | 5 | 121,0 |
| T4, après reframe | `reconcile_tickets.py`, `cli.py` | 70 | 65 | 0 | 5 | 116,4 |
| Finale, diff complet | `ai_factory` filtré vs `main` | 670 (76 exécutés) | 67 | 0 | 9 | 152,0 |

Total : 261 mutants distincts sur les probes ciblées (474,6 s). La probe finale
sur le diff complet (`cosmic-ray.toml`) exécute 76 mutants des lignes 06b, en tue
67 et laisse 9 survivants équivalents (152,0 s), soit 626,6 s de sondes au total.
0 faux positif (aucune sonde rouge sur un test finalement correct).

Survivants équivalents, justifiés :

- `@dataclass(frozen=True)` -> `False` (`TrelloLists`, `FactoryConfig`,
  `ProcessTicketResult`, `ReconcileResult`) : aucune AC ne définit la mutabilité.
- `is` -> `==` sur des membres d'enum (`PullRequestState`, `PipelineStage`) :
  les enums sont des singletons, l'égalité par défaut est l'identité.
- `GIT_TIMEOUT_SECONDS` +/- 1 : valeur arbitraire, aucune AC ne l'observe.
- `split("/", 1)` -> `split("/", 2)` : le premier élément ne dépend pas de
  `maxsplit`.
- `returncode != 0` -> `> 0` : un returncode négatif suppose un kill par signal
  POSIX ; le timeout lève `TimeoutExpired`. Plateforme supportée : Windows.
- `arguments.command == "reconcile"` -> `<=` : le domaine se limite aux deux
  sous-commandes déclarées.
- `!=` -> `<` et `!=` -> `is not` sur des longueurs 0..3 : `len(set) <= len(list)`
  toujours, et les petits entiers sont internés.

Les probes ciblées incluent des lignes inchangées de leurs modules ; la probe
finale, filtrée sur le diff, ne retient que 9 de ces équivalents.

Findings actionnables :

1. T2, mutation : `_ensure_clone` créait la chaîne de parents sans test ; un
   workdir imbriqué absent aurait échoué. Test de régression ajouté (1 mutant).
2. T4, mutation : les tests d'exit codes importaient les constantes de
   l'implémentation ; les mutants `0->1`, `1->2`, etc. survivaient. Assertions
   remplacées par les littéraux `0`/`1`/`2` (6 mutants). Même classe de gap que
   `MAX_DEVELOPMENT_ATTEMPTS` en 06a.
3. T4, mutation : le dispatch `==` -> `is` survivait grâce à l'internement de la
   chaîne de test. Test avec une chaîne non internée (1 mutant).
4. T4, mutation : `required=True` -> `False` survivait ; aucune sous-commande ne
   serait refusée. Test de l'absence de sous-commande (1 mutant).

Findings par source : RED 0 (le seul rouge non lié à une AC était le fake AC9,
corrigé), mutation 4, refactor 0, revue 3 (docstrings des fakes, filtre `base`,
nettoyage de la branche sur `CLOSED`), CI à venir.

Critère d'adoption : **atteint** — la mutation a produit au moins un finding
actionnable qu'une revue aurait laissé passer (le couplage aux constantes
d'exit codes). Décision prise : P1 et P4 sont promues dans `AGENTS.md` §4, et
le job CI `Mutation testing` applique le gate à chaque PR. L'allowlist reste
human-owned : une entrée ne peut couvrir qu'un comportement qu'aucun critère
d'acceptation n'observe.

## Hypothèses

- `GET /pulls?head=&base=` reste fiable après suppression de branche ; vérifié sur le dépôt, pas de fallback par SHA.
- Les tests d'intégration Trello restent en lecture seule : aucun déplacement réel de carte, pour ne pas polluer le board sandbox.
- Le test d'intégration GitHub réel est opt-in (`integration`), et vérifie `OPEN` puis `CLOSED` après suppression de la branche.
- `FakeTicketSource` conserve trois listes distinctes ; les assertions portent sur l'état des listes, pas sur la séquence des appels internes.
- Le nom de branche est dérivé par `BRANCH_NAME_TEMPLATE` (`process_ticket.py`), pas recalculé différemment dans `reconcile`.
- `NOT_FOUND` réutilise l'exit code `1` (échec de traitement) déjà défini par `cli.py`.

## Limites

- Si `set_status` échoue après l'ouverture de la PR, la carte reste en To Do alors qu'une PR existe ; un `run` ultérieur peut créer une seconde PR. L'ordre déplacer-puis-commenter supprime le commentaire trompeur, pas ce risque. Il est traité en spec 08 (idempotence de `POST /pulls`, verrou).
- `reconcile` ne détecte pas une PR rouverte après coup : une carte déjà en Done n'est plus scannée.
- Aucune reprise après crash : un `reconcile` interrompu doit être relancé manuellement.

## Plan de livraison

Une branche `feat/06b-trello-lifecycle`, une PR, commits verts successifs :

1. Ports, config et adapter Trello (AC1-AC3).
2. GitHub `pull_request_state` (AC4).
3. `run` : déplacement en In Review puis commentaire (AC5).
4. Cas d'usage `reconcile` + CLI + composition (AC6-AC11).
5. README, amendement de `specs/04-cli.md`, résultat du pilot (AC12).
6. Durcissement : filtre `base`, nettoyage de branche sur `CLOSED` (AC13), Bandit, gate de mutation et règle RED-first.

Chaque commit laisse `ruff check`, `ruff format --check`, `lint-imports` et `pytest tests/unit` verts.

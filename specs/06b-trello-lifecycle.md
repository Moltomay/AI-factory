# Spec 06b — `trello-lifecycle` (Étape 6b)

> Les specs sont numérotées dans l'ordre d'exécution des étapes : `specs/NN-<task>.md`.

## Contexte

- La spec 06 est éclatée en 5 sous-parties : 06a sécurité runtime, 06b cycle de vie Trello, 06c review JSON retry, 06d QA vs Reviewer, 06e spec agent. 06a est livrée.
- Aujourd'hui `run` traite la première carte de `TRELLO_LIST_ID`, ouvre la PR et poste un commentaire. La carte reste dans la liste To Do : le board ne reflète ni la revue en cours, ni le merge, ni l'abandon.
- `ProcessTicket` nomme ses branches `factory/{ticket_id}` (`BRANCH_NAME_TEMPLATE`), ce qui donne une clé stable pour retrouver la PR d'une carte.
- GitHub `GET /repos/{repo}/pulls?head={owner}:{branch}&state=all` retrouve les PR d'une branche supprimée (vérifié sur les PR #9 et #11 du dépôt) : pas besoin de fallback.
- Livraison en une branche + une PR, plusieurs commits verts. Pilot de mesure décrit plus bas ; `AGENTS.md` n'est **pas** modifié par cette spec.

## Objectifs

1. Le board reflète le cycle de vie : To Do -> In Review -> Done ou retour en To Do.
2. `run` ne détecte jamais un merge : il ne fait que publier et déplacer en In Review.
3. Une commande `reconcile` séparée, ré-exécutable, applique le sort des PR.
4. Aucune nouvelle dépendance runtime, aucune base de données, aucun webhook.
5. Le comportement est testé sur des ports factices, sans écriture réelle sur Trello.

## Périmètre — inclus

1. `interfaces/config.py` — `TRELLO_REVIEW_LIST_ID` et `TRELLO_DONE_LIST_ID` rejoignent `REQUIRED_VARIABLES`. Les trois identifiants de liste doivent être distincts deux à deux ; sinon `ConfigurationError` (message listant des noms, jamais des valeurs). `FactoryConfig` gagne les deux champs.
2. `application/ports.py` — enums `TicketStatus` (`TODO`, `IN_REVIEW`, `DONE`) et `PullRequestState` (`OPEN`, `MERGED`, `CLOSED`, `NOT_FOUND`). `TicketSource` gagne `list_by_status` et `set_status`. `VersionControl` gagne `pull_request_state`.
3. `infrastructure/trello.py` — `TrelloLists` (trois identifiants), `set_status` (`PUT /cards/{id}` avec `idList`), `list_by_status`. `TrelloBoard` reçoit `TrelloLists` au lieu d'un `list_id` unique.
4. `infrastructure/github.py` — `pull_request_state(branch_name)`. Plusieurs PR sur la même branche : priorité `MERGED` > `OPEN` > `CLOSED`.
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
   - `CLOSED` -> carte en To Do, **puis** commentaire mentionnant la branche ;
   - `OPEN` -> aucune action ;
   - `NOT_FOUND` -> carte ignorée, les autres cartes restent traitées, sortie `1`.

### Ordre des opérations

- `run` déplace **avant** de commenter : un échec de commentaire ne laisse pas une carte en To Do avec un commentaire trompeur.
- `reconcile` déplace **avant** de commenter sur `CLOSED`, pour la même raison.

### Idempotence

`reconcile` ne scanne que In Review. Une carte déplacée en Done ou en To Do n'est plus vue au passage suivant : deux exécutions consécutives sans changement d'état ne produisent ni déplacement ni commentaire.

## Critères d'acceptation

| # | Critère |
|---|---|
| AC1 | Config : les deux nouvelles variables sont requises ; absentes ou vides -> `ConfigurationError` nommant les variables ; trois identifiants identiques ou deux identiques -> `ConfigurationError` |
| AC2 | Trello : `set_status` envoie `idList` de la liste correspondant au statut ; erreur HTTP -> `ExternalServiceError` dont le message ne contient ni clé ni token |
| AC3 | Trello : `list_by_status(IN_REVIEW)` lit la liste de revue et retourne les cartes sous forme de `Ticket` |
| AC4 | GitHub : `pull_request_state` mappe `OPEN`, `MERGED`, `CLOSED`, `NOT_FOUND` ; plusieurs PR -> `MERGED` prioritaire, puis `OPEN`, puis `CLOSED` |
| AC5 | `run` sur succès : `set_status(IN_REVIEW)` appelé avant `report_result`, puis commentaire avec l'URL ; sur échec : commentaire d'échec et aucun déplacement |
| AC6 | `reconcile` : carte In Review + PR `MERGED` -> Done, aucun commentaire |
| AC7 | `reconcile` : carte In Review + PR `CLOSED` -> To Do puis commentaire contenant le nom de la branche |
| AC8 | `reconcile` : carte In Review + PR `OPEN` -> aucun déplacement, aucun commentaire |
| AC9 | `reconcile` : PR `NOT_FOUND` -> carte ignorée, les autres traitées, résultat agrégé marque l'échec, CLI sort `1` |
| AC10 | `reconcile` est idempotent : deux exécutions sans changement d'état ne produisent aucun déplacement ni commentaire |
| AC11 | CLI : `run` et `reconcile` sont deux sous-commandes distinctes ; `reconcile` n'est pas exécuté par `run` ; erreur de config -> `2` |
| AC12 | README : documente les deux variables, le cycle de vie, `reconcile`, les exit codes et la limite de ré-exécution |

Chaque AC est couvert par un test `test_spec06b_acN_<behavior>` (convention `AGENTS.md`) ; le mapping AC -> test et le rapport des sondes sont reportés dans la PR.

## Pilot — règles locales (non `AGENTS.md`)

Ce pilot mesure si les règles méritent d'entrer dans `AGENTS.md` §4. Il s'applique à 06b uniquement.

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

### Artefacts du pilot

- `requirements-mutation.txt` : `cosmic-ray==8.7.0`, hors CI.
- `cosmic-ray.toml` : modules du diff uniquement, via `cr-filter-git` contre `main`.
- Aucun script d'automatisation tant que la règle n'est pas adoptée.

### Résultat du pilot (à remplir avant la revue finale)

| AC | RED | Survivants actionnables | Survivants équivalents | Refactor probe | Coût (s) |
|---|---|---|---|---|---|
| AC1 | | | | | |
| AC2 | | | | | |
| AC3 | | | | | |
| AC4 | | | | | |
| AC5 | | | | | |
| AC6 | | | | | |
| AC7 | | | | | |
| AC8 | | | | | |
| AC9 | | | | | |
| AC10 | | | | | |
| AC11 | | | | | |
| AC12 | | | | | |

## Hypothèses

- `GET /pulls?head=` reste fiable après suppression de branche ; vérifié sur le dépôt, pas de fallback par SHA.
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

Chaque commit laisse `ruff check`, `ruff format --check`, `lint-imports` et `pytest tests/unit` verts.

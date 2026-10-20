# Spec 04 — `cli` (Étape 4)

> Les specs sont numérotées dans l'ordre d'exécution des étapes : `specs/NN-<task>.md`.

## Contexte

- Étape 3 mergée : les 3 adapters (Trello, GitHub, OpenRouter) implémentent les ports de l'étape 2, testés unitairement (fakes) et réellement (marker `integration`).
- Il manque le point d'entrée : rien n'instancie les adapters ni n'appelle `ProcessTicket`. Il manque aussi un adapter `QualityRunner` (checks déterministes) pour que le use case soit exécutable.
- Livraison en une branche + une PR, 3 commits verts : (a) `QualityRunner`, (b) config/env/composition, (c) CLI.

## Objectifs

1. `python -m ai_factory run` traite un ticket de bout en bout en local, sans aucune logique métier dans `interfaces/`.
2. La configuration vient de l'environnement, complétée par un `.env` local gitignoré (chargé automatiquement, l'environnement réel gagne).
3. Les erreurs de config sont explicites et sans secret ; les échecs du pipeline donnent un code de sortie non nul.

## Périmètre — inclus

1. `infrastructure/quality.py` — `CommandQualityRunner(workdir)` implémentant `QualityRunner` :
   - `ruff check .` toujours ; `pytest -q` seulement si le clone contient un dossier `tests/`.
   - Exécutables résolus depuis le venv courant (`sys.executable`) puis `PATH` ; introuvable -> `ExternalServiceError`.
   - Tous les checks verts -> `True`, sinon `False` (pas d'exception pour un échec de lint/test).
2. `interfaces/env.py` — mini-parseur `.env` (`KEY=VALUE`, commentaires `#`, quotes retirées), `setdefault` : les variables déjà définies gagnent ; fichier absent = no-op.
3. `interfaces/config.py` — `FactoryConfig` (frozen) + `load_config(environ) -> FactoryConfig` :
   - Requis : `TRELLO_API_KEY`, `TRELLO_TOKEN`, `TRELLO_LIST_ID`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `GITHUB_TOKEN`, `GITHUB_REPOSITORY`.
   - Optionnel : `FACTORY_WORKDIR` (défaut `%TEMP%\factory-workdir`) ; le clone vit dans `<workdir>\clone` et est partagé entre l'agent et le VCS.
   - Manquant/vide -> `ConfigurationError` listant **uniquement les noms** des variables absentes.
4. `interfaces/composition.py` — `build_ticket_source(config)`, `build_code_agent(config)`, `build_quality_runner(config)`, `build_version_control(config)`, `build_process_ticket(config)` : seule zone où les adapters sont instanciés.
5. `interfaces/cli.py` — `main(argv) -> int` + `ai_factory/__main__.py` (`sys.exit(main())`) :
   - Commande unique `run` (argparse, `--help`), charge `./.env` avant la config.
   - Aucun ticket en attente -> message clair, exit `0`.
   - Pipeline réussi -> affiche `Pull request opened: <url>`, exit `0`.
   - Pipeline échoué (résultat terminal d'échec) -> affiche la raison, exit `1`.
   - `ConfigurationError` -> message avec les noms manquants, exit `2`.
   - `ExternalServiceError` -> message, exit `1`. Autres exceptions : non capturées (fail loudly).
6. Tests unitaires sans réseau : env, config, quality (faux `run_process`), CLI (composition monkeypatchée, sorties capturées).
7. README : section « Run locally » (variables, commande).

## Périmètre — exclu

- E2E réel (étape 5), retries réseau, transitions de statut Trello, packaging `console_scripts`, plusieurs tickets par run.

## Critères d'acceptation

| # | Critère |
|---|---|
| AC1 | `load_config` : environnement complet -> `FactoryConfig` ; variables manquantes -> `ConfigurationError` (noms seulement, aucune valeur) ; `FACTORY_WORKDIR` absent -> défaut temp |
| AC2 | `.env` : valeurs chargées si absentes de l'environnement ; une variable déjà définie n'est jamais écrasée ; fichier absent toléré |
| AC3 | CLI : liste Trello vide -> message « aucun ticket », exit `0` |
| AC4 | CLI : run réussi -> URL de PR affichée, exit `0` |
| AC5 | CLI : run échoué -> raison affichée, exit `1` ; config invalide -> exit `2` |
| AC6 | `CommandQualityRunner` : lint+tests verts -> `True` ; un échec -> `False` ; `pytest` seulement si `tests/` existe ; exécutable absent -> `ExternalServiceError` |
| AC7 | Aucun secret (token, clé) dans stdout/stderr des tests CLI |

## Hypothèses

- Le CLI tourne depuis la racine du repo (`.env` attendu là) avec le venv du projet.
- Config invalide et résultats du pipeline suffisent pour valider la CLI en unitaire ; le vrai parcours Trello -> PR est couvert par l'étape 5.
- CI inchangée : `pytest tests/unit` uniquement.

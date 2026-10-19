# Spec 00 — `project-bootstrap` (Étape 0)

> Les specs sont numérotées dans l'ordre d'exécution des étapes : `specs/NN-<task>.md`.

## Contexte

- **Repo cible** : clone local de `github.com/Moltomay/AI-factory`, branche `main`, 1 commit (LICENSE + README).
- **Règles appliquées** : les fichiers human-owned (`AGENTS.md`, `ARCHITECTURE.md`, `.pre-commit-config.yaml`, `ruff.toml`, `.github/workflows/ci.yml`) doivent s'appliquer au repo cible.
- **Contraintes imposées par `ci.yml`** : `PYTHONPATH=.` (package à la racine, pas de `src/`), tests dans `tests/unit/`, dépendances via `requirements*.txt`, branches `main`/`develop`.
- **Règle d'architecture** : Clean Architecture 4 couches (`domain -> application -> infrastructure -> interfaces`), dépendances vers l'intérieur, enforceée par `import-linter`.

## Objectifs

1. Repo bootstrapé et conforme aux règles du projet.
2. `ai_factory` importable depuis la racine, squelette des 4 couches en place.
3. Contrat d'architecture actif (`lint-imports` passe).
4. Chaîne qualité opérationnelle : pre-commit installé, ruff, pytest, lint-imports verts en local.
5. CI GitHub verte sur la première PR.

## Périmètre — inclus

1. Copie verbatim dans le repo : `AGENTS.md`, `ARCHITECTURE.md`, `.pre-commit-config.yaml`, `ruff.toml`, `.github/workflows/ci.yml` (aucune modification).
2. `.importlinter` : contrat *layers* (`interfaces -> infrastructure -> application -> domain`), package `ai_factory`. Le fichier DFTI `importlinter` du dossier de règles n'est pas copié.
3. venv Python 3.11 : `py install 3.11` (portée utilisateur) puis `py -3.11 -m venv .venv`.
4. Dépendances : `requirements-dev.txt` épinglé (`ruff==0.16.9`, `pytest==9.1.1`, `import-linter==2.15`, `pre-commit==4.7.0`) ; `requirements.txt` vide (les deps runtime seront ajoutées par les étapes qui les utilisent).
5. Squelette `ai_factory/` : `__init__.py` + `domain/`, `application/`, `infrastructure/`, `interfaces/` (docstrings de module, aucune logique métier).
6. Tests : `tests/unit/` avec un test smoke (« le package s'importe depuis la racine ») ; `tests/integration/` vide.
7. `.gitignore` : `.venv/`, `__pycache__/`, caches pytest/ruff, `.env*`, artefacts de build.
8. `specs/00-project-bootstrap.md` : cette spec, commitée avec le code.
9. `README.md` mis à jour minimalement : description, structure, setup dev, commandes de test.
10. Vérifications locales : `pre-commit install`, `pre-commit run --all-files`, `ruff check .`, `ruff format --check .`, `lint-imports`, `pytest tests/unit`.
11. Git : branche `chore/bootstrap` -> commit -> push -> PR vers `main`.

## Périmètre — exclu

Code métier (`domain`/`application`), adapters (Trello, LLM, GitHub), CLI, secrets, nouveaux workflows CI.

## Critères d'acceptation

| # | Critère | Vérifié par |
|---|---|---|
| AC1 | `ai_factory` s'importe depuis la racine du repo | test smoke `tests/unit` |
| AC2 | Le contrat d'architecture passe (4 couches déclarées, aucune violation) | `lint-imports` exit 0 |
| AC3 | Code conforme au lint et au format | `ruff check .` + `ruff format --check .` : 0 erreur |
| AC4 | Suite unitaire verte | `pytest tests/unit` |
| AC5 | Hooks pre-commit opérationnels | `pre-commit run --all-files` vert |
| AC6 | CI GitHub verte sur la PR | 4 jobs passent : secrets-scan, lint, test, dependency-audit |
| AC7 | Aucun fichier DFTI copié ; seul `.importlinter` mono-package est présent | revue du diff |
| AC8 | Aucun secret dans le repo ni dans le diff | gitleaks (local + CI) + revue du diff |

## Hypothèses

- Nom du package : `ai_factory`.
- `py install 3.11` disponible (vérifié) ; fallback : installeur python.org portée utilisateur.
- Auth git via Windows Credential Manager (compte Moltomay déjà stocké) ; PR créée par l'humain sur GitHub ou autorisée via le credential stocké.
- CI vérifiable sans token (repo public).
- `pyproject.toml` minimal (config pytest : racine importable) ajouté pour rendre AC1/AC4 robustes hors CI.

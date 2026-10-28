# Spec 06a — `agent-runtime-hardening` (Étape 6a)

> Les specs sont numérotées dans l'ordre d'exécution des étapes : `specs/NN-<task>.md`.

## Contexte

- La spec 06 est éclatée en 5 sous-parties : 06a sécurité runtime, 06b Trello Done, 06c review JSON retry, 06d QA vs Reviewer, 06e spec agent.
- Aujourd'hui, `OpenRouterAgent._run_command` résout n'importe quel exécutable avec `shutil.which` et l'exécute via `run_process`. `run_process` appelle `subprocess.run` sans `env` : le sous-processus hérite donc de `TRELLO_TOKEN`, `OPENROUTER_API_KEY`, `GITHUB_TOKEN` et `FACTORY_*`.
- `read_file`, `write_file` et `list_files` confinent les chemins au workdir, mais `.git` reste accessible.
- `GitHubVersionControl` a besoin de `fetch`, `switch`, `add`, `commit`, `push` et `POST /pulls` : la politique git read-only ne doit pas s'y appliquer.
- Livraison en une branche + une PR, 2 commits verts : (a) environnement sûr, (b) allowlist + git read-only + protection `.git`. Pilot TDD : tests d'abord, RED classifié, puis implémentation.

## Objectifs

1. Aucun secret de la factory n'atteint un sous-processus.
2. Le modèle ne peut lancer que des exécutables approuvés.
3. Le modèle peut inspecter git, pas modifier l'état du dépôt.
4. Les outils fichier ne peuvent ni lire ni écrire `.git`.
5. L'adapter GitHub garde `push` et l'ouverture de PR.
6. La limite est documentée : 06a est un garde-fou, pas un sandbox OS.

## Périmètre — inclus

1. `infrastructure/process.py` — `build_safe_environment` (default deny) ; `run_process` l'utilise pour **tous** les appels :
   - Allowlist système commune (`PATH`, `HOME`, `TEMP`, `TMP`, `TMPDIR`, locale, `USER`, `LOGNAME`, `SHELL`) + variables Windows nécessaires (`SYSTEMROOT`, `WINDIR`, `COMSPEC`, `PATHEXT`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `PROGRAMDATA`, `PROGRAMFILES*`, `NUMBER_OF_PROCESSORS`, `PROCESSOR_ARCHITECTURE`, `OS`).
   - Tout le reste est supprimé, dont `TRELLO_*`, `OPENROUTER_*`, `GITHUB_*` et `FACTORY_*` (préfixes insensibles à la casse).
   - Pas d'opt-out : ajouter une variable = l'ajouter à l'allowlist + un test.
2. `infrastructure/openrouter_agent.py` — `_run_command` :
   - Allowlist : `git`, `python`, `python3`, `pytest`, `ruff` ; nom nu obligatoire (aucun `/` ni `\`) ; comparaison sur le basename lowercase, sans `.exe`.
   - Refus -> `_ToolCallError` -> message d'erreur au modèle ; la boucle continue, le run ne crashe pas.
   - Git read-only : seules `status`, `diff`, `log`, `show`, `rev-parse`, `ls-files`, `grep` sont acceptées. La sous-commande doit être le premier token. Toute option globale est refusée (`-C`, `-c`, `--config-env`, `--git-dir`, `--work-tree`, `--exec-path`, `-p`, `--paginate`). Sont aussi refusés `--no-index`, `--textconv`, `--ext-diff`, `--open-files-in-pager`, `--output` et ses abréviations (`--outp*`). `git` seul ou sans sous-commande est refusé.
   - `write_file` reste disponible en implémentation ; les deux reviews gardent les outils read-only.
3. `infrastructure/openrouter_agent.py` — `_resolve` : refus de tout chemin dont une partie relative vaut `.git` (insensible à la casse), après résolution des symlinks ; s'applique à `read_file`, `write_file` et `list_files`.
4. Tests unitaires sans réseau (fakes `subprocess.run`, stub LLM) : AC1–AC8. Les fakes existants gagnent le paramètre `env`, sans changer leurs assertions.
5. README : section sur la limite « garde-fou, pas sandbox » et le risque résiduel.
6. Spec enregistrée sous `specs/06a-agent-runtime-hardening.md`.

## Périmètre — exclu

- Container, VM, sandbox OS, isolation réseau, détection de prompt injection.
- Nouvelle dépendance.
- Modification des commandes de `GitHubVersionControl` (`fetch`, `switch`, `add`, `commit`, `push`, `POST /pulls`).
- Retrait de `python` / `pytest` de l'allowlist.
- 06b, 06c, 06d, 06e.

## Critères d'acceptation

| # | Critère |
|---|---|
| AC1 | Environnement sûr : les variables système nécessaires sont conservées ; `TRELLO_*`, `OPENROUTER_*`, `GITHUB_*`, `FACTORY_*` et les variables inconnues sont absentes ; les préfixes sont insensibles à la casse |
| AC2 | Les 3 familles de sous-processus (outil agent, quality runner, adapter GitHub) utilisent l'environnement sûr |
| AC3 | `run_command` exécute un exécutable approuvé en nom nu ; refuse un exécutable non approuvé ou un chemin ; le modèle reçoit un message d'erreur ; le run ne crashe pas |
| AC4 | Git read-only : seules les sous-commandes listées passent ; les autres sous-commandes, les options globales, `git` seul et les flags listés sont refusés ; l'adapter GitHub garde `push` + PR |
| AC5 | `read_file` et `write_file` refusent un chemin contenant `.git` (insensible à la casse) ; aucun fichier n'est écrit |
| AC6 | Les 81 tests unitaires existants gardent leurs assertions et passent ; `write_file` reste disponible en implémentation ; les 2 reviews gardent les outils read-only |
| AC7 | Le token GitHub reste dans l'argument `-c http.extraHeader` ; il est absent de l'environnement enfant et des messages d'erreur |
| AC8 | Le README documente la limite : garde-fou, pas sandbox ; `python` et `pytest` peuvent exécuter du code arbitraire et utiliser le réseau |

Chaque AC est couvert par un test `test_spec06a_acN_<behavior>` (convention `AGENTS.md`) ; le mapping AC -> test et le rapport RED sont reportés dans la PR.

## Hypothèses

- 06a est un garde-fou, pas un sandbox OS : `python` et `pytest` peuvent lancer `git push` ou lire des fichiers. Risque résiduel accepté pour le MVP et documenté.
- Tests unitaires déterministes, sans réseau, avec fakes (`subprocess.run`, stub LLM) ; CI inchangée (`pytest tests/unit`).
- Pilot TDD : tests écrits d'abord, RED attendu et classifié (`missing API` vs `wrong behavior` vs `missing documentation`) ; un test qui couvre un comportement **nouveau** et passe avant le code est corrigé ; un test de **non-régression** est marqué comme tel et peut être vert d'emblée ; le rapport est dans la PR.
- Résolution des exécutables inchangée (`shutil.which`) ; la factory tourne avec le venv du projet, sinon `ruff` / `pytest` peuvent être introuvables (`python -m ...` reste possible).
- Branche `feat/06a-agent-runtime-hardening` depuis `main` (`6fb0801`), 2 commits, 1 PR ; spec enregistrée sous `specs/06a-agent-runtime-hardening.md`.
- Pas de nouvelle dépendance ; `ruff.toml`, `.importlinter`, `.pre-commit-config.yaml` et la CI ne changent pas.

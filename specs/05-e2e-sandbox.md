# Spec 05 — `e2e-sandbox` (Étape 5)

> Les specs sont numérotées dans l'ordre d'exécution des étapes : `specs/NN-<task>.md`.

## Contexte

- Étapes 1 à 4 mergées : domaine, use case, adapters, CLI. Tout est vert en unitaire et en réel (Trello, GitHub, OpenRouter).
- Cette étape n'ajoute (a priori) aucun code : elle prouve le parcours complet en conditions réelles sur le sandbox.

## Objectif

Une carte Trello réelle traverse tout le pipeline et produit une pull request relisible dans `Moltomay/ai-factory-sandbox`, avec un commentaire de résultat sur la carte.

## Préconditions

1. `main` local à jour, `.env` complet (`OPENROUTER_MODEL` = modèle free validé, ex. `minimax/minimax-m3.1-flash:free`).
2. Sandbox propre : branche `main` uniquement, aucune PR ouverte.
3. Une carte en attente dans la liste Trello configurée (scénario : « Ajouter un fichier hello.txt »).
4. `FACTORY_WORKDIR` vidé (le clone est recréé au premier run, ce qui teste aussi ce chemin).

## Scénario

```powershell
.\.venv\Scripts\python.exe -m ai_factory run
```

Observation : un seul ticket traité, étapes implémentation -> checks -> QA -> review finale -> PR ; durée et nombre de tours LLM notés.

## Critères d'acceptation

| # | Critère |
|---|---|
| AC1 | CLI : exit `0`, URL de PR affichée et identique à celle du commentaire Trello |
| AC2 | PR sandbox : branche `factory/<ticket_id>` basée sur `main`, contient le fichier demandé par la carte, ouverte (non mergée) |
| AC3 | Trello : commentaire de résultat sur la carte avec l'URL de la PR |
| AC4 | Sécurité/état : aucun secret en console, clone présent dans `FACTORY_WORKDIR`, repo de travail propre après le run |
| AC5 | Scénario obligatoire d'échec qualité déterministe ou par injection de faute contrôlée : vérifier au plus une tentative de réimplémentation avec feedback, puis un commentaire d'échec sur la carte Trello et un code de sortie `1` |

## Périmètre — exclu

- Optimisation des prompts/modèles, multi-tickets, transitions de statut Trello, merge automatique.
- Nettoyage des artefacts sandbox (PR/branche) : fait après la revue humaine.
- Correction de défauts éventuels : bugfix séparé, sur validation (nouvelle branche + PR + tests).

## Livrable

- Rapport de run : commande, durée, étapes observées, URL de PR, commentaire Trello, résultat des ACs.
- Si un défaut est trouvé : description + proposition de correctif, sans improviser de contournement.

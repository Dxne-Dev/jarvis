# 00 — Démarrage

## Ce qui a été fait

Le dépôt, sans code applicatif. Les choix sont dans `DECISIONS.md`, l'état dans `PROGRESS.md`.

L'ancien Jarvis (`octavebahoun/Jarvis`) est cloné dans `legacy/` pour ses leçons seulement. Ce dossier est ignoré par git : on n'en recopie pas le code.

## Les leçons retenues de l'ancien Jarvis

| Problème rencontré | Ce qu'on fait cette fois |
|---|---|
| Une app web dans Docker n'entend pas le micro et ne pilote pas le bureau | App desktop Tauri + moteur Python sur la machine |
| Les bugs n'apparaissaient que sur la vraie machine | On teste sur la vraie machine, dès le début |
| `create_all()` n'ajoute pas une colonne à une table existante | Migrations Alembic dès le premier schéma |
| Deux processus lançaient les migrations en même temps | Une seule migration, au démarrage du moteur |
| Un petit modèle a renvoyé `{"steps": [...]}]` | Appel d'outils natif, schéma, parse tolérant, un seul nouvel essai |
| Le cron en UTC décalait « 8 h » au changement d'heure | Planification dans le fuseau du système, testée sur les deux changements d'heure |
| Une tâche ponctuelle restait active ; pas de suppression | Désactivation après exécution ; CRUD complet |
| Trois appels LLM à la suite (intention, plan, réponse) | Un seul appel qui répond ou appelle des outils |

## Pourquoi un historique neuf

L'ancien dépôt GitHub avait été supprimé et les deux anciens commits ne respectaient pas les règles de traçabilité du projet. Le nouvel historique part donc d'une racine propre. Rien n'a été détruit : les anciens commits restent sur des branches locales `archive-v0-*` qui ne sont jamais poussées.

Des hooks git locaux protègent le dépôt : un commit qui contient une valeur du `.env` ou un fichier interdit est refusé avant d'exister.

## Vérifié

- Ubuntu 26.04.1, GNOME 50 sous Wayland, 7,2 Go de RAM, i5-4200M, Intel HD 4600.
- Docker 29.1.3 répond ; l'utilisateur est dans le groupe `docker`.
- Chaque clé du `.env` a été testée par un vrai appel léger (tableau dans `PROGRESS.md`).
- Cartesia Sonic `sonic-3.6` parle français : la documentation officielle liste `fr`, et un appel réel a renvoyé un fichier WAV.

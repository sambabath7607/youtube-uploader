# YouTube Uploader

Site Django + API qui envoie sur YouTube les vidéos créées avec Claude (Claude Code ou connecteur MCP).
En ligne : https://api.batchcodeia.com

## Ce que fait le projet
- `accounts` : inscription, connexion, clé d'API (hachée, affichée une seule fois), export et suppression des données.
- `youtube_uploader` : connexion de la chaîne YouTube (OAuth Google, jeton chiffré), API `/youtube/api/v1/videos/`,
  file d'attente des envois (worker `traiter_envois`).
- `mcp_server.py` : connecteur MCP pour Claude.

## Utiliser avec Claude
Page du site : https://api.batchcodeia.com/guide-claude/ (préparer son compte, ajouter le connecteur dans claude.ai
avec l'en-tête `x-api-key`, **prompt général** à copier, demandes types, ce qui marche sur ordinateur ou téléphone).
Outils du connecteur : `fabriquer_voix`, `etat_voix`, `preparer_envoi`, `envoyer_video`, `etat_video`, `mes_videos`.

## Installation sur un PC
```
python -m venv ..\.venv
..\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env             (puis remplir les valeurs)
python manage.py migrate
python manage.py runserver
python manage.py traiter_envois    (dans un second terminal : envoie les vidéos)
```

## Tests
```
python manage.py test
```

## Sur le serveur (~/youtube-uploader)
- `youtube-uploader` : le site (gunicorn) · `youtube-worker` : les envois · `youtube-mcp` : le connecteur MCP.
- Journal du projet : `JOURNAL.md`. Règles de travail : `CLAUDE.md`.

## Secrets
Jamais dans Git : `.env`, `client_secret*.json`, `token.json`, `db.sqlite3` (voir `.gitignore`).

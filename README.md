# YouTube Uploader

Site Django + API qui fabrique sur nos serveurs (Modal) les vidéos demandées à un agent IA (connecteur MCP)
et les envoie sur la chaîne YouTube du client. Le client n'installe rien.
En ligne : https://api.batchcodeia.com

## Ce que fait le projet
- `accounts` : inscription, connexion, clé d'API (hachée, affichée une seule fois), export et suppression des données.
- `youtube_uploader` : connexion de la chaîne YouTube (OAuth Google, jeton chiffré), API `/youtube/api/v1/videos/`,
  file d'attente des envois (worker `traiter_envois`).
- `mcp_server.py` : connecteur MCP pour les agents IA (claude.ai, ChatGPT, Claude Code…).
- `fabrication_modal/` : rendu des vidéos sur Modal (`service.py`), modèles Remotion (`remotion/`), catalogue des
  modèles partagé avec le site (`modeles.py`). `voix_modal/` : la voix clonée sur Modal.

## Utiliser avec un agent IA
Page du site : https://api.batchcodeia.com/guide-claude/ (préparer son compte, ajouter le connecteur dans claude.ai,
**prompt général** à copier, demandes types). Modèles : https://api.batchcodeia.com/youtube/modeles/.
Outils du connecteur (8) : `mon_compte`, `modeles_video`, `fabriquer_video`, `etat_video`, `mes_videos`,
`fabriquer_voix`, `etat_voix`, `envoyer_video`.

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

# Journal du projet YouTube Uploader

Suite du journal (parties 1 à 20 dans le document d'origine). Une partie par étape terminée.
Ne jamais écrire la valeur d'une clé dans ce fichier : il va sur GitHub.

---

## Partie 21 : Petites corrections et mise à jour du serveur (terminée, 26 octobre 2026)

But : corriger les points fragiles repérés à l'analyse du projet, puis les mettre en ligne.

### Fichiers modifiés (commit f0f10a7)

blog/settings.py
```python
INSTALLED_APPS = [
    # ...
    'accounts',            # ajouté : l'application était utilisée sans être déclarée
    'youtube_uploader',
    # ...
]

TEMPLATES = [
    {
        # ...
        'DIRS': [BASE_DIR / "template"],  # avant : [BASE_DIR, 'template'] (dépendait du dossier de lancement)
        # ...
    },
]
```

youtube_uploader/upload.py : l'ancienne méthode du début du projet est retirée (`get_credentials`, `InstalledAppFlow`,
`client_secret.json`, `token.json`). Chaque envoi utilise uniquement le token Google chiffré de l'utilisateur, en base.
```python
def upload_video(chemin_video, titre, description="", statut="private", user=None,
                 pour_enfants=False, contenu_ia=False):
    # Toujours le jeton chiffré de l'utilisateur, rangé en base (plus de fichier token.json)
    if user is None:
        raise ValueError("Un envoi doit toujours être fait pour un utilisateur connecté.")
    creds = get_credentials_user(user)
    # ... (le reste ne change pas)
```

youtube_uploader/oauth.py : le retour de Google n'affiche plus une erreur 500.
- l'utilisateur clique sur « Annuler » chez Google (`?error=access_denied`) → message « Connexion annulée » ;
- lien sans `state` ou sans `code` → « Lien de connexion invalide ou expiré » ;
- Google refuse le code → « Google n'a pas pu confirmer la connexion » (aucun détail technique affiché) ;
- succès → « Ta chaîne YouTube est connectée ».
Les valeurs `oauth_state` et `code_verifier` sont retirées de la session après usage.

youtube_uploader/tests.py : 4 tests ajoutés (RetourGoogleTests : annulation, lien invalide, code refusé ;
EnvoiSansUtilisateurTests : plus d'envoi sans utilisateur).

### Vérifications
- Sur le PC : `python manage.py check` → aucun problème ; `python manage.py test` → 29 tests OK.
- Sur le serveur (dans ~/youtube-uploader, .venv activé), une commande à la fois :
```
cp db.sqlite3 ~/db_youtube_avant-maj_$(date +%F).sqlite3     # sauvegarde (164 Ko)
git pull origin main                                          # f0f10a7
python manage.py check                                        # aucun problème
sudo systemctl restart youtube-uploader
curl -s -o /dev/null -w "site %{http_code}\n" https://api.batchcodeia.com/login/   # site 200
```

### Pièges rencontrés
- Juste après `systemctl restart`, le site répond 502 pendant une ou deux secondes (gunicorn démarre). Attendre 5 s et refaire le test.
- Test du connecteur MCP : « Token non valide » = clé de l'ordinateur (base locale). Le serveur a sa propre base :
  utiliser la clé de https://api.batchcodeia.com/ma-cle/.
- Les fichiers `youtube_uploader/token.json` et `client_secret.json` restent sur le PC (ignorés par Git) mais ne servent plus.
  token.json donne accès à la chaîne : à supprimer, et retirer l'accès sur myaccount.google.com/permissions.

### Repéré pendant cette partie
- Les deux sites du serveur (batchcodeia et youtube-uploader) utilisent le même fichier de contrôle gunicorn
  (/home/batch/.gunicorn/gunicorn.ctl) : corrigé dans la Partie 22 (correction 11).

### Ensuite
Partie 22 : correction de toutes les mauvaises pratiques. Partie 23 : envoi direct depuis Claude sans lien public
(outil MCP qui donne une adresse d'envoi à usage unique).

---

## Partie 22 : Correction des mauvaises pratiques (en cours)

Règle décidée : tout ce qui n'est pas une bonne pratique est corrigé maintenant, rien n'est laissé « pour plus tard ».
Liste : 1 settings.py (sécurité HTTPS, courriels, journal, SQLite) · 2 messages d'erreur sans détail interne ·
3 déchiffrement sans repli silencieux · 4 clés d'API hachées · 5 token.json et client_secret.json supprimés du PC ·
6 Pico CSS rangé dans le projet · 7 file d'attente fiable pour les envois · 8 redirection après inscription ·
9 README et include · 10 connecteur MCP (DNS rebinding) · 11 fichier de contrôle gunicorn propre à chaque site.

### Correction 1 : blog/settings.py (terminée)
- `MAILERS` retiré : ce réglage n'existe pas dans Django (Django utilisait donc SMTP sur localhost, inexistant).
  Remplacé par `EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"`.
- SQLite : `'OPTIONS': {"timeout": 20, "transaction_mode": "IMMEDIATE"}` (évite « database is locked »).
- Production seulement (`if not DEBUG:`) : `SECURE_PROXY_SSL_HEADER`, `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`,
  `CSRF_COOKIE_SECURE`, `CSRF_TRUSTED_ORIGINS` (construit depuis ALLOWED_HOSTS), `SECURE_HSTS_SECONDS` (30 jours),
  `SECURE_CONTENT_TYPE_NOSNIFF`, `SECURE_REFERRER_POLICY`.
- `LOGGING` : erreurs affichées dans la console (sur le serveur : `sudo journalctl -u youtube-uploader`).

Vérifications : `manage.py check` OK, 29 tests OK. `check --deploy` (DEBUG=False) : restent W009 (clé secrète du .env
local seulement ; le serveur a sa propre clé longue) et W005 / W021 (HSTS sur les sous-domaines et préchargement :
volontairement non activés, ils engageraient tout batchcodeia.com).
Avant la mise en ligne : vérifier que Nginx envoie `X-Forwarded-Proto` (sinon SECURE_SSL_REDIRECT fait une boucle).

### Correction 2 : youtube_uploader/erreurs.py (terminée)
- Avant : une erreur inattendue renvoyait `f"Erreur pendant l'envoi : {e}"` (risque de chemins ou de détails internes
  dans la réponse de l'API, interdit par CLAUDE.md).
- Après : message neutre « Erreur inattendue pendant l'envoi… » pour l'utilisateur, et le détail complet seulement dans
  le journal du serveur : `logger.error("Envoi YouTube : erreur inattendue", exc_info=e)`.
- Nouveau cas : `google.auth.exceptions.RefreshError` (autorisation expirée après 7 jours en mode Test, ou retirée)
  → « L'autorisation YouTube a expiré ou a été retirée. Reconnecte ta chaîne sur la page d'accueil du site. »
- Tests ajoutés (MessageErreurTests) : `test_autorisation_expiree_message_clair`,
  `test_erreur_inattendue_sans_detail_interne`. 31 tests OK, `manage.py check` OK.

### Correction 3 : déchiffrement sans repli silencieux (terminée)
- Avant : `dechiffrer()` renvoyait le texte tel quel si le déchiffrement échouait (« ancien token en clair »). Une clé
  TOKEN_ENCRYPTION_KEY changée ou perdue donnait alors une erreur incompréhensible plus loin.
- Après : nouvelle erreur `JetonIllisible` dans youtube_uploader/chiffrement.py, signalée dans le journal du serveur
  (sans jamais écrire le jeton). L'utilisateur reçoit « Reconnecte ta chaîne » (erreurs.py).
- oauth.py : `revoquer_token_google` renvoie False si le jeton est illisible → le bouton « Déconnecter » marche toujours.
- Vérifié avant : base du PC et base du serveur = 1 jeton chacune, 0 jeton en clair (commande qui compte sans afficher).
- Tests : le test de déconnexion utilise un jeton chiffré ; ajoutés `test_deconnecter_meme_avec_jeton_illisible`,
  DechiffrementTests (`test_jeton_en_clair_refuse`, `test_jeton_illisible_message_clair`). 34 tests OK, check OK.

### Correction 4 : clés d'API hachées (terminée)
- Avant : les clés d'API étaient rangées en clair (table authtoken_token) et réaffichées en entier sur /ma-cle/.
  Une copie de db.sqlite3 suffisait pour envoyer des vidéos sur toutes les chaînes.
- Après :
  - accounts/models.py : modèle `CleApi` (user, `empreinte` SHA-256 unique, `debut` = 8 premiers caractères,
    created_at) et `CleApi.creer_pour(user)` qui renvoie la nouvelle clé une seule fois.
  - accounts/authentification.py : `CleApiAuthentication` (même en-tête « Authorization: Token SA_CLE »), recherche
    par empreinte, compte désactivé refusé. Utilisée dans youtube_uploader/api.py à la place de TokenAuthentication.
  - Migrations accounts 0001_initial (modèle) et 0002_copier_les_cles_hachees (copie l'empreinte de chaque clé
    existante, puis efface les clés en clair) → les clés actuelles continuent de marcher.
  - /ma-cle/ : la clé complète n'est affichée qu'une fois, juste après « Créer une nouvelle clé » ; ensuite seulement
    « commence par a1b2c3d4… ». Textes du guide API et de la page confidentialité mis à jour.
  - `rest_framework.authtoken` reste dans INSTALLED_APPS (la migration 0002 en dépend) ; settings.py non modifié.
- Sur le PC : base sauvegardée (..\db_avant-correction4_2026-10-26.sqlite3), puis migrate → 2 clés hachées, 0 en clair.
- Tests : 38 OK (ajoutés : clé jamais affichée en entier, affichée une seule fois, remplace l'ancienne, base sans clé
  en clair, fausse clé 401, compte désactivé 401).
- Au déploiement : sauvegarder db.sqlite3 AVANT `python manage.py migrate`.

### Correction 5 : anciens fichiers Google supprimés du PC (terminée)
- Supprimés : youtube_uploader/token.json (accès direct à la chaîne) et youtube_uploader/client_secret.json (ancien
  identifiant « application de bureau »). Plus utilisés depuis la Partie 21 ; jamais envoyés sur GitHub (.gitignore).
- Gardé : youtube_uploader/client_secret_web.json (connexion Google du site).
- À faire par Samba : retirer l'ancien accès sur https://myaccount.google.com/permissions (attention : ne pas retirer
  l'accès du site s'il porte le même nom).
- Au déploiement : vérifier si token.json ou client_secret.json existent aussi sur le serveur.
- 38 tests OK.

### Correction 6 : Pico CSS rangé dans le projet (terminée)
- Avant : template/base.html chargeait https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css (service tiers,
  version non fixée).
- Après : static/css/pico-2.1.1.min.css (83 319 octets, licence MIT, téléchargé depuis
  cdn.jsdelivr.net/npm/@picocss/pico@2.1.1, même version que celle utilisée jusque-là) ; base.html utilise
  `{% static 'css/pico-2.1.1.min.css' %}`.
- Test ajouté : `test_style_servi_par_le_site_sans_cdn`. 39 tests OK.
- Au déploiement : `python manage.py collectstatic --noinput` pour que Nginx serve le fichier.

### Correction 7 : file d'attente fiable pour les envois (terminée sur le PC)
- Avant : l'API lançait l'envoi dans un thread de gunicorn (perdu à chaque redémarrage, vidéo bloquée « En cours ») ;
  le formulaire du site envoyait pendant la requête (page bloquée, coupure à 300 s) et ne vérifiait ni la limite
  de 5 envois par jour ni la connexion de la chaîne.
- Après :
  - youtube_uploader/envois.py : `probleme_avant_envoi` (vérifications communes API + formulaire),
    `prendre_prochaine_video` (réservation atomique : une vidéo n'est jamais prise deux fois), `envoyer`,
    `marquer_envois_interrompus` (au démarrage : « en cours » → échec avec message, pas de renvoi automatique
    pour éviter un doublon sur YouTube).
  - Commande `python manage.py traiter_envois` (le worker) : boucle, attend 5 s quand la file est vide, termine la
    vidéo en cours avant de s'arrêter (SIGTERM). Option `--une-fois` pour les tests.
  - api.py : plus de thread ; la vidéo est enregistrée « en attente », réponse 202 inchangée.
  - views.py : le formulaire vérifie limite + chaîne, enregistre puis redirige vers /youtube/video/<id>/
    (nouvelle page de suivi, rechargée toutes les 10 s tant que l'envoi n'est pas fini ; 404 pour un autre).
  - base.html : nouveau bloc `{% block entete %}` dans <head>.
- Pas de migration, pas de nouveau paquet, settings.py non modifié.
- Tests : 47 OK (WorkerTests 4, FormulaireEnvoiTests 4 ; les tests API ne simulent plus de thread).
- Au déploiement : créer le service systemd youtube-worker (sinon les vidéos restent « en attente »).

### Correction 8 : redirection après l'inscription (terminée)
- Avant : après l'inscription, l'utilisateur (déjà connecté) était renvoyé vers la page de connexion.
- Après : accounts/views.py `inscription` → message « Bienvenue ! Ton compte est créé. Connecte maintenant ta chaîne
  YouTube. » et redirection vers `accueil`.
- Test ajouté : `test_inscription_mene_a_l_accueil_connecte`. 48 tests OK.

### Correction 9 : README, .env.example et include (terminée)
- README.md réécrit en UTF-8 (avant : UTF-16, seulement le titre en double) : rôle des apps, installation,
  tests, services du serveur, secrets.
- .env.example créé (noms des variables et commentaires, aucune valeur secrète) : DJANGO_SECRET_KEY, DJANGO_DEBUG,
  DJANGO_ALLOWED_HOSTS, TOKEN_ENCRYPTION_KEY, OAUTH_REDIRECT_URI, MCP_ADRESSE_API.
- blog/urls.py : `name='accounts'` retiré de l'include (Django l'ignorait).
- CLAUDE.md (avec l'accord de Samba) : les 3 phrases sur « régénérer la clé » suivent la correction 4
  (empreinte en base, clé visible une seule fois, « créer une nouvelle clé »).
- 48 tests OK.

### Correction 10 : connecteur MCP protégé contre le DNS rebinding (terminée)
- Avant : `adresse_autorisee()` vérifiait l'adresse avec une 1re question au DNS, puis `requests.get()` reposait la
  question. Un domaine piégé pouvait répondre « public » puis « 127.0.0.1 » → lecture d'un service interne.
  Aussi : variables HTTP_PROXY prises en compte, et messages « Problème de connexion : {détail technique} ».
- Après (mcp_server.py) :
  - `SeulementPublique._new_conn` vérifie l'adresse IP réellement connectée (`getpeername`) avant l'envoi de la
    requête ; classes ConnexionHttp/ConnexionHttps, PoolHttp/PoolHttps, AdaptateurPublic (urllib3 déjà installé).
  - `session_de_telechargement()` : `trust_env = False` (proxys ignorés), adaptateur public pour http et https.
  - `telecharger()` utilise cette session ; refus → « Lien refusé : il doit être public » + avertissement au journal.
  - `adresse_autorisee()` gardée comme premier filtre (refus rapide).
  - Messages réseau : `MESSAGE_CONNEXION` (« Problème de connexion. Réessaie dans un instant. »), détail au journal.
  - Les appels vers notre propre API (ADRESSE_API) ne changent pas.
- Tests : youtube_uploader/tests_mcp.py (4 tests : lien interne refusé ; DNS trompé mais connexion à 127.0.0.1
  refusée sans qu'aucune requête n'atteigne le serveur local ; proxys ignorés ; message sans détail). Sautés si le
  paquet mcp n'est pas installé (cas du PC) ; vérifiés sur le PC avec des modules factices : 4 OK. Lien public réel
  (example.com en http et https) toujours téléchargé.
- `manage.py test` sur le PC : 52 tests, OK (4 sautés).
- Au déploiement : `sudo systemctl restart youtube-mcp`, puis lancer les tests sur le serveur (mcp y est installé).

### Correction 11 : fichier de contrôle gunicorn propre à chaque site (terminée sur le serveur, 27 octobre 2026)
- Avant : gunicorn 26.2 place par défaut son fichier de contrôle dans /run/user/1000/gunicorn.ctl ; ce dossier
  n'existe pas pour un service systemd → les deux sites utilisaient /home/batch/.gunicorn/gunicorn.ctl.
- Après (fichiers systemd du serveur, pas de code) :
  - youtube-uploader.service, ligne ExecStart : ajout de `--control-socket /run/youtube-uploader/gunicorn.ctl`
    (RuntimeDirectory=youtube-uploader existait déjà). Prend effet au prochain redémarrage (déploiement).
  - batchcodeia.service : ajout de `RuntimeDirectory=batchcodeia` et `--control-socket /run/batchcodeia/gunicorn.ctl`
    (sauvegarde : ~/batchcodeia.service.bak). Vérifié avant : la version de gunicorn du venv batchcodeia connaît l'option.
- Commandes : `sudo systemctl daemon-reload`, `sudo systemctl restart batchcodeia` → active,
  /run/batchcodeia/gunicorn.ctl présent, https://batchcodeia.com/ → 200.
- Piège rencontré : une commande `sed` qui AJOUTE du texte, lancée plusieurs fois, l'ajoute plusieurs fois
  (--control-socket s'est retrouvé 3 fois). Corrigé en remplaçant toute la ligne ExecStart. Pour le serveur,
  préférer des commandes qui donnent le même résultat même lancées deux fois.

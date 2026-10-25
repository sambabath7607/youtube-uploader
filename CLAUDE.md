# Règles du projet YouTube Uploader

## Communication
- Réponds toujours en français simple.
- Avant chaque modification, explique ce que tu vas faire et pourquoi, puis attends mon accord.
- Une seule étape à la fois. Après chaque étape, résume les fichiers modifiés.

## Structure
- App accounts : comptes, connexion, page d'accueil, clé d'API.
- App youtube_uploader : connexion YouTube, vidéos, envois.
- views.py pour les pages HTML, api.py pour l'API JSON (Django REST Framework).
- Templates dans le dossier src/template/ : template/accounts/ et template/youtube_uploader/.

## Conventions
- Toujours utiliser le name des URL ({% url 'nom' %}, redirect("nom")), jamais d'adresses écrites en dur.
- Toute page privée est protégée par @login_required.
- Un utilisateur ne voit et ne modifie que ses propres données (filtrer par request.user).

## Interdits sans mon accord
- Supprimer un fichier, un modèle ou des données.
- Lancer makemigrations ou migrate.
- Installer un nouveau paquet.
- Modifier settings.py.

## Sécurité
- Ne jamais afficher, copier ni modifier client_secret_web.json, token.json ou YOUTUBE_API_KEY.
- Aucun secret dans le code ni sur GitHub : variables d'environnement, et fichiers secrets dans .gitignore.
- Tokens Google uniquement en base (YouTubeCredentials), chiffrés avant la mise en ligne, jamais dans un fichier ni dans les logs.
- Clés d'API : l'utilisateur peut les voir et les régénérer ; ne jamais les afficher dans les logs.

## Règles YouTube et Google (conditions de l'API)
- Respecter les Conditions d'utilisation des services d'API YouTube, les Règles du programme pour les développeurs YouTube et le Règlement Google sur les données utilisateur des services d'API (usage limité).
- Ne demander que les permissions (scopes) nécessaires : l'envoi de vidéos.
- Utiliser les données Google uniquement pour envoyer les vidéos demandées par l'utilisateur. Jamais de revente, de publicité ou d'entraînement d'IA avec ces données.
- Le site doit indiquer clairement qu'il utilise les services d'API YouTube, avec des liens vers les Conditions d'utilisation de YouTube et les Règles de confidentialité de Google.
- L'utilisateur doit pouvoir déconnecter sa chaîne : supprimer son token en base et le révoquer auprès de Google.
- Ne pas conserver les données venant de YouTube plus longtemps que nécessaire.
- Quota : un envoi coûte cher. Ne jamais envoyer en boucle, ni relancer automatiquement après une erreur.
- Si YouTube renvoie uploadLimitExceeded ou quotaExceeded : s'arrêter et prévenir l'utilisateur.
- Tant que l'application n'est pas vérifiée par Google, les vidéos restent en privé.

## Règles de contenu (responsabilité du créateur)
- « Conçue pour les enfants » : toujours demander à l'utilisateur, jamais choisir à sa place (COPPA, loi américaine). Il en est légalement responsable.
- Contenu généré par IA : demander si la vidéo contient des scènes réalistes modifiées ou synthétiques, pour la déclarer à YouTube.
- Droits d'auteur : uniquement des musiques, images, vidéos et polices libres de droits ou sous licence.
- Ne jamais générer de contenu trompeur, haineux, violent, sexuel, ni de spam, conformément au règlement de la communauté YouTube.
- Titre : 100 caractères maximum. Pas de titre ni de miniature trompeurs.

## Données personnelles (RGPD, LPRPDE au Canada, Loi 25 au Québec)
- Collecter le minimum : nom d'utilisateur, e-mail, token Google, informations des vidéos.
- Supprimer chaque fichier vidéo du serveur dès la fin de l'envoi, réussi ou non.
- Pages obligatoires : politique de confidentialité, conditions d'utilisation, contact.
- L'utilisateur peut voir ses données, les exporter et supprimer son compte, ce qui efface aussi ses tokens et ses vidéos.
- Âge minimum pour créer un compte : 13 ans, ou l'âge exigé par la loi du pays.
- Signaler toute fuite de données aux utilisateurs et aux autorités, comme la loi l'exige.

## Design (UI / UX) — pages HTML uniquement
Inspiration : Human Interface Guidelines d'Apple. Principes : clarté, simplicité, cohérence.

Style général
- Interface sobre et moderne : fond blanc ou gris très clair, beaucoup d'espace vide.
- Une seule couleur d'accent (bleu #007AFF) pour les boutons et les liens. Pas de marron, pas de couleurs criardes, pas de dégradés chargés.
- Texte principal gris très foncé (#1D1D1F), texte secondaire gris (#6E6E73).
- Police système : -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif.
- Coins arrondis (8 à 12 px), ombres très légères, pas de bordures épaisses.
- Espacements multiples de 8 px (8, 16, 24, 32).
- Mode sombre pris en charge avec prefers-color-scheme.

Organisation
- Un seul fichier CSS commun (static/css/style.css) et un template de base (base.html) que toutes les pages étendent.
- Pas de framework CSS (Bootstrap, Tailwind) ni de style écrit dans le HTML sans mon accord.
- Une page = une action principale, avec un seul bouton principal bien visible.

Mobile et accessibilité
- Mobile d'abord : le site doit être parfait sur iPhone, puis s'adapter à l'ordinateur.
- Zones cliquables d'au moins 44 x 44 px.
- Texte d'au moins 16 px (évite aussi le zoom automatique de l'iPhone dans les formulaires).
- Contraste suffisant (norme WCAG AA).
- Chaque champ de formulaire a un label visible ; navigation possible au clavier.

Expérience utilisateur
- Messages clairs en français : succès en vert, erreur en rouge, avec une explication et la solution.
- Montrer l'état des envois avec un badge coloré (en attente, en cours, réussi, échoué).
- Bouton désactivé avec « Envoi en cours… » pendant un envoi, pour éviter les doubles clics.
- Demander une confirmation avant une action irréversible (régénérer la clé, supprimer le compte).
- Bouton « Copier » à côté de la clé d'API.

## Règles de l'API
Adresses et versions
- Toutes les routes commencent par /youtube/api/v1/. Un changement qui casse l'existant = nouvelle version (v2), jamais une modification de v1.
- Noms au pluriel et sans verbe : /videos/, /videos/<id>/. L'action vient de la méthode HTTP (GET lire, POST créer, DELETE supprimer).

Authentification
- Chaque route exige TokenAuthentication et IsAuthenticated.
- Un utilisateur n'accède qu'à ses propres objets ; une vidéo d'un autre renvoie 404, jamais ses données.

Réponses
- Toujours du JSON, toujours passé par un serializer, mêmes noms de champs partout.
- Codes HTTP : 200 lu, 201 créé, 202 accepté (envoi en arrière-plan), 400 données invalides, 401 clé absente ou fausse, 403 interdit, 404 introuvable, 429 trop de requêtes, 500 erreur du serveur.
- Format d'erreur unique : {"erreur": "message clair en français", "code": "nom_court"}.
- Ne jamais renvoyer de trace Python, de chemin de fichier du serveur, de token ni de secret.
- Listes paginées (20 éléments par page).

Validation et limites
- Vérifier chaque donnée dans le serializer : titre 100 caractères max, pour_enfants obligatoire, fichier vidéo uniquement (mp4, mov, webm), taille maximale définie.
- Limiter le nombre de requêtes par utilisateur (throttling DRF) et le nombre d'envois par jour.

Documentation
- Chaque nouvelle route est documentée : adresse, méthode, champs, exemple curl, exemple de réponse, erreurs possibles.
- Mettre à jour la section « Envoi de vidéos par l'API » de ce fichier quand l'API change.

## Qualité du code
Avant de coder
- Lire les fichiers concernés et le code existant ; réutiliser ce qui existe au lieu de dupliquer.
- Proposer un plan court, attendre mon accord.

Pendant
- Code simple et lisible, noms en français cohérents avec le projet (titre, etat, pour_enfants).
- Une fonction = une tâche. Commentaires courts seulement là où le code n'est pas évident.
- Gérer les erreurs avec try/except là où un service externe peut échouer (Google, YouTube), et enregistrer l'erreur dans le modèle.

Après
- Écrire ou mettre à jour un test (tests.py) pour chaque nouvelle fonctionnalité, et lancer python manage.py test.
- Lancer python manage.py check.
- Me donner les commandes pour tester moi-même, une action à la fois.
- Ne jamais dire que c'est terminé sans l'avoir vérifié.

## Envoi de vidéos par l'API
RÈGLE OBLIGATOIRE : avant chaque envoi, demande à l'utilisateur :
1. « Cette vidéo est-elle conçue pour les enfants ? (oui / non) »
2. « Contient-elle des scènes réalistes générées ou modifiées par IA ? (oui / non) »
Attends ses réponses. Ne choisis jamais à sa place, même pour un test.
(L'API refuse d'ailleurs un envoi sans pour_enfants : erreur 400.)

Envoyer une vidéo — POST /youtube/api/v1/videos/ (le serveur Django doit être lancé) :
curl -X POST http://127.0.0.1:8000/youtube/api/v1/videos/ -H "Authorization: Token $YOUTUBE_API_KEY" -F "titre=TITRE" -F "description=DESCRIPTION" -F "pour_enfants=REPONSE_DE_L_UTILISATEUR" -F "fichier=@CHEMIN_DE_LA_VIDEO"
- Champs : titre (obligatoire, 100 caractères max), description (facultatif), pour_enfants (true/false, obligatoire), fichier (mp4, mov ou webm, 500 Mo max).
- Réponse 202 : {"id": 7, "titre": "...", "description": "...", "pour_enfants": false, "etat": "en_attente", "youtube_id": "", "erreur": "", "created_at": "..."}

Suivre un envoi — GET /youtube/api/v1/videos/ID/ :
curl http://127.0.0.1:8000/youtube/api/v1/videos/ID/ -H "Authorization: Token $YOUTUBE_API_KEY"
Répète au maximum une fois toutes les 10 secondes, jusqu'à ce que "etat" vaille "reussi" ou "echoue", puis donne le résultat à l'utilisateur.

Lister mes vidéos — GET /youtube/api/v1/videos/ (20 par page, ?page=2 pour la suite) :
curl http://127.0.0.1:8000/youtube/api/v1/videos/ -H "Authorization: Token $YOUTUBE_API_KEY"
Réponse 200 : {"count": 12, "next": "...", "previous": null, "results": [ ... ]}
Avant un envoi, vérifie dans cette liste qu'une vidéo avec le même titre n'a pas déjà été envoyée.

Erreurs possibles : {"erreur": "message", "code": "nom_court"}
- 400 donnees_invalides (détail dans "details"), 400 youtube_non_connecte : l'utilisateur doit connecter sa chaîne sur le site.
- 401 : clé absente ou fausse (vérifier YOUTUBE_API_KEY, ou la régénérer sur /ma-cle/).
- 404 video_introuvable.
- 429 limite_envois_atteinte (5 envois par jour) ou trop de requêtes (60 par minute) : s'arrêter et prévenir l'utilisateur.
- "etat": "echoue" avec uploadLimitExceeded ou quotaExceeded dans "erreur" : s'arrêter, ne pas relancer, prévenir l'utilisateur.


## cfgh
RÈGLE N°1 : confirmation obligatoire
Avant TOUTE modification de fichier (création, modification, suppression) ou commande qui change quelque chose :

Explique en français simple ce que tu vas faire et dans quel fichier.
Montre le code exact que tu vas écrire.
Attends que Samba réponde « oui » ou « d'accord ».
Une seule modification à la fois. Sans réponse claire, ne fais rien.
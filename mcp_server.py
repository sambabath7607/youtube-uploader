"""Connecteur MCP multi-utilisateurs pour l'API YouTube Uploader.

Chaque utilisateur envoie SA clé d'API du site dans l'en-tête Authorization
(« Token SA_CLE »). Le connecteur la transmet telle quelle à l'API Django :
les vidéos partent donc sur la chaîne de cet utilisateur, et les limites
de l'API (5 envois par jour, 60 requêtes par minute) s'appliquent à chacun.
Les vidéos sont fabriquées sur nos serveurs (fabriquer_video) : l'agent IA n'a besoin d'aucun terminal,
il marche aussi depuis claude.ai, ChatGPT ou un téléphone.

Ajout dans Claude Code (terminal) :
claude mcp add --transport http youtube-uploader https://api.batchcodeia.com/mcp --header "Authorization: Token TA_CLE"
"""
import contextvars
import ipaddress
import json
import logging
import os
import socket
import tempfile
from urllib.parse import urljoin, urlparse

import anyio
import requests
import uvicorn
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

ADRESSE_API = os.environ.get("MCP_ADRESSE_API", "https://api.batchcodeia.com/youtube/api/v1/videos/")
ADRESSE_PUBLIQUE = os.environ.get("MCP_ADRESSE_PUBLIQUE", "https://api.batchcodeia.com")   # pour le 401 OAuth
ADRESSE_VOIX = ADRESSE_API.replace("/videos/", "/voix/")
ADRESSE_FABRICATIONS = ADRESSE_API.replace("/videos/", "/fabrications/")
ADRESSE_MODELES = ADRESSE_API.replace("/videos/", "/modeles/")
ADRESSE_COMPTE = ADRESSE_API.replace("/videos/", "/compte/")
TAILLE_MAX = 500 * 1024 * 1024
HOTE, PORT = "127.0.0.1", 8100
MESSAGE_CONNEXION = "Problème de connexion. Réessaie dans un instant."

logger = logging.getLogger("mcp_server")

# Clé de l'utilisateur de la requête en cours (remplie par VerifierCle)
cle_courante = contextvars.ContextVar("cle_courante", default=None)
# Au plus 2 téléchargements en même temps, pour protéger le disque et la mémoire
telechargements = anyio.Semaphore(2)

try:
    mcp = FastMCP("YouTube Uploader", host=HOTE, port=PORT, stateless_http=True, json_response=True)
except TypeError:
    mcp = FastMCP("YouTube Uploader")


# ---------- outils internes ----------

def entetes(cle):
    return {"Authorization": cle}


def lire_reponse(reponse):
    try:
        return reponse.json()
    except ValueError:
        return {"erreur": f"Réponse inattendue du site (code {reponse.status_code})."}


def cle_ou_erreur():
    cle = cle_courante.get()
    if not cle:
        return None, {"erreur": "Clé d'API manquante.", "code": "non_authentifie"}
    return cle, None


def adresse_autorisee(url):
    """Refuse les adresses internes (127.0.0.1, réseau privé, métadonnées du serveur…)."""
    morceaux = urlparse(url)
    if morceaux.scheme not in ("http", "https") or not morceaux.hostname:
        return False
    try:
        adresses = socket.getaddrinfo(morceaux.hostname, None)
    except socket.gaierror:
        return False
    for adresse in adresses:
        ip = ipaddress.ip_address(adresse[4][0])
        if not ip.is_global:
            return False
    return True


class AdresseInterdite(ConnectionError):
    pass


class SeulementPublique:
    """Vérifie l'adresse IP réellement connectée (pas une 2e réponse du DNS) avant tout envoi."""

    def _new_conn(self):
        sock = super()._new_conn()
        if not ipaddress.ip_address(sock.getpeername()[0]).is_global:
            sock.close()
            raise AdresseInterdite("adresse interne refusée")
        return sock


class ConnexionHttp(SeulementPublique, HTTPConnection):
    pass


class ConnexionHttps(SeulementPublique, HTTPSConnection):
    pass


class PoolHttp(HTTPConnectionPool):
    ConnectionCls = ConnexionHttp


class PoolHttps(HTTPSConnectionPool):
    ConnectionCls = ConnexionHttps


class AdaptateurPublic(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": PoolHttp, "https": PoolHttps}


def causes(erreur):
    """L'erreur et toutes celles qui l'ont provoquée (requests enveloppe l'erreur de urllib3)."""
    vues, a_voir = set(), [erreur]
    while a_voir:
        e = a_voir.pop()
        if not isinstance(e, BaseException) or id(e) in vues:
            continue
        vues.add(id(e))
        yield e
        a_voir += [e.__cause__, e.__context__, getattr(e, "reason", None), *e.args]


def session_de_telechargement():
    session = requests.Session()
    session.trust_env = False                 # ignore HTTP_PROXY / HTTPS_PROXY
    session.mount("http://", AdaptateurPublic())
    session.mount("https://", AdaptateurPublic())
    return session


def telecharger(url, fichier):
    """Télécharge la vidéo dans le fichier temporaire. Renvoie un message d'erreur, ou None."""
    session = session_de_telechargement()
    for _ in range(4):  # suit au plus 3 redirections, en vérifiant chaque adresse
        if not adresse_autorisee(url):
            return "Lien refusé : il doit être public (http ou https)."
        try:
            reponse = session.get(url, stream=True, timeout=60, allow_redirects=False)
        except requests.ConnectionError as e:
            # L'adresse réellement connectée était interne (DNS rebinding) : refus
            if any(isinstance(cause, AdresseInterdite) for cause in causes(e)):
                logger.warning("Téléchargement refusé : adresse interne derrière %s", urlparse(url).hostname)
                return "Lien refusé : il doit être public (http ou https)."
            raise
        with reponse:
            if reponse.status_code in (301, 302, 303, 307, 308) and reponse.headers.get("Location"):
                url = urljoin(url, reponse.headers["Location"])
                continue
            if reponse.status_code != 200:
                return f"Impossible de télécharger la vidéo (code {reponse.status_code})."
            taille = 0
            for morceau in reponse.iter_content(1024 * 1024):
                taille += len(morceau)
                if taille > TAILLE_MAX:
                    return "Vidéo trop lourde (500 Mo maximum)."
                fichier.write(morceau)
            return None
    return "Trop de redirections."


def envoyer(cle, url_video, titre, description, pour_enfants, contenu_ia, visibilite="private"):
    extension = os.path.splitext(urlparse(url_video).path)[1].lower() or ".mp4"
    try:
        with tempfile.NamedTemporaryFile(suffix=extension) as fichier:
            probleme = telecharger(url_video, fichier)
            if probleme:
                return {"erreur": probleme}
            fichier.flush()
            fichier.seek(0)
            reponse = requests.post(
                ADRESSE_API,
                headers=entetes(cle),
                data={
                    "titre": titre,
                    "description": description,
                    "pour_enfants": "true" if pour_enfants else "false",
                    "contenu_ia": "true" if contenu_ia else "false",
                    "visibilite": visibilite,
                },
                # fichier.file : le vrai fichier (requests refuse l'enveloppe NamedTemporaryFile, bug du 31/10)
                files={"fichier": (f"video{extension}", fichier.file)},
                timeout=300,
            )
    except requests.RequestException:
        logger.exception("Envoi vers l'API : problème de connexion")
        return {"erreur": MESSAGE_CONNEXION}
    return lire_reponse(reponse)


def lire(cle, url, params=None):
    try:
        return lire_reponse(requests.get(url, headers=entetes(cle), params=params, timeout=30))
    except requests.RequestException:
        logger.exception("Lecture de l'API : problème de connexion")
        return {"erreur": MESSAGE_CONNEXION}



def ecrire(cle, url, donnees):
    try:
        return lire_reponse(requests.post(url, headers=entetes(cle), json=donnees, timeout=60))
    except requests.RequestException:
        logger.exception("Écriture vers l'API : problème de connexion")
        return {"erreur": MESSAGE_CONNEXION}


# ---------- outils visibles par Claude ----------

@mcp.tool()
async def envoyer_video(url_video: str, titre: str, pour_enfants: bool, contenu_ia: bool, description: str = "",
                        visibilite: str = "private") -> dict:
    """Publie sur la chaîne YouTube de l'utilisateur une vidéo DÉJÀ FAITE qui a un lien public.
    Pour créer une nouvelle vidéo, utilise plutôt fabriquer_video (fabriquée sur nos serveurs).

    Avant d'appeler cet outil, demande TOUJOURS à l'utilisateur :
    1. si la vidéo est conçue pour les enfants (pour_enfants) ;
    2. si elle contient des scènes réalistes générées ou modifiées par IA (contenu_ia).
    Ne choisis jamais à sa place, même pour un test.
    visibilite : « private » (privée, par défaut), « unlisted » (non répertoriée) ou « public » : demande-lui.

    url_video : lien direct et public vers le fichier vidéo (mp4, mov ou webm, 500 Mo maximum).
    titre : 100 caractères maximum.
    La réponse contient un "id" : utilise ensuite etat_video pour suivre l'envoi.
    """
    cle, probleme = cle_ou_erreur()
    if probleme:
        return probleme
    async with telechargements:
        return await anyio.to_thread.run_sync(envoyer, cle, url_video, titre, description, pour_enfants, contenu_ia,
                                              visibilite)


@mcp.tool()
async def etat_video(video_id: int) -> dict:
    """Donne l'état d'une vidéo et l'ID YouTube une fois réussie (lien : https://youtu.be/ID).

    États : fabrication (sur nos serveurs ; "etape" dit où on en est : « Voix en cours », « Rendu 7/12 »,
    « Assemblage »…), fabrication_echouee, en_attente et en_cours (envoi YouTube), reussi ou echoue.
    Ne pas appeler plus d'une fois toutes les 15 secondes ; donne l'étape à l'utilisateur quand elle change.
    Si l'erreur contient uploadLimitExceeded ou quotaExceeded, arrête-toi et préviens l'utilisateur.
    """
    cle, probleme = cle_ou_erreur()
    if probleme:
        return probleme
    return await anyio.to_thread.run_sync(lire, cle, f"{ADRESSE_API}{video_id}/")


@mcp.tool()
async def mes_videos(page: int = 1) -> dict:
    """Liste les vidéos déjà envoyées par l'utilisateur (20 par page). Utile pour éviter les doublons."""
    cle, probleme = cle_ou_erreur()
    if probleme:
        return probleme
    return await anyio.to_thread.run_sync(lire, cle, ADRESSE_API, {"page": page})


# ---------- vérification de la clé à chaque requête ----------

class VerifierCle:
    """Refuse toute requête sans clé, et garde la clé de l'utilisateur pour les outils."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        entetes = dict(scope.get("headers") or [])
        valeur = entetes.get(b"authorization", b"").decode().strip()
        # « Bearer … » = jeton de la connexion en un clic (OAuth) : transmis tel quel, l'API le vérifie
        # claude.ai (« Request headers ») ne permet pas Authorization : la clé peut arriver dans X-API-Key
        if not valeur:
            cle_x = entetes.get(b"x-api-key", b"").decode().strip()
            if cle_x:
                valeur = cle_x if cle_x.lower().startswith("token ") else "Token " + cle_x
        if not valeur.lower().startswith(("token ", "bearer ")) or len(valeur) < 10:
            corps = json.dumps({
                "erreur": "Connexion requise : connecte-toi en un clic (OAuth) ou ajoute ta clé dans l'en-tête "
                          "« X-API-Key: TA_CLE » (page « Mes clés » du site).",
                "code": "non_authentifie",
            }).encode()
            # Spécification MCP : le 401 indique où trouver le serveur de connexion (RFC 9728)
            defi = f'Bearer resource_metadata="{ADRESSE_PUBLIQUE}/.well-known/oauth-protected-resource/mcp", scope="videos"'
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"), (b"www-authenticate", defi.encode())]})
            await send({"type": "http.response.body", "body": corps})
            return
        jeton = cle_courante.set(valeur)
        try:
            await self.app(scope, receive, send)
        finally:
            cle_courante.reset(jeton)


@mcp.tool()
async def fabriquer_voix(texte: str) -> dict:
    """Lit un texte avec LA VOIX DE L'UTILISATEUR (enregistrée sur la page « Ma voix » du site) et donne
    seulement l'AUDIO (lien wav valable 24 h).

    Pour une VIDÉO, n'utilise pas cet outil : appelle directement fabriquer_video(avec_ma_voix=true), qui fabrique
    la voix et la vidéo ensemble sur nos serveurs.
    Paragraphes séparés par une ligne vide (lus en même temps, environ 1 à 2 minutes). Ensuite, etat_voix(travail)
    toutes les 15 secondes jusqu'à "pret" : "url_audio" et "minutage" (début et durée de chaque paragraphe).
    Erreurs : voix_absente ou mode_voix (l'utilisateur doit régler sa voix sur le site), quota_voix_atteint (s'arrêter et prévenir).
    """
    cle, probleme = cle_ou_erreur()
    if probleme:
        return probleme
    return await anyio.to_thread.run_sync(ecrire, cle, ADRESSE_VOIX, {"texte": texte})


@mcp.tool()
async def etat_voix(travail: str) -> dict:
    """Donne l'état d'une lecture lancée par fabriquer_voix : en_cours, pret (avec url_audio et minutage) ou echoue.

    Ne pas appeler plus d'une fois toutes les 15 secondes.
    """
    cle, probleme = cle_ou_erreur()
    if probleme:
        return probleme
    return await anyio.to_thread.run_sync(lire, cle, f"{ADRESSE_VOIX}{travail}/")


@mcp.tool()
async def modeles_video() -> dict:
    """Liste les modèles de vidéos (lecon, astuces, presentation, short) : description, format, durée maximale,
    types de scène permis, et un exemple complet de champs remplis. Appelle-le avant le premier fabriquer_video
    de la conversation pour savoir exactement quoi remplir."""
    cle, probleme = cle_ou_erreur()
    if probleme:
        return probleme
    return await anyio.to_thread.run_sync(lire, cle, ADRESSE_MODELES)


@mcp.tool()
async def fabriquer_video(modele: str, script: str, scenes: list[dict], titre: str, pour_enfants: bool,
                          contenu_ia: bool, avec_ma_voix: bool = True, visibilite: str = "private",
                          description: str = "", accent: str = "#3B8BFF", musique: str = "calme") -> dict:
    """Fabrique une vidéo SUR NOS SERVEURS (voix, animation, montage) puis la publie sur la chaîne YouTube de
    l'utilisateur. Rien à installer, aucune commande : marche depuis claude.ai, ChatGPT, un téléphone ou Claude Code.

    Marche à suivre RAPIDE :
    1. mon_compte() : chaîne connectée (dis à l'utilisateur sur quelle chaîne la vidéo partira), voix, préférences.
    2. modeles_video() si tu ne connais pas encore les champs. Choisis le modèle : lecon, astuces, presentation,
       short (vertical, 60 s max).
    3. Écris le script (un paragraphe = une scène, paragraphes séparés par une ligne vide) et, pour chaque
       paragraphe, une scène : {"type": "titre"|"texte"|"points"|"code"|"fin", "texte": "...", "points": [...],
       "code": "...", "langage": "python"}. Montre le plan à l'utilisateur et attends son accord.
    4. Réponses obligatoires de YouTube : regarde mon_compte() → preferences_publication. Pour chaque réponse
       enregistrée, utilise-la sans redemander et rappelle-la ; pour chaque valeur null, demande :
       pour_enfants (vidéo conçue pour les enfants ?), contenu_ia (scènes réalistes générées par IA ?),
       visibilite (private, unlisted ou public). Ne choisis jamais à sa place.
       Avec sa voix (avec_ma_voix = true), contenu_ia vaut toujours true (une voix clonée est un contenu IA).
    5. Appelle fabriquer_video : la réponse contient "id". Puis etat_video(id) toutes les 15 secondes : etat
       « fabrication » (avec "etape"), puis « en_attente »/« en_cours » (envoi YouTube), enfin « reussi » :
       donne le lien https://youtu.be/<youtube_id>.
    Erreurs : donnees_invalides (lis "details" et corrige les champs), video_trop_longue (raccourcis le script),
    fabrication_en_cours (une seule vidéo à la fois), voix_absente / mode_voix (régler la voix sur le site),
    quota_voix_atteint, limite_envois_atteinte, limite_service_atteinte (s'arrêter et prévenir l'utilisateur).
    """
    cle, probleme = cle_ou_erreur()
    if probleme:
        return probleme
    donnees = {"modele": modele, "script": script, "scenes": scenes, "titre": titre, "pour_enfants": pour_enfants,
               "contenu_ia": contenu_ia, "avec_ma_voix": avec_ma_voix, "visibilite": visibilite,
               "description": description, "accent": accent, "musique": musique}
    return await anyio.to_thread.run_sync(ecrire, cle, ADRESSE_FABRICATIONS, donnees)


@mcp.tool()
async def mon_compte() -> dict:
    """Résumé du compte de l'utilisateur : chaîne YouTube connectée (et son nom), voix enregistrée,
    minutes de voix restantes ce mois-ci, tests de voix et envois restants aujourd'hui,
    et ses préférences de publication (réponses par défaut aux questions de YouTube : null = lui demander).
    Utilise-le avant fabriquer_video, et quand l'utilisateur demande ce qu'il lui reste.
    Indique-lui toujours le nom de la chaîne sur laquelle la vidéo va partir (s'il est connu)."""
    cle, probleme = cle_ou_erreur()
    if probleme:
        return probleme
    return await anyio.to_thread.run_sync(lire, cle, ADRESSE_COMPTE)


# Toujours à la toute fin du fichier : le serveur démarre seulement quand TOUS les outils sont déclarés
if __name__ == "__main__":
    uvicorn.run(VerifierCle(mcp.streamable_http_app()), host=HOTE, port=PORT, log_level="info")

"""Connecteur MCP multi-utilisateurs pour l'API YouTube Uploader.

Chaque utilisateur envoie SA clé d'API du site dans l'en-tête Authorization
(« Token SA_CLE »). Le connecteur la transmet telle quelle à l'API Django :
les vidéos partent donc sur la chaîne de cet utilisateur, et les limites
de l'API (5 envois par jour, 60 requêtes par minute) s'appliquent à chacun.

Ajout dans Claude Code :
claude mcp add --transport http youtube-uploader https://api.batchcodeia.com/mcp --header "Authorization: Token TA_CLE"
"""
import contextvars
import ipaddress
import json
import os
import socket
import tempfile
from urllib.parse import urljoin, urlparse

import anyio
import requests
import uvicorn
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

ADRESSE_API = os.environ.get("MCP_ADRESSE_API", "https://api.batchcodeia.com/youtube/api/v1/videos/")
TAILLE_MAX = 500 * 1024 * 1024
HOTE, PORT = "127.0.0.1", 8100

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


def telecharger(url, fichier):
    """Télécharge la vidéo dans le fichier temporaire. Renvoie un message d'erreur, ou None."""
    for _ in range(4):  # suit au plus 3 redirections, en vérifiant chaque adresse
        if not adresse_autorisee(url):
            return "Lien refusé : il doit être public (http ou https)."
        with requests.get(url, stream=True, timeout=60, allow_redirects=False) as reponse:
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


def envoyer(cle, url_video, titre, description, pour_enfants, contenu_ia):
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
                },
                files={"fichier": (f"video{extension}", fichier)},
                timeout=300,
            )
    except requests.RequestException as e:
        return {"erreur": f"Problème de connexion : {e}"}
    return lire_reponse(reponse)


def lire(cle, url, params=None):
    try:
        return lire_reponse(requests.get(url, headers=entetes(cle), params=params, timeout=30))
    except requests.RequestException as e:
        return {"erreur": f"Problème de connexion : {e}"}


# ---------- outils visibles par Claude ----------

@mcp.tool()
async def envoyer_video(url_video: str, titre: str, pour_enfants: bool, contenu_ia: bool, description: str = "") -> dict:
    """Envoie une vidéo sur la chaîne YouTube de l'utilisateur (en privé).

    Avant d'appeler cet outil, demande TOUJOURS à l'utilisateur :
    1. si la vidéo est conçue pour les enfants (pour_enfants) ;
    2. si elle contient des scènes réalistes générées ou modifiées par IA (contenu_ia).
    Ne choisis jamais à sa place, même pour un test.

    url_video : lien direct et public vers le fichier vidéo (mp4, mov ou webm, 500 Mo maximum).
    titre : 100 caractères maximum.
    La réponse contient un "id" : utilise ensuite etat_video pour suivre l'envoi.
    """
    cle, probleme = cle_ou_erreur()
    if probleme:
        return probleme
    async with telechargements:
        return await anyio.to_thread.run_sync(envoyer, cle, url_video, titre, description, pour_enfants, contenu_ia)


@mcp.tool()
async def etat_video(video_id: int) -> dict:
    """Donne l'état d'un envoi (en_attente, en_cours, reussi ou echoue) et l'ID YouTube une fois réussi.

    Ne pas appeler plus d'une fois toutes les 10 secondes. Si l'erreur contient
    uploadLimitExceeded ou quotaExceeded, arrête-toi et préviens l'utilisateur.
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
        valeur = dict(scope.get("headers") or []).get(b"authorization", b"").decode().strip()
        if valeur.lower().startswith("bearer "):
            valeur = "Token " + valeur[7:].strip()
        if not valeur.lower().startswith("token ") or len(valeur) < 10:
            corps = json.dumps({
                "erreur": "Clé d'API manquante. Ajoute l'en-tête « Authorization: Token TA_CLE » (page « Ma clé d'API » du site).",
                "code": "non_authentifie",
            }).encode()
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": corps})
            return
        jeton = cle_courante.set(valeur)
        try:
            await self.app(scope, receive, send)
        finally:
            cle_courante.reset(jeton)


if __name__ == "__main__":
    uvicorn.run(VerifierCle(mcp.streamable_http_app()), host=HOTE, port=PORT, log_level="info")

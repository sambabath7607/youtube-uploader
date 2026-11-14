"""Journaux sans secret et alertes par courriel (lot 5).

Chargé par la configuration LOGGING de settings.py, avant les applications : aucun import de modèle en haut du fichier.
"""
import logging
import os
import re
import threading

# Variables d'environnement secrètes : leur valeur est masquée si elle apparaît dans un message
VARIABLES_SECRETES = ("DJANGO_SECRET_KEY", "TOKEN_ENCRYPTION_KEY", "PONT_SECRET", "MODAL_TOKEN_ID",
                      "MODAL_TOKEN_SECRET", "EMAIL_HOST_PASSWORD", "YOUTUBE_API_KEY", "SAUVEGARDE_CLE")
MASQUE = "***"

MOTIFS = [
    # clés d'API et jetons dans un en-tête : « Token abc… », « Bearer abc… », « X-API-Key: abc… »
    (re.compile(r"\b(Token|Bearer)\s+[A-Za-z0-9._~+/=\-]{8,}", re.I), r"\1 " + MASQUE),
    (re.compile(r"(x-api-key|authorization)([\"']?\s*[:=]\s*[\"']?)(?!Token\b|Bearer\b)[^\s\"',}]+", re.I),
     r"\1\2" + MASQUE),
    # jetons Google (accès « ya29.… », renouvellement « 1//… ») et champs JSON sensibles
    (re.compile(r"ya29\.[A-Za-z0-9._\-]+"), MASQUE),
    (re.compile(r"\b1//[A-Za-z0-9._\-]{10,}"), MASQUE),
    (re.compile(r"([\"']?(?:access_token|refresh_token|client_secret|password|mot_de_passe|token_json|secret)[\"']?"
                r"\s*[:=]\s*[\"']?)[^\s\"',}&]+", re.I), r"\1" + MASQUE),
    # paramètres secrets dans une adresse (?code=…, &token=…)
    (re.compile(r"([?&](?:code|token|access_token|refresh_token|key|cle|state)=)[^&\s\"']+", re.I), r"\1" + MASQUE),
    # liens secrets du site : dépôt à usage unique et « nouveau mot de passe »
    (re.compile(r"(/depot/)[^/\s\"']+"), r"\1" + MASQUE),
    (re.compile(r"(/nouveau-mot-de-passe/)(?!termine/)[^/\s\"']+/[^/\s\"']+"), r"\1" + MASQUE),
]


def masquer(texte):
    """Retire d'un texte tout ce qui ressemble à un secret (valeurs du .env, clés, jetons, liens secrets)."""
    if not texte:
        return texte
    texte = str(texte)
    for nom in VARIABLES_SECRETES:
        valeur = os.environ.get(nom, "")
        if len(valeur) >= 8:
            texte = texte.replace(valeur, MASQUE)
    for motif, remplacement in MOTIFS:
        texte = motif.sub(remplacement, texte)
    return texte


class FiltreSecrets(logging.Filter):
    """Masque les secrets dans le message ET dans la trace de l'erreur, avant tout affichage ou courriel."""

    def filter(self, record):
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        record.msg, record.args = masquer(message), None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = masquer(record.exc_text)
        return True


_local = threading.local()


class AlerteAdmins(logging.Handler):
    """Erreur du service (niveau ERROR) → courriel à ADMINS, une fois par heure au plus pour la même erreur.
    Le courriel ne contient que le message et la trace, déjà passés par FiltreSecrets (aucune donnée de requête)."""

    def emit(self, record):
        if getattr(_local, "en_cours", False):   # une alerte qui échoue ne déclenche pas d'autre alerte
            return
        _local.en_cours = True
        try:
            from .exploitation import alerter
            texte = record.getMessage()
            if record.exc_text:
                texte += "\n\n" + record.exc_text
            # même erreur pour une autre vidéo = même alerte (les numéros ne comptent pas)
            cle = f"journal:{record.name}:{re.sub(r'[0-9]+', '#', str(record.msg))[:80]}"
            alerter(cle, f"Erreur : {record.getMessage()[:120]}", texte)
        except Exception:
            pass   # une panne de l'alerte ne doit jamais casser le site ni le worker
        finally:
            _local.en_cours = False

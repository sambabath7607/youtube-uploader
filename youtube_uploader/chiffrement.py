import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class JetonIllisible(Exception):
    """Le jeton Google en base ne se déchiffre pas (clé changée, ou ancien jeton en clair)."""


def get_fernet():
    cle = os.environ.get("TOKEN_ENCRYPTION_KEY")
    if not cle:
        raise RuntimeError("La variable TOKEN_ENCRYPTION_KEY est absente.")
    return Fernet(cle.encode())


def chiffrer(texte):
    return get_fernet().encrypt(texte.encode()).decode()


def dechiffrer(texte):
    try:
        return get_fernet().decrypt(texte.encode()).decode()
    except InvalidToken:
        # Jamais de repli en clair : le jeton n'est pas affiché, seulement signalé dans le journal du serveur
        logger.error("Jeton Google illisible : TOKEN_ENCRYPTION_KEY a changé ou le jeton n'est pas chiffré.")
        raise JetonIllisible() from None

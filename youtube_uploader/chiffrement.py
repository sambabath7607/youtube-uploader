import os

from cryptography.fernet import Fernet, InvalidToken


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
        # Ancien token enregistré en clair : on le renvoie tel quel
        return texte
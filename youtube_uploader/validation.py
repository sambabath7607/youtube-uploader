import os

# Règles communes au formulaire du site et à l'API
EXTENSIONS_AUTORISEES = [".mp4", ".mov", ".webm"]
TAILLE_MAX_MO = 500
LIMITE_ENVOIS_PAR_JOUR = 5


def probleme_fichier(fichier):
    """Renvoie un message d'erreur si le fichier n'est pas accepté, sinon None."""
    extension = os.path.splitext(fichier.name)[1].lower()
    if extension not in EXTENSIONS_AUTORISEES:
        return "Format refusé. Formats acceptés : mp4, mov, webm."
    if fichier.size > TAILLE_MAX_MO * 1024 * 1024:
        return f"Fichier trop lourd (maximum {TAILLE_MAX_MO} Mo)."
    return None

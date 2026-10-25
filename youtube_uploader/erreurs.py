from rest_framework.views import exception_handler

# Messages clairs pour les erreurs connues de YouTube.
# Le nom de l'erreur reste entre parenthèses, pour que Claude Code la reconnaisse.
MESSAGES_YOUTUBE = {
    "uploadLimitExceeded": "Limite d'envois YouTube du jour atteinte pour cette chaîne. Réessaie dans environ 24 h.",
    "quotaExceeded": "Quota de l'API YouTube épuisé pour aujourd'hui. Réessaie demain.",
}

CODES_HTTP = {
    401: "non_authentifie",
    403: "interdit",
    404: "introuvable",
    405: "methode_refusee",
    429: "trop_de_requetes",
}


def message_erreur(e):
    """Transforme une erreur d'envoi en message lisible en français."""
    from googleapiclient.errors import HttpError
    from .models import YouTubeCredentials

    if isinstance(e, YouTubeCredentials.DoesNotExist):
        return "Aucune chaîne YouTube connectée pour ce compte."
    if isinstance(e, HttpError):
        for detail in getattr(e, "error_details", None) or []:
            raison = detail.get("reason") if isinstance(detail, dict) else None
            if raison in MESSAGES_YOUTUBE:
                return f"{MESSAGES_YOUTUBE[raison]} ({raison})"
        return f"YouTube a refusé l'envoi (code {e.resp.status})."
    return f"Erreur pendant l'envoi : {e}"


def gestionnaire_erreurs_api(exc, context):
    """Met toutes les erreurs de DRF au format {"erreur": ..., "code": ...}.

    Pas encore actif : il faut ajouter dans settings.py
    REST_FRAMEWORK = {"EXCEPTION_HANDLER": "youtube_uploader.erreurs.gestionnaire_erreurs_api"}
    """
    response = exception_handler(exc, context)
    if response is None or not isinstance(response.data, dict) or "erreur" in response.data:
        return response
    if "detail" in response.data:
        response.data = {
            "erreur": str(response.data["detail"]),
            "code": CODES_HTTP.get(response.status_code, "erreur"),
        }
    else:
        response.data = {"erreur": "Données invalides.", "code": "donnees_invalides", "details": response.data}
    return response

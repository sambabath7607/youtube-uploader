import logging

from django.utils import timezone

from .erreurs import message_erreur
from .models import Video, YouTubeCredentials
from .upload import upload_video
from .validation import LIMITE_ENVOIS_PAR_JOUR

logger = logging.getLogger(__name__)

MESSAGE_INTERROMPU = "L'envoi a été interrompu (redémarrage du serveur). Renvoie la vidéo."


def probleme_avant_envoi(user):
    """Vérifications communes à l'API et au formulaire. Renvoie (message, code) ou None."""
    if not YouTubeCredentials.objects.filter(user=user).exists():
        return ("Aucune chaîne YouTube connectée. Connecte ta chaîne sur la page d'accueil du site.",
                "youtube_non_connecte")
    debut_du_jour = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if Video.objects.filter(user=user, created_at__gte=debut_du_jour).count() >= LIMITE_ENVOIS_PAR_JOUR:
        return (f"Limite de {LIMITE_ENVOIS_PAR_JOUR} envois par jour atteinte. Réessaie demain.",
                "limite_envois_atteinte")
    return None


def prendre_prochaine_video():
    """Réserve la plus ancienne vidéo en attente (une seule fois, même avec plusieurs workers)."""
    for video in Video.objects.filter(etat="en_attente").order_by("created_at")[:5]:
        if Video.objects.filter(id=video.id, etat="en_attente").update(etat="en_cours"):
            video.etat = "en_cours"
            return video
    return None


def envoyer(video):
    try:
        video.youtube_id = upload_video(
            video.fichier.path, video.titre, video.description,
            "private", user=video.user,
            pour_enfants=video.pour_enfants, contenu_ia=video.contenu_ia,
        )
        video.etat = "reussi"
    except Exception as e:
        video.etat = "echoue"
        video.erreur = message_erreur(e)
    video.fichier.delete(save=False)
    video.save()


def marquer_envois_interrompus():
    """Au démarrage du worker : une vidéo restée « en cours » a été coupée. On ne la renvoie pas
    automatiquement (risque de doublon sur YouTube) : elle passe en échec avec un message clair."""
    for video in Video.objects.filter(etat="en_cours"):
        video.etat = "echoue"
        video.erreur = MESSAGE_INTERROMPU
        video.fichier.delete(save=False)
        video.save()
        logger.warning("Envoi interrompu marqué en échec (vidéo %s)", video.id)

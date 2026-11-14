import logging
from datetime import timedelta

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
    du_jour = envois_du_jour()
    from accounts.offres import limites   # offres Gratuit / Pro (lot 4)
    limite = limites(user).envois_par_jour
    if du_jour.filter(user=user).count() >= limite:
        return (f"Limite de {limite} envois par jour atteinte. Réessaie demain.",
                "limite_envois_atteinte")
    if du_jour.count() >= limite_service_par_jour():
        # Quota YouTube partagé par tout le service : on s'arrête avant d'atteindre la limite de Google
        from .exploitation import alerter
        alerter("limite_service", "Envois bloqués : limite du service atteinte",
                f"{du_jour.count()} envois aujourd'hui pour tout le service (ENVOIS_SERVICE_PAR_JOUR = "
                f"{limite_service_par_jour()}). Les nouveaux envois sont refusés jusqu'à demain (heure UTC). "
                "Si cela devient fréquent : demander l'augmentation du quota YouTube (tâche G5).")
        return ("Le service a atteint sa limite d'envois YouTube pour aujourd'hui. Réessaie demain.",
                "limite_service_atteinte")
    return None


def envois_du_jour():
    """Vidéos créées aujourd'hui qui partent (ou sont parties) sur YouTube : une fabrication échouée ne compte pas."""
    debut_du_jour = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return Video.objects.filter(created_at__gte=debut_du_jour).exclude(etat="fabrication_echouee")


def limite_service_par_jour():
    from django.conf import settings
    return getattr(settings, "ENVOIS_SERVICE_PAR_JOUR", 90)


def envoi_en_double(user, titre):
    """Un envoi du même titre, pas encore terminé et lancé il y a moins d'1 h : c'est une répétition, pas une nouvelle vidéo."""
    return (Video.objects.filter(user=user, titre=titre, etat__in=["fabrication", "attente_fichier", "reception", "en_attente", "en_cours"],
                                 created_at__gte=timezone.now() - ABANDON_DEPOT)
            .order_by("-created_at").first())


def prendre_prochaine_video():
    """Réserve la plus ancienne vidéo en attente (une seule fois, même avec plusieurs workers)."""
    for video in Video.objects.filter(etat="en_attente").order_by("created_at")[:5]:
        if Video.objects.filter(id=video.id, etat="en_attente").update(etat="en_cours"):
            video.etat = "en_cours"
            return video
    return None


def envoyer(video):
    from google.auth.exceptions import RefreshError
    try:
        reponse = upload_video(
            video.fichier.path, video.titre, video.description,
            video.visibilite, user=video.user,
            pour_enfants=video.pour_enfants, contenu_ia=video.contenu_ia,
        )
        video.youtube_id = reponse["id"]
        video.envoye_le = timezone.now()
        snippet = reponse.get("snippet") or {}
        if snippet.get("channelTitle"):
            YouTubeCredentials.objects.filter(user=video.user).update(
                chaine_titre=snippet["channelTitle"], chaine_id=snippet.get("channelId", ""), chaine_maj_le=timezone.now())
        video.etat = "reussi"
    except Exception as e:
        video.etat = "echoue"
        video.erreur = message_erreur(e)
        alerter_si_cause_service(e, video)
        if isinstance(e, RefreshError):
            # Autorisation retirée chez Google ou expirée : on efface le jeton et les données YouTube (règle de révocation)
            effacer_donnees_youtube(video.user)
            prevenir(video.user, "Reconnecte ta chaîne YouTube",
                     "L'autorisation YouTube a expiré ou a été retirée. Reconnecte ta chaîne sur "
                     "https://api.batchcodeia.com/ puis renvoie ta vidéo.")
    video.fichier.delete(save=False)
    video.save()
    if video.etat == "reussi":
        prevenir(video.user, f"Ta vidéo « {video.titre} » est sur YouTube",
                 f"Ta vidéo est en ligne : https://youtu.be/{video.youtube_id}\n"
                 f"Visibilité : {video.get_visibilite_display()}. Tu peux la modifier dans YouTube Studio.")


def alerter_si_cause_service(e, video):
    """Échec d'envoi : alerte à Samba seulement si le service est en cause (quota YouTube du projet, panne de
    Google, erreur inattendue) ; jamais pour une cause du client (autorisation retirée, limite de sa chaîne)."""
    from google.auth.exceptions import RefreshError
    from googleapiclient.errors import HttpError

    from .chiffrement import JetonIllisible
    from .exploitation import alerter

    if "(quotaExceeded)" in video.erreur:
        alerter("quota_youtube", "Quota YouTube du service atteint",
                "YouTube a répondu quotaExceeded : plus aucun envoi possible aujourd'hui pour tout le service. "
                "Les clients sont prévenus ; rien n'est relancé. Penser à la demande d'augmentation (tâche G5).")
        return
    if isinstance(e, (RefreshError, JetonIllisible)) or "(uploadLimitExceeded)" in video.erreur:
        return   # cause du client (ou de sa chaîne) : il est prévenu, Samba n'a rien à faire
    if not isinstance(e, HttpError):
        return   # erreur inattendue : déjà signalée à Samba par le journal (message_erreur, niveau ERROR)
    if 400 <= e.resp.status < 500 and e.resp.status != 403:
        return   # vidéo refusée par YouTube (fichier, titre…) : le message est donné au client
    alerter(f"envoi_echoue:{e.resp.status}", "Envoi YouTube échoué (cause du service)",
            f"Vidéo n° {video.id} : {video.erreur}\n"
            "Le détail est dans : sudo journalctl -u youtube-worker")


def prevenir(user, sujet, message):
    """Courriel à l'utilisateur (s'il a donné son adresse). Une panne d'envoi ne bloque jamais le worker."""
    if not user.email:
        return
    from django.core.mail import send_mail
    try:
        send_mail(sujet, message, None, [user.email])
    except Exception:
        logger.exception("Courriel non envoyé (%s)", sujet)


def effacer_donnees_youtube(user):
    """Révocation : jeton Google, nom de la chaîne et identifiants des vidéos effacés (règle YouTube : sous 7 jours)."""
    YouTubeCredentials.objects.filter(user=user).delete()
    Video.objects.filter(user=user).exclude(youtube_id="").update(youtube_id="")


# ---------- tâches automatiques du worker ----------

ABANDON_DEPOT = timedelta(hours=1)            # adresse de dépôt donnée mais aucune vidéo reçue
CONSERVATION_DONNEES_YOUTUBE = timedelta(days=30)
NB_SAUVEGARDES = 14


def nettoyer_envois_abandonnes():
    """Envois réservés (preparer_envoi) sans fichier après 1 h : supprimés, ils ne comptent plus dans la limite du jour."""
    limite = timezone.now() - ABANDON_DEPOT
    nombre, _ = Video.objects.filter(etat="attente_fichier", created_at__lt=limite).delete()
    return nombre


def appliquer_regle_30_jours():
    """Règle YouTube (III.E.4) : les données reçues de l'API sont effacées si elles n'ont pas été rafraîchies en 30 jours."""
    limite = timezone.now() - CONSERVATION_DONNEES_YOUTUBE
    videos = Video.objects.filter(envoye_le__lt=limite).exclude(youtube_id="").update(youtube_id="")
    chaines = YouTubeCredentials.objects.filter(chaine_maj_le__lt=limite).update(chaine_titre="", chaine_id="",
                                                                                 chaine_maj_le=None)
    return videos, chaines


def sauvegarder_base(dossier=None, forcer=False):
    """Copie de la base SQLite (fiable même pendant l'utilisation), lisible seulement par le propriétaire ;
    on garde les 14 dernières. Renvoie le chemin de la copie, ou None si la dernière a moins de 24 h
    (forcer=True : copie tout de suite, commande « sauvegarder »)."""
    import os
    import sqlite3
    from pathlib import Path

    from django.conf import settings

    dossier = Path(dossier or Path.home() / "sauvegardes_youtube")
    dossier.mkdir(mode=0o700, exist_ok=True)
    copies = sorted(dossier.glob("db_*.sqlite3"))
    if not forcer and copies and timezone.now().timestamp() - copies[-1].stat().st_mtime < 24 * 3600:
        return None
    cible = dossier / f"db_{timezone.now():%Y-%m-%d_%H%M%S}.sqlite3"
    nom = str(settings.DATABASES["default"]["NAME"])
    copie = sqlite3.connect(cible)
    if nom.startswith("file:"):
        # Base en mémoire des tests : copiée par la connexion de Django (avant, sqlite3.connect(NAME) créait
        # pendant les tests un fichier vide nommé « file » à la racine : tâche X1)
        from django.db import connection
        connection.ensure_connection()
        copie.executescript("\n".join(connection.connection.iterdump()))
    else:
        source = sqlite3.connect(nom)
        with copie:
            source.backup(copie)
        source.close()
    copie.close()
    os.chmod(cible, 0o600)
    for ancienne in sorted(dossier.glob("db_*.sqlite3"))[:-NB_SAUVEGARDES]:
        ancienne.unlink()
    return cible


def taches_periodiques():
    """Appelée par le worker : nettoyage toutes les heures, règle des 30 jours et sauvegarde une fois par jour."""
    try:
        abandonnes = nettoyer_envois_abandonnes()
        videos, chaines = appliquer_regle_30_jours()
        from .exploitation import sauvegarde_quotidienne
        sauvegarde = sauvegarde_quotidienne()   # copie du jour vérifiée (et copiée hors du serveur si configuré)
        if abandonnes or videos or chaines or sauvegarde:
            logger.warning("Tâches automatiques : %s envoi(s) abandonné(s), %s lien(s) et %s chaîne(s) effacés, "
                           "sauvegarde : %s", abandonnes, videos, chaines, sauvegarde)
    except Exception:
        logger.exception("Tâches automatiques : erreur")


def marquer_envois_interrompus():
    """Au démarrage du worker : une vidéo restée « en cours » a été coupée. On ne la renvoie pas
    automatiquement (risque de doublon sur YouTube) : elle passe en échec avec un message clair."""
    for video in Video.objects.filter(etat="en_cours"):
        video.etat = "echoue"
        video.erreur = MESSAGE_INTERROMPU
        video.fichier.delete(save=False)
        video.save()
        logger.warning("Envoi interrompu marqué en échec (vidéo %s)", video.id)
        from .exploitation import alerter
        alerter("envoi_interrompu", "Envoi interrompu par un redémarrage",
                f"La vidéo n° {video.id} était en cours d'envoi quand le worker s'est arrêté : elle est marquée en "
                "échec (pas de renvoi automatique). Le client doit la renvoyer.")

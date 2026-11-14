"""Lien entre le site et le service de fabrication des vidéos sur Modal (fabrication_modal/service.py).

Le site ne calcule rien : il lance la fabrication chez Modal, puis le worker (traiter_envois) suit l'étape en cours,
récupère la vidéo finie avec le client Modal (centre de données → centre de données), l'efface chez Modal et la
range « en attente » : l'envoi YouTube existant prend le relais (décision D8 : aucun jeton Google chez Modal).
"""
import logging
import os
import secrets
import time

from django.conf import settings
from django.core.files.storage import default_storage
from django.utils import timezone

from .models import Video, VoixUtilisateur

# Catalogue des modèles, partagé avec le service Modal (fichier Python pur, sans Django ni Modal)
from fabrication_modal.modeles import MODELES, MUSIQUES, TYPES_SCENE, duree_estimee, paragraphes

logger = logging.getLogger(__name__)

VOLUME_VIDEOS = "batchcodeia-video-fichiers"
DICT_PROGRESSION = "batchcodeia-video-progression"
MESSAGE_ECHEC = ("La fabrication de la vidéo a échoué. Ton quota de voix t'a été rendu : relance fabriquer_video "
                 "dans quelques minutes ; si le problème continue, contacte le support.")
MESSAGE_DELAI = ("La fabrication de la vidéo a pris trop de temps et a été arrêtée. Ton quota de voix t'a été rendu : "
                 "relance fabriquer_video.")
MESSAGE_RECUPERATION = ("La vidéo a été fabriquée mais n'a pas pu être récupérée. Ton quota de voix t'a été rendu : "
                        "relance fabriquer_video.")
ETAPES = {"preparation": "Préparation", "voix": "Voix en cours", "rendu": "Rendu", "assemblage": "Assemblage",
          "prete": "Récupération de la vidéo"}

__all__ = ["MODELES", "MUSIQUES", "TYPES_SCENE", "duree_estimee", "paragraphes"]


def app_modal():
    return getattr(settings, "RENDU_MODAL_APP", "batchcodeia-video")


def duree_max(modele):
    """Durée maximale d'une vidéo (en s) : celle du modèle, plafonnée par le réglage du service (offres : lot 4)."""
    return min(MODELES[modele]["duree_max"], getattr(settings, "RENDU_DUREE_MAX_SECONDES", 600))


# ---------- appels à Modal (remplacés par des simulations dans les tests) ----------

def lancer_fabrication(donnees):
    import modal
    return modal.Function.from_name(app_modal(), "fabriquer").spawn(donnees).object_id


def resultat_fabrication(id_appel):
    """Résultat (dict) si la fabrication est finie, None si elle est en cours. Lève une exception si elle a échoué."""
    import modal
    try:
        return modal.FunctionCall.from_id(id_appel).get(timeout=0)
    except TimeoutError:
        return None


def arreter_fabrication(id_appel):
    import modal
    try:
        modal.FunctionCall.from_id(id_appel).cancel()
    except Exception:
        logger.exception("Fabrication : arrêt impossible chez Modal")


def lire_progression(cle):
    import modal
    try:
        return modal.Dict.from_name(DICT_PROGRESSION).get(cle)
    except Exception:
        return None


def telecharger_video(nom, chemin):
    """Copie la vidéo finie du volume Modal privé vers le disque du serveur (sans lien public)."""
    import modal
    volume = modal.Volume.from_name(VOLUME_VIDEOS)
    with open(chemin, "wb") as fichier:
        for morceau in volume.read_file(nom):
            fichier.write(morceau)


def effacer_chez_modal(nom):
    import modal
    try:
        modal.Volume.from_name(VOLUME_VIDEOS).remove_file(nom)
    except Exception:
        logger.exception("Fabrication : vidéo non effacée chez Modal (le nettoyage automatique le fera sous 2 h)")


# ---------- lancement (API) ----------

def donnees_pour_modal(video, reference=None, debut_voix=0.0):
    """Ce qui part chez Modal : les champs du modèle et, si besoin, l'extrait de voix (jamais gardé en base)."""
    d = video.donnees_modele
    return {
        "cle": d["cle"], "modele": video.modele, "titre": video.titre, "accent": d["accent"], "musique": d["musique"],
        "script": d["script"], "scenes": d["scenes"],
        "voix": {"reference": reference, "debut": debut_voix} if reference is not None else None,
    }


def nouvelle_cle(video_id):
    return f"video-{video_id}-{secrets.token_hex(8)}"


# ---------- suivi par le worker ----------

def rendre_quota(video):
    """Échec : les secondes de voix décomptées au lancement sont rendues au client."""
    secondes = int(video.donnees_modele.get("secondes_voix") or 0)
    if not secondes:
        return
    voix = VoixUtilisateur.objects.filter(user=video.user).first()
    if voix is not None:
        voix.secondes_utilisees = max(0, voix.secondes_utilisees - secondes)
        voix.save(update_fields=["secondes_utilisees"])
    video.donnees_modele["secondes_voix"] = 0


def echec(video, message):
    rendre_quota(video)
    video.etat, video.erreur, video.etape = "fabrication_echouee", message, ""
    video.save(update_fields=["etat", "erreur", "etape", "donnees_modele"])
    logger.warning("Fabrication échouée (vidéo %s) : %s", video.id, message)
    if message == MESSAGE_DELAI:
        # les autres échecs sont déjà signalés à Samba par le journal (niveau ERROR, avec la trace)
        from .exploitation import alerter
        alerter("fabrication_delai", "Fabrication arrêtée : délai dépassé",
                f"La vidéo n° {video.id} n'était pas finie après {getattr(settings, 'RENDU_DELAI_MAX_SECONDES', 1800) // 60} "
                "min : arrêtée chez Modal, quota de voix rendu au client. Vérifier le tableau de bord Modal.")


def texte_etape(progression):
    if not progression:
        return None
    etape = progression.get("etape")
    if etape == "rendu" and progression.get("total"):
        return f"Rendu {progression.get('fait', 0)}/{progression['total']}"
    return ETAPES.get(etape)


def recuperer(video, resultat):
    """Vidéo prête chez Modal : copie sur le serveur, effacement chez Modal, puis « en attente » d'envoi YouTube."""
    nom_modal = resultat["fichier"]
    nom = default_storage.get_available_name(f"videos/fabrication_{video.id}.mp4")
    chemin = default_storage.path(nom)
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    debut = time.monotonic()
    try:
        telecharger_video(nom_modal, chemin)
    except Exception:
        logger.exception("Fabrication : récupération impossible (vidéo %s)", video.id)
        if os.path.exists(chemin):
            os.remove(chemin)
        echec(video, MESSAGE_RECUPERATION)
        return
    finally:
        effacer_chez_modal(nom_modal)   # effacée chez Modal dans tous les cas
    secondes = time.monotonic() - debut
    taille_mo = os.path.getsize(chemin) / (1024 * 1024)
    # Mesure T4 : temps Modal → serveur (si > 30 s pour 50 Mo, revoir la décision D8)
    logger.warning("Fabrication %s : vidéo récupérée chez Modal (%.1f Mo en %.1f s)", video.id, taille_mo, secondes)
    mesures = dict(resultat.get("mesures") or {})
    mesures.update({"recuperation": round(secondes, 1), "taille_mo": round(taille_mo, 1)})
    video.donnees_modele["mesures"] = mesures
    video.fichier.name = nom
    video.duree_secondes = round(resultat.get("duree") or video.duree_secondes)
    video.etat, video.etape = "en_attente", ""   # le worker l'envoie maintenant sur YouTube
    video.save(update_fields=["fichier", "duree_secondes", "etat", "etape", "donnees_modele"])


def suivre(video):
    delai = getattr(settings, "RENDU_DELAI_MAX_SECONDES", 30 * 60)
    try:
        resultat = resultat_fabrication(video.appel_modal)
    except Exception:
        logger.exception("Fabrication : le travail Modal a échoué (vidéo %s)", video.id)
        echec(video, MESSAGE_ECHEC)
        return
    if resultat is None:
        if (timezone.now() - video.created_at).total_seconds() > delai:
            arreter_fabrication(video.appel_modal)
            echec(video, MESSAGE_DELAI)
            return
        etape = texte_etape(lire_progression(video.donnees_modele.get("cle")))
        if etape and etape != video.etape:
            video.etape = etape
            video.save(update_fields=["etape"])
        return
    recuperer(video, resultat)


def suivre_fabrications():
    """Appelée par le worker toutes les 5 s : étape en cours, échecs, vidéos prêtes à récupérer."""
    for video in Video.objects.filter(etat="fabrication").exclude(appel_modal="").select_related("user"):
        try:
            suivre(video)
        except Exception:
            logger.exception("Fabrication : erreur pendant le suivi (vidéo %s)", video.id)

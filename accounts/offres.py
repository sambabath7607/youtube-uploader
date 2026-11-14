"""Offres Gratuit / Pro (lot 4) : une seule fonction, limites(user), donne ce que le compte peut faire.

Elle est utilisée par l'envoi (envois par jour), la voix (minutes par mois) et la fabrication (minutes de vidéo).
Les chiffres sont dans settings.OFFRES (provisoires, à décider par Samba).
"""
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

# Filet de sécurité : si le renouvellement n'est jamais arrivé (appel perdu et rattrapage en panne),
# l'offre Pro reste active 3 jours après la fin de la période, puis le compte repasse en Gratuit.
DELAI_DE_GRACE = timedelta(days=3)


@dataclass
class Limites:
    offre: str                 # "gratuit" ou "pro"
    nom: str
    prix: str
    envois_par_jour: int
    secondes_voix_par_mois: int
    secondes_video_par_mois: int
    secondes_max_par_video: int
    fin_periode: object = None

    @property
    def est_pro(self):
        return self.offre == "pro"


def offre_du_compte(user):
    """« pro » si un abonnement payé est actif (ou dans le délai de grâce), sinon « gratuit »."""
    from .models import Abonnement

    abonnement = Abonnement.objects.filter(user=user).first()
    if abonnement is None or not abonnement.est_pro:
        return "gratuit", None
    if abonnement.fin_periode and abonnement.fin_periode + DELAI_DE_GRACE < timezone.now():
        return "gratuit", None
    return "pro", abonnement.fin_periode


def limites(user):
    offre, fin = offre_du_compte(user)
    chiffres = settings.OFFRES[offre]
    return Limites(
        offre=offre, nom=chiffres["nom"], prix=chiffres["prix"],
        envois_par_jour=chiffres["envois_par_jour"],
        secondes_voix_par_mois=chiffres["minutes_voix_par_mois"] * 60,
        secondes_video_par_mois=chiffres["minutes_video_par_mois"] * 60,
        secondes_max_par_video=chiffres["minutes_max_par_video"] * 60,
        fin_periode=fin,
    )


# ---------- Compteurs du jour et du mois ----------

def debut_du_jour():
    return timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)


def debut_du_mois():
    return debut_du_jour().replace(day=1)


def envois_du_jour(user):
    from youtube_uploader.models import Video

    # Même règle que youtube_uploader.envois : une fabrication échouée ne compte pas
    return Video.objects.filter(user=user, created_at__gte=debut_du_jour()).exclude(etat="fabrication_echouee").count()


def envois_restants(user):
    return max(0, limites(user).envois_par_jour - envois_du_jour(user))


def quota_voix_secondes(voix):
    """Secondes de voix du mois : celles de l'offre, sauf si l'administrateur a réglé un quota à la main
    (champ « quota_secondes » différent de la valeur par défaut) : ce réglage l'emporte, en plus ou en moins."""
    from youtube_uploader.models import QUOTA_GRATUIT_SECONDES

    if voix.quota_secondes != QUOTA_GRATUIT_SECONDES:
        return voix.quota_secondes
    return limites(voix.user).secondes_voix_par_mois


def _video_a_une_duree():
    # Le champ « duree_secondes » arrive avec la fabrication sur Modal (lot 2) : sans lui, rien n'est compté
    from youtube_uploader.models import Video

    return any(champ.name == "duree_secondes" for champ in Video._meta.get_fields())


def secondes_video_du_mois(user):
    """Minutes de vidéo fabriquées sur nos serveurs ce mois-ci (les vidéos dont la fabrication a échoué ne comptent pas)."""
    from youtube_uploader.models import Video

    if not _video_a_une_duree():
        return 0
    total = (Video.objects.filter(user=user, created_at__gte=debut_du_mois()).exclude(modele="")
             .exclude(etat="fabrication_echouee").aggregate(total=Sum("duree_secondes"))["total"])
    return total or 0


def probleme_fabrication(user, duree_secondes):
    """À appeler avant de lancer une fabrication. Renvoie (message, code) ou None."""
    offre = limites(user)
    if duree_secondes > offre.secondes_max_par_video:
        return (f"Avec l'offre {offre.nom}, une vidéo dure au plus {offre.secondes_max_par_video // 60} min. "
                "Raccourcis le script ou passe à l'offre Pro.", "duree_max_atteinte")
    if secondes_video_du_mois(user) + duree_secondes > offre.secondes_video_par_mois:
        return (f"Tes {offre.secondes_video_par_mois // 60} min de vidéo du mois (offre {offre.nom}) sont utilisées. "
                "Le compteur repart le 1er du mois, ou passe à l'offre Pro.", "quota_video_atteint")
    return None


def resume(user):
    """Résumé de l'offre pour « Mon compte » et l'API : offre, fin de période, compteurs utilisés et restants."""
    from youtube_uploader.models import VoixUtilisateur
    from youtube_uploader.voix import quota_restant

    offre = limites(user)
    voix = VoixUtilisateur.objects.filter(user=user).first()
    voix_total = quota_voix_secondes(voix) if voix else offre.secondes_voix_par_mois
    voix_restant = quota_restant(voix) if voix else voix_total
    video_utilise = secondes_video_du_mois(user)
    return {
        "offre": offre.offre,
        "nom": offre.nom,
        "fin_periode": offre.fin_periode,
        "envois_par_jour": offre.envois_par_jour,
        "envois_restants_aujourd_hui": envois_restants(user),
        "minutes_voix_par_mois": voix_total // 60,
        "minutes_voix_restantes": voix_restant // 60,
        "minutes_video_par_mois": offre.secondes_video_par_mois // 60,
        "minutes_video_restantes": max(0, offre.secondes_video_par_mois - video_utilise) // 60,
        "minutes_max_par_video": offre.secondes_max_par_video // 60,
    }

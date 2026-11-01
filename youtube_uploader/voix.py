"""Lien entre le site et le service de voix sur Modal (voix_modal/service.py).

Le calcul se fait chez Modal, jamais sur ce serveur : le site envoie le texte et l'extrait,
puis lit l'état du travail. L'audio fabriqué est téléchargé directement chez Modal.
"""
import math

from django.core import signing
from django.utils import timezone


APP_MODAL = "batchcodeia-voix"
MOTS_PAR_SECONDE = 2.5          # débit moyen d'une voix qui explique un cours (environ 150 mots par minute)
SEL_TRAVAIL = "travail-voix"
VALIDITE_TRAVAIL = 24 * 3600    # même durée que la conservation de l'audio chez Modal


def secondes_estimees(texte):
    return max(1, math.ceil(len(texte.split()) / MOTS_PAR_SECONDE))


def quota_restant(voix):
    """Secondes d'audio encore disponibles ce mois-ci (compteur remis à zéro chaque mois)."""
    debut_mois = timezone.localdate().replace(day=1)
    if voix.mois_du_compteur != debut_mois:
        voix.mois_du_compteur, voix.secondes_utilisees = debut_mois, 0
        voix.save(update_fields=["mois_du_compteur", "secondes_utilisees"])
    return max(0, voix.quota_secondes - voix.secondes_utilisees)   # quota propre à chaque utilisateur (offre Pro)


def jeton_travail(id_appel, user):
    # Le numéro du travail Modal est signé avec l'utilisateur : personne d'autre ne peut le lire
    return signing.dumps({"appel": id_appel, "user": user.id}, salt=SEL_TRAVAIL)


def lire_jeton(jeton, user):
    """Renvoie le numéro du travail Modal, ou None si le jeton est faux, expiré ou à quelqu'un d'autre."""
    try:
        donnees = signing.loads(jeton, salt=SEL_TRAVAIL, max_age=VALIDITE_TRAVAIL)
    except signing.BadSignature:
        return None
    return donnees["appel"] if donnees.get("user") == user.id else None


TEXTE_ESSAI = ("Bonjour à tous, et bienvenue dans ce nouveau cours. "
               "Aujourd'hui, nous allons apprendre quelque chose de nouveau, étape par étape.")


def lancer_lecture(texte, reference, debut=0.0):
    import modal
    Voix = modal.Cls.from_name(APP_MODAL, "Voix")
    return Voix().lire.spawn(texte, reference, debut).object_id


def lancer_essai(reference):
    """« Tester ma voix » : 3 propositions, chacune à partir d'un passage différent de l'enregistrement."""
    import modal
    Voix = modal.Cls.from_name(APP_MODAL, "Voix")
    return Voix().essayer.spawn(TEXTE_ESSAI, reference).object_id


def essais_restants(voix):
    """Tests « Tester ma voix » encore permis aujourd'hui (compteur remis à zéro chaque jour)."""
    from .models import ESSAIS_PAR_JOUR
    aujourd_hui = timezone.localdate()
    if voix.jour_des_essais != aujourd_hui:
        voix.jour_des_essais, voix.essais_du_jour = aujourd_hui, 0
        voix.save(update_fields=["jour_des_essais", "essais_du_jour"])
    return max(0, ESSAIS_PAR_JOUR - voix.essais_du_jour)


def etat_lecture(id_appel):
    """Résultat du travail (dict ou liste) s'il est fini, None s'il est encore en cours. Lève une exception s'il a échoué."""
    import modal
    try:
        return modal.FunctionCall.from_id(id_appel).get(timeout=0)
    except TimeoutError:
        return None

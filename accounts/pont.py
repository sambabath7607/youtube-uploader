"""Pont signé avec le site vitrine (lot 4) : POST /youtube/api/v1/interne/abonnements/

Le site vitrine (Stripe) prévient le service quand un abonnement YouTube Uploader commence, change ou se termine.
Sécurité :
- signature HMAC-SHA256 du message « <horodatage>.<corps> » avec le secret partagé PONT_SECRET
  (en-têtes X-Pont-Horodatage et X-Pont-Signature) ;
- horodatage de moins de 5 minutes (un vieil appel recopié est refusé) ;
- chaque événement (champ « evenement ») n'agit qu'une seule fois ; un état plus ancien que le dernier reçu est ignoré.

Corps JSON : {"evenement": "…", "email": "…", "offre": "pro" | "gratuit", "statut": "active", "reference": "…",
              "fin_periode": "2026-12-14T10:00:00+00:00" ou null, "etat_le": "2026-11-14T10:00:00+00:00"}
"""
import hashlib
import hmac
import json
import logging
import secrets
import time

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Abonnement, EvenementPont

journal = logging.getLogger(__name__)
TAILLE_MAX = 10_000   # octets : un appel du pont est tout petit


def signature(secret, horodatage, corps):
    """Signature attendue (le site vitrine calcule exactement la même)."""
    message = f"{horodatage}.".encode() + corps
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def erreur(message, code, statut):
    return JsonResponse({"erreur": message, "code": code}, status=statut)


def verifier_appel(request):
    """Renvoie une réponse d'erreur si l'appel n'est pas authentique, sinon None."""
    secret = settings.PONT_SECRET
    if not secret:
        return erreur("Le pont n'est pas configuré sur ce serveur.", "pont_non_configure", 503)
    horodatage = request.headers.get("X-Pont-Horodatage", "")
    signature_recue = request.headers.get("X-Pont-Signature", "")
    if not horodatage.isdigit() or not signature_recue:
        return erreur("Signature absente.", "signature_absente", 401)
    if abs(time.time() - int(horodatage)) > settings.PONT_TOLERANCE_SECONDES:
        return erreur("Appel trop ancien (ou horloge décalée).", "appel_expire", 401)
    if not hmac.compare_digest(signature(secret, horodatage, request.body), signature_recue):
        return erreur("Signature invalide.", "signature_invalide", 401)
    return None


def nom_utilisateur_libre(email):
    base = "".join(c for c in email.split("@")[0] if c.isalnum() or c in "._-")[:120] or "client"
    nom, n = base, 2
    while User.objects.filter(username__iexact=nom).exists():
        nom, n = f"{base}{n}", n + 1
    return nom


def creer_compte(email, request):
    """Compte créé pour un client qui a payé sans compte : mot de passe aléatoire inconnu de tous, et courriel
    « Choisis ton mot de passe » (même lien que « mot de passe oublié », valable 1 h ; ensuite, « mot de passe oublié »)."""
    user = User.objects.create_user(username=nom_utilisateur_libre(email), email=email,
                                    password=secrets.token_urlsafe(32))
    lien = request.build_absolute_uri(reverse("password_reset_confirm", kwargs={
        "uidb64": urlsafe_base64_encode(force_bytes(user.pk)), "token": default_token_generator.make_token(user)}))
    corps = render_to_string("accounts/courriels/bienvenue_pro.txt", {
        "user": user, "lien": lien, "connexion": request.build_absolute_uri(reverse("login"))})

    def envoyer():
        try:
            send_mail("Ton accès Pro YouTube Uploader est prêt : choisis ton mot de passe", corps,
                      settings.DEFAULT_FROM_EMAIL, [email])
        except Exception:   # le compte existe quand même : « mot de passe oublié » renverra un lien
            journal.exception("Courriel de bienvenue Pro non envoyé (compte %s)", user.pk)

    transaction.on_commit(envoyer)   # seulement si le compte est bien enregistré
    return user


def trouver_compte(reference, email):
    abonnement = Abonnement.objects.filter(reference=reference).select_related("user").first() if reference else None
    if abonnement:
        return abonnement.user
    return User.objects.filter(email__iexact=email).order_by("id").first()


def lire_donnees(request):
    try:
        donnees = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(donnees, dict):
        return None
    evenement = str(donnees.get("evenement") or "")[:100]
    email = str(donnees.get("email") or "").strip()
    offre = donnees.get("offre")
    etat_le = parse_datetime(str(donnees.get("etat_le") or ""))
    fin = parse_datetime(str(donnees.get("fin_periode") or "")) if donnees.get("fin_periode") else None
    if not evenement or "@" not in email or offre not in ("pro", "gratuit") or etat_le is None:
        return None
    return {"evenement": evenement, "email": email, "offre": offre, "etat_le": etat_le, "fin_periode": fin,
            "statut": str(donnees.get("statut") or "")[:20], "reference": str(donnees.get("reference") or "")[:100]}


@csrf_exempt
@require_POST
def recevoir_abonnement(request):
    if len(request.body) > TAILLE_MAX:
        return erreur("Message trop long.", "trop_long", 400)
    refus = verifier_appel(request)
    if refus:
        return refus
    donnees = lire_donnees(request)
    if donnees is None:
        return erreur("Données invalides : evenement, email, offre (pro ou gratuit) et etat_le sont obligatoires.",
                      "donnees_invalides", 400)
    try:
        with transaction.atomic():
            EvenementPont.objects.create(identifiant=donnees["evenement"])
            reponse = appliquer(donnees, request)
    except IntegrityError:   # déjà reçu : aucune action en double
        return JsonResponse({"resultat": "deja_traite"})
    return JsonResponse(reponse)


def appliquer(donnees, request):
    pro = donnees["offre"] == "pro"
    user = trouver_compte(donnees["reference"], donnees["email"])
    compte_cree = False
    if user is None:
        if not pro:
            return {"resultat": "ignore", "compte_cree": False}   # retour à Gratuit d'un compte inconnu : rien à faire
        user, compte_cree = creer_compte(donnees["email"], request), True
    abonnement, _ = Abonnement.objects.select_for_update().get_or_create(user=user)
    if abonnement.etat_le and donnees["etat_le"] < abonnement.etat_le:
        return {"resultat": "ancien_etat_ignore", "compte_cree": False}
    abonnement.email = donnees["email"]
    abonnement.offre = "pro" if pro else "gratuit"
    abonnement.actif = pro
    abonnement.fin_periode = donnees["fin_periode"]
    abonnement.statut_vitrine = donnees["statut"]
    abonnement.reference = donnees["reference"] or abonnement.reference
    abonnement.dernier_evenement = donnees["evenement"]
    abonnement.etat_le = donnees["etat_le"]
    abonnement.save()
    journal.info("Pont : compte %s passé en offre %s", user.pk, abonnement.offre)
    return {"resultat": "pro_active" if pro else "gratuit", "compte_cree": compte_cree}

import json
import os

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.views.decorators.http import require_POST
from google_auth_oauthlib.flow import Flow

from .models import YouTubeCredentials
from .upload import DOSSIER, SCOPES


from .chiffrement import chiffrer, dechiffrer

if settings.DEBUG:
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # seulement en local (http), jamais sur le serveur

CLIENT_SECRET_WEB = os.path.join(DOSSIER, "client_secret_web.json")
REDIRECT_URI = os.environ.get("OAUTH_REDIRECT_URI", "http://127.0.0.1:8000/youtube/oauth/callback/")
ADRESSE_REVOCATION = "https://oauth2.googleapis.com/revoke"


def creer_flow(state=None):
    return Flow.from_client_secrets_file(
        CLIENT_SECRET_WEB, scopes=SCOPES, state=state, redirect_uri=REDIRECT_URI
    )


@login_required
def connecter_youtube(request):
    flow = creer_flow()
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    request.session["oauth_state"] = state
    request.session["code_verifier"] = flow.code_verifier
    return redirect(url)


@login_required
def oauth_callback(request):
    # L'utilisateur a cliqué sur « Annuler » chez Google : Google renvoie ?error=access_denied
    if request.GET.get("error"):
        messages.warning(request, "Connexion annulée : ta chaîne YouTube n'a pas été connectée.")
        return redirect("accueil")
    if not request.session.get("oauth_state") or not request.GET.get("code"):
        messages.error(request, "Lien de connexion invalide ou expiré. Clique à nouveau sur « Connecter ma chaîne ».")
        return redirect("accueil")
    try:
        flow = creer_flow(state=request.session.get("oauth_state"))
        flow.code_verifier = request.session.get("code_verifier")
        flow.fetch_token(authorization_response=request.build_absolute_uri())
    except Exception:
        # Pas de détail technique affiché (ni enregistré avec un token) : seulement un message clair
        messages.error(request, "Google n'a pas pu confirmer la connexion. Réessaie dans un instant.")
        return redirect("accueil")
    finally:
        request.session.pop("oauth_state", None)
        request.session.pop("code_verifier", None)
    YouTubeCredentials.objects.update_or_create(
        user=request.user,
        defaults={"token_json": chiffrer(flow.credentials.to_json())},
    )
    messages.success(request, "Ta chaîne YouTube est connectée.")
    return redirect("accueil")


def revoquer_token_google(ligne):
    """Demande à Google d'annuler l'autorisation. Renvoie True si Google a accepté."""
    donnees = json.loads(dechiffrer(ligne.token_json))
    token = donnees.get("refresh_token") or donnees.get("token")
    if not token:
        return False
    try:
        reponse = requests.post(
            ADRESSE_REVOCATION,
            params={"token": token},
            headers={"content-type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        return reponse.status_code == 200
    except requests.RequestException:
        return False


@login_required
@require_POST
def deconnecter_youtube(request):
    ligne = YouTubeCredentials.objects.filter(user=request.user).first()
    if ligne:
        revoque = revoquer_token_google(ligne)
        ligne.delete()
        if revoque:
            messages.success(request, "Ta chaîne YouTube est déconnectée et l'accès a été retiré chez Google.")
        else:
            messages.warning(
                request,
                "Ta chaîne est déconnectée du site, mais Google n'a pas confirmé. "
                "Retire l'accès toi-même sur myaccount.google.com/permissions.",
            )
    return redirect("accueil")

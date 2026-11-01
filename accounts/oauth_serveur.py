"""Connexion en un clic (OAuth 2.1) pour les agents IA, selon la spécification MCP (révision 2026-07-28).

L'agent IA (Claude, ChatGPT, Cursor…) découvre ce serveur par les métadonnées, s'enregistre (RFC 7591) ou se
présente par l'adresse de son document (CIMD), envoie l'utilisateur sur la page « Autoriser », puis échange le
code contre un jeton d'accès (PKCE S256 obligatoire). Le jeton remplace la clé d'API : rien à copier.
"""
import base64
import hashlib
import json
import secrets
from datetime import timedelta
from urllib.parse import urlencode, urlparse

import requests
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from .models import ClientOAuth, CodeOAuth, JetonOAuth, empreinte

DUREE_CODE = timedelta(minutes=10)
DUREE_ACCES = timedelta(hours=1)
DUREE_RAFRAICHISSEMENT = timedelta(days=30)
MAX_ENREGISTREMENTS_PAR_HEURE = 200


def emetteur(request):
    return f"{request.scheme}://{request.get_host()}"


def erreur_oauth(code, description, statut=400):
    return JsonResponse({"error": code, "error_description": description}, status=statut)


def redirection_autorisee(uri):
    """https partout ; http seulement vers l'ordinateur de l'utilisateur (Claude Code, Cursor…)."""
    morceaux = urlparse(uri)
    if morceaux.scheme == "https" and morceaux.hostname:
        return True
    return morceaux.scheme == "http" and morceaux.hostname in ("localhost", "127.0.0.1", "::1")


# ---------- découverte ----------

def metadonnees_serveur(request):
    """RFC 8414 : où se trouvent les pages de connexion."""
    base = emetteur(request)
    return JsonResponse({
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize/",
        "token_endpoint": f"{base}/oauth/token/",
        "registration_endpoint": f"{base}/oauth/register/",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["videos"],
        "client_id_metadata_document_supported": True,
        "authorization_response_iss_parameter_supported": True,
    })


def metadonnees_ressource(request):
    """RFC 9728 : le connecteur /mcp est protégé par ce serveur de connexion."""
    base = emetteur(request)
    return JsonResponse({
        "resource": f"{base}/mcp",
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["videos"],
        "resource_name": "Batch Code IA",
    })


# ---------- enregistrement des agents ----------

@csrf_exempt
@require_POST
def enregistrer_client(request):
    """RFC 7591 : un agent IA s'enregistre seul et reçoit son client_id (client public, sans secret)."""
    if ClientOAuth.objects.filter(created_at__gte=timezone.now() - timedelta(hours=1)).count() >= MAX_ENREGISTREMENTS_PAR_HEURE:
        return erreur_oauth("temporarily_unavailable", "Trop d'enregistrements, réessaie plus tard.", 429)
    try:
        donnees = json.loads(request.body or b"{}")
    except ValueError:
        return erreur_oauth("invalid_client_metadata", "Corps JSON invalide.")
    uris = donnees.get("redirect_uris")
    if not isinstance(uris, list) or not uris or len(uris) > 10 or not all(isinstance(u, str) and redirection_autorisee(u) for u in uris):
        return erreur_oauth("invalid_redirect_uri", "redirect_uris : 1 à 10 adresses https (ou http://localhost).")
    client = ClientOAuth.objects.create(client_id="bci_" + secrets.token_urlsafe(24),
                                        nom=str(donnees.get("client_name", ""))[:100], redirect_uris=uris)
    return JsonResponse({
        "client_id": client.client_id,
        "client_id_issued_at": int(client.created_at.timestamp()),
        "client_name": client.nom,
        "redirect_uris": uris,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }, status=201)


def client_depuis_document(client_id):
    """CIMD : le client_id est l'adresse https d'un petit document JSON publié par l'agent (ex. Claude)."""
    morceaux = urlparse(client_id)
    if morceaux.scheme != "https" or not morceaux.hostname or not morceaux.path or morceaux.path == "/":
        return None
    try:
        reponse = requests.get(client_id, timeout=5, allow_redirects=False, headers={"Accept": "application/json"})
        if reponse.status_code != 200 or len(reponse.content) > 20_000:
            return None
        document = reponse.json()
    except (requests.RequestException, ValueError):
        return None
    uris = document.get("redirect_uris")
    if document.get("client_id") != client_id or not isinstance(uris, list) or not all(
            isinstance(u, str) and redirection_autorisee(u) for u in uris):
        return None
    client, _ = ClientOAuth.objects.update_or_create(
        client_id=client_id, defaults={"nom": str(document.get("client_name", morceaux.hostname))[:100], "redirect_uris": uris})
    return client


def trouver_client(client_id):
    client = ClientOAuth.objects.filter(client_id=client_id).first()
    if client is None and client_id.startswith("https://"):
        client = client_depuis_document(client_id)
    return client


# ---------- page « Autoriser » ----------

@login_required
@require_http_methods(["GET", "POST"])
def autoriser(request):
    p = request.GET if request.method == "GET" else request.POST
    client = trouver_client(p.get("client_id", ""))
    redirect_uri = p.get("redirect_uri", "")
    # Adresse de retour inconnue : on n'y renvoie JAMAIS l'utilisateur (redirection ouverte)
    if client is None or redirect_uri not in client.redirect_uris:
        return render(request, "accounts/oauth_erreur.html",
                      {"message": "Application inconnue ou adresse de retour non enregistrée."}, status=400)

    def retour(**params):
        params["iss"] = emetteur(request)
        if p.get("state"):
            params["state"] = p.get("state")
        separateur = "&" if "?" in redirect_uri else "?"
        return HttpResponseRedirect(redirect_uri + separateur + urlencode(params))

    if p.get("response_type") != "code":
        return retour(error="unsupported_response_type")
    if p.get("code_challenge_method") != "S256" or not p.get("code_challenge"):
        return retour(error="invalid_request", error_description="PKCE S256 obligatoire")

    if request.method == "GET":
        return render(request, "accounts/oauth_autoriser.html", {
            "client": client, "hote_retour": urlparse(redirect_uri).hostname, "parametres": p.items(),
        })
    if request.POST.get("decision") != "autoriser":
        return retour(error="access_denied")
    code = secrets.token_urlsafe(32)
    CodeOAuth.objects.create(empreinte=empreinte(code), client=client, user=request.user, redirect_uri=redirect_uri,
                             code_challenge=p["code_challenge"], resource=p.get("resource", ""),
                             expire_le=timezone.now() + DUREE_CODE)
    return retour(code=code)


# ---------- échange du code contre un jeton ----------

def verifier_pkce(verificateur, defi):
    calcule = base64.urlsafe_b64encode(hashlib.sha256(verificateur.encode()).digest()).rstrip(b"=").decode()
    return secrets.compare_digest(calcule, defi)


def creer_jetons(client, user, resource):
    acces, rafraichissement = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    maintenant = timezone.now()
    JetonOAuth.objects.create(client=client, user=user, resource=resource,
                              empreinte_acces=empreinte(acces), empreinte_rafraichissement=empreinte(rafraichissement),
                              acces_expire_le=maintenant + DUREE_ACCES,
                              rafraichissement_expire_le=maintenant + DUREE_RAFRAICHISSEMENT)
    return JsonResponse({"access_token": acces, "token_type": "Bearer", "expires_in": int(DUREE_ACCES.total_seconds()),
                         "refresh_token": rafraichissement, "scope": "videos"},
                        headers={"Cache-Control": "no-store"})


@csrf_exempt
@require_POST
def jeton(request):
    p = request.POST
    client = ClientOAuth.objects.filter(client_id=p.get("client_id", "")).first()
    if client is None:
        return erreur_oauth("invalid_client", "client_id inconnu.", 401)
    if p.get("grant_type") == "authorization_code":
        with transaction.atomic():
            code = CodeOAuth.objects.select_for_update().filter(empreinte=empreinte(p.get("code", "")), client=client).first()
            if code is None or code.utilise or code.expire_le < timezone.now():
                return erreur_oauth("invalid_grant", "Code invalide, déjà utilisé ou expiré.")
            code.utilise = True
            code.save(update_fields=["utilise"])
        if p.get("redirect_uri") != code.redirect_uri:
            return erreur_oauth("invalid_grant", "redirect_uri différente de celle de l'autorisation.")
        if not verifier_pkce(p.get("code_verifier", ""), code.code_challenge):
            return erreur_oauth("invalid_grant", "code_verifier incorrect (PKCE).")
        return creer_jetons(client, code.user, code.resource)
    if p.get("grant_type") == "refresh_token":
        with transaction.atomic():
            ancien = JetonOAuth.objects.select_for_update().filter(
                empreinte_rafraichissement=empreinte(p.get("refresh_token", "")), client=client).first()
            if ancien is None or ancien.revoque or ancien.rafraichissement_expire_le < timezone.now():
                return erreur_oauth("invalid_grant", "Jeton de rafraîchissement invalide ou expiré.")
            ancien.revoque = True   # rotation : chaque jeton de rafraîchissement ne sert qu'une fois
            ancien.save(update_fields=["revoque"])
        return creer_jetons(client, ancien.user, ancien.resource)
    return erreur_oauth("unsupported_grant_type", "grant_type : authorization_code ou refresh_token.")


# ---------- retirer l'accès d'un agent ----------

@login_required
@require_POST
def retirer_acces(request):
    JetonOAuth.objects.filter(user=request.user, client_id=request.POST.get("client"), revoque=False).update(revoque=True)
    from django.contrib import messages
    from django.shortcuts import redirect
    messages.success(request, "Accès retiré : cet agent IA ne peut plus utiliser ton compte.")
    return redirect("ma_cle")

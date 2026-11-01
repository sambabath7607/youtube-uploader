from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect

from youtube_uploader.models import Video, YouTubeCredentials
from youtube_uploader.oauth import revoquer_token_google
from .forms import InscriptionForm
from .models import CleApi


def accueil(request):
    # Visiteur : page publique de présentation (Google exige une page d'accueil qui décrit le service)
    if not request.user.is_authenticated:
        return render(request, "accounts/presentation.html")
    from youtube_uploader.models import Video, VoixUtilisateur, YouTubeCredentials
    voix = VoixUtilisateur.objects.filter(user=request.user).first()
    etapes = [
        ("Connecter ta chaîne YouTube", YouTubeCredentials.objects.filter(user=request.user).exists(), "#chaine"),
        ("Enregistrer ta voix", bool(voix and voix.extrait), "ma_voix"),
        ("Tester ta voix et choisir « C'est ma voix »", bool(voix and voix.voix_validee), "ma_voix"),
        ("Créer une clé et ajouter le connecteur dans Claude", CleApi.objects.filter(user=request.user).exists(), "guide_claude"),
        ("Publier ta première vidéo", Video.objects.filter(user=request.user, etat="reussi").exists(), "guide_claude"),
    ]
    return render(request, "accounts/accueil.html", {
        "etapes": etapes, "etapes_faites": sum(1 for _, fait, _ in etapes if fait), "nb_etapes": len(etapes),
    })


def inscription(request):
    if request.method == "POST":
        form = InscriptionForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Bienvenue ! Ton compte est créé. Connecte maintenant ta chaîne YouTube.")
            return redirect("accueil")
    else:
        form = InscriptionForm()
    return render(request, "accounts/inscription.html", {"form": form})


@login_required
def ma_cle(request):
    """Mes clés : une clé par appareil ou agent IA ; en créer une n'annule pas les autres."""
    nouvelle_cle = nom_nouvelle_cle = None
    if request.method == "POST":
        if request.POST.get("action") == "supprimer":
            CleApi.objects.filter(user=request.user, id=request.POST.get("id")).delete()
            messages.success(request, "Clé supprimée : elle ne fonctionne plus.")
            return redirect("ma_cle")
        if CleApi.objects.filter(user=request.user).count() >= CleApi.MAX_PAR_COMPTE:
            messages.error(request, f"Maximum {CleApi.MAX_PAR_COMPTE} clés : supprime d'abord une clé inutile.")
            return redirect("ma_cle")
        nom_nouvelle_cle = request.POST.get("nom", "").strip() or "Ma clé"
        nouvelle_cle = CleApi.creer_pour(request.user, nom_nouvelle_cle)
    cles = CleApi.objects.filter(user=request.user).order_by("-created_at")
    from django.db.models import Max
    from django.utils import timezone
    from .models import JetonOAuth
    agents = (JetonOAuth.objects.filter(user=request.user, revoque=False, rafraichissement_expire_le__gt=timezone.now())
              .values("client_id", "client__nom", "client__client_id").annotate(depuis=Max("created_at")))
    return render(request, "accounts/ma_cle.html",
                  {"cles": cles, "nouvelle_cle": nouvelle_cle, "nom_nouvelle_cle": nom_nouvelle_cle, "agents": agents})


def voix_exportee(user):
    from youtube_uploader.models import VoixUtilisateur
    voix = VoixUtilisateur.objects.filter(user=user).first()
    if voix is None or not voix.extrait:
        return None
    return {"mode": voix.mode, "consentement_le": voix.consentement_le.isoformat() if voix.consentement_le else None,
            "remarque": "L'extrait de voix s'écoute sur la page « Ma voix » ; il est effacé avec le compte."}


@login_required
def mes_donnees(request):
    # Export des données personnelles (sans aucun token ni secret)
    user = request.user
    donnees = {
        "nom_utilisateur": user.username,
        "email": user.email,
        "date_inscription": user.date_joined.isoformat(),
        "chaine_youtube_connectee": YouTubeCredentials.objects.filter(user=user).exists(),
        "voix": voix_exportee(user),
        "cles_api": [{"nom": c.nom, "debut": c.debut, "creee_le": c.created_at.isoformat()}
                     for c in CleApi.objects.filter(user=user)],
        "videos": [
            {
                "titre": video.titre,
                "description": video.description,
                "pour_enfants": video.pour_enfants,
                "etat": video.etat,
                "youtube_id": video.youtube_id,
                "erreur": video.erreur,
                "created_at": video.created_at.isoformat(),
            }
            for video in Video.objects.filter(user=user).order_by("created_at")
        ],
    }
    reponse = JsonResponse(donnees, json_dumps_params={"ensure_ascii": False, "indent": 2})
    reponse["Content-Disposition"] = 'attachment; filename="mes_donnees.json"'
    return reponse


@login_required
def supprimer_compte(request):
    if request.method == "POST":
        user = request.user
        if not user.check_password(request.POST.get("mot_de_passe", "")):
            return render(request, "accounts/supprimer_compte.html", {"erreur": "Mot de passe incorrect."})
        ligne = YouTubeCredentials.objects.filter(user=user).first()
        if ligne:
            revoquer_token_google(ligne)
        for video in Video.objects.filter(user=user):
            if video.fichier:
                video.fichier.delete(save=False)
        from youtube_uploader.models import VoixUtilisateur
        for voix in VoixUtilisateur.objects.filter(user=user):
            if voix.extrait:
                voix.extrait.delete(save=False)   # le fichier de voix, pas seulement la fiche
        logout(request)
        user.delete()  # supprime aussi le token Google, la clé d'API et les vidéos (CASCADE)
        messages.success(request, "Ton compte et toutes tes données ont été supprimés.")
        return redirect("login")
    return render(request, "accounts/supprimer_compte.html")


def politique_confidentialite(request):
    return render(request, "accounts/confidentialite.html")


def conditions_utilisation(request):
    return render(request, "accounts/conditions.html")

def guide_api(request):
    return render(request, "accounts/guide_api.html")


def guide_claude(request):
    return render(request, "accounts/guide_claude.html")

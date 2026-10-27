from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect

from youtube_uploader.models import Video, YouTubeCredentials
from youtube_uploader.oauth import revoquer_token_google
from .forms import InscriptionForm
from .models import CleApi


@login_required
def accueil(request):
    return render(request, "accounts/accueil.html")


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
    nouvelle_cle = None
    if request.method == "POST":
        # Créer une nouvelle clé : l'ancienne ne marche plus ; la nouvelle est affichée une seule fois
        nouvelle_cle = CleApi.creer_pour(request.user)
    cle = CleApi.objects.filter(user=request.user).first()
    return render(request, "accounts/ma_cle.html", {"cle": cle, "nouvelle_cle": nouvelle_cle})


@login_required
def mes_donnees(request):
    # Export des données personnelles (sans aucun token ni secret)
    user = request.user
    donnees = {
        "nom_utilisateur": user.username,
        "email": user.email,
        "date_inscription": user.date_joined.isoformat(),
        "chaine_youtube_connectee": YouTubeCredentials.objects.filter(user=user).exists(),
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
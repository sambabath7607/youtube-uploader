from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .envois import probleme_avant_envoi
from .forms import VideoForm
from .models import QUOTA_GRATUIT_SECONDES, Video, VoixUtilisateur
from .voix import quota_restant

TAILLE_MAX_VOIX = 10 * 1024 * 1024   # 10 Mo, largement assez pour 2 minutes


@login_required
def nouvelle_video(request):
    probleme = None
    if request.method == "POST":
        form = VideoForm(request.POST, request.FILES)
        probleme = probleme_avant_envoi(request.user)
        if probleme is None and form.is_valid():
            # Rangée « En attente » : le worker youtube-worker l'enverra sur YouTube
            video = form.save(commit=False)
            video.user = request.user
            video.save()
            return redirect("suivi_video", video_id=video.id)
    else:
        form = VideoForm()
    message = probleme[0] if probleme else None
    return render(request, "youtube_uploader/nouvelle_video.html", {"form": form, "probleme": message})


@login_required
def suivi_video(request, video_id):
    # La vidéo d'un autre utilisateur répond 404
    video = get_object_or_404(Video, id=video_id, user=request.user)
    return render(request, "youtube_uploader/resultat.html", {"video": video})


@login_required
def ma_voix(request):
    voix, _ = VoixUtilisateur.objects.get_or_create(user=request.user)
    phrase = (f"Moi, {request.user.username}, j'autorise Batch Code IA à utiliser ma voix "
              f"pour créer mes vidéos, le {timezone.localdate():%d/%m/%Y}.")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "supprimer":
            voix.extrait.delete(save=False)
            voix.consentement_le, voix.mode = None, "aucune"
            voix.save()
            messages.success(request, "Ta voix a été supprimée.")
        elif action == "mode":
            mode = request.POST.get("mode")
            voix.mode = mode if mode in dict(VoixUtilisateur.MODES) else "aucune"
            voix.save()
            messages.success(request, "Ton choix est enregistré.")
        elif action == "enregistrer":
            fichier = request.FILES.get("extrait")
            if not request.POST.get("consentement"):
                messages.error(request, "Coche la case : tu confirmes que c'est ta propre voix.")
            elif not fichier or fichier.size > TAILLE_MAX_VOIX:
                messages.error(request, "Enregistrement absent ou trop lourd (10 Mo maximum).")
            else:
                voix.extrait.delete(save=False)
                voix.extrait.save(f"voix_{request.user.id}.webm", fichier, save=False)
                voix.consentement_le = timezone.now()
                voix.save()
                messages.success(request, "Ta voix est enregistrée.")
        return redirect("ma_voix")
    restant = quota_restant(voix)
    return render(request, "youtube_uploader/ma_voix.html", {
        "voix": voix, "phrase": phrase,
        "quota_minutes": restant // 60, "quota_secondes": restant % 60, "quota_total": QUOTA_GRATUIT_SECONDES // 60,
    })

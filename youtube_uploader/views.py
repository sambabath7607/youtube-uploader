from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .envois import probleme_avant_envoi
from .forms import VideoForm
from .models import Video


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

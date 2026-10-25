

from django.shortcuts import render
from .erreurs import message_erreur
from .forms import VideoForm
from .upload import upload_video

from django.contrib.auth.decorators import login_required



@login_required
def nouvelle_video(request):
    if request.method == "POST":
        form = VideoForm(request.POST, request.FILES)
        if form.is_valid():
            video = form.save(commit=False)
            video.user = request.user
            video.etat = "en_cours"
            video.save()
            try:
                statut = "private"
                video.youtube_id = upload_video(
                    video.fichier.path, video.titre, video.description,
                    "private", user=video.user,
                    pour_enfants=video.pour_enfants, contenu_ia=video.contenu_ia,
                )
                video.etat = "reussi"
            except Exception as e:
                video.etat = "echoue"
                video.erreur = message_erreur(e)
            video.fichier.delete(save=False)
            video.save()
            return render(request, "youtube_uploader/resultat.html", {"video": video})
    else:
        form = VideoForm()
    return render(request, "youtube_uploader/nouvelle_video.html", {"form": form})
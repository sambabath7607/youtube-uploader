import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .envois import probleme_avant_envoi
from .forms import VideoForm
from .models import PreferencesPublication, Video, VoixUtilisateur
from .voix import essais_restants, etat_lecture, lancer_essai, quota_restant

logger = logging.getLogger(__name__)
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
            voix.consentement_le, voix.mode, voix.passage_debut, voix.voix_validee = None, "aucune", 0, False
            voix.save()
            request.session.pop("essai_voix", None)
            messages.success(request, "Ta voix a été supprimée.")
        elif action == "tester":
            if not voix.extrait:
                messages.error(request, "Enregistre d'abord ta voix.")
            elif essais_restants(voix) == 0:
                messages.error(request, "Tu as utilisé tes 3 tests d'aujourd'hui. Réessaie demain.")
            else:
                try:
                    with voix.extrait.open("rb") as f:
                        request.session["essai_voix"] = lancer_essai(f.read())
                except Exception:
                    logger.exception("Tester ma voix : impossible de lancer l'essai")
                    messages.error(request, "Le service de voix est indisponible. Réessaie dans quelques minutes.")
                else:
                    voix.essais_du_jour += 1
                    voix.save(update_fields=["essais_du_jour"])
                    request.session.pop("essai_debuts", None)
                    messages.success(request, "Test lancé : les 3 propositions arrivent dans environ 1 à 2 minutes.")
        elif action == "choisir":
            try:
                debut = float(request.POST.get("debut", ""))
            except ValueError:
                debut = None
            if debut is None or debut not in request.session.get("essai_debuts", []):
                messages.error(request, "Proposition introuvable : relance « Tester ma voix ».")
            else:
                voix.passage_debut, voix.voix_validee = debut, True
                voix.save(update_fields=["passage_debut", "voix_validee"])
                messages.success(request, "C'est noté ✅ : tes vidéos utiliseront ce passage de ta voix.")
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
                voix.consentement_le, voix.passage_debut, voix.voix_validee = timezone.now(), 0, False
                voix.save()
                request.session.pop("essai_voix", None)
                messages.success(request, "Ta voix est enregistrée.")
        return redirect("ma_voix")
    restant = quota_restant(voix)
    return render(request, "youtube_uploader/ma_voix.html", {
        "voix": voix, "phrase": phrase,
        "quota_minutes": restant // 60, "quota_secondes": restant % 60, "quota_total": voix.quota_secondes // 60,
        "essais_restants": essais_restants(voix), "essai_en_cours": "essai_voix" in request.session,
    })


@login_required
def essai_ma_voix(request):
    """Interrogée par la page toutes les 5 s : état du test « Tester ma voix » (JSON)."""
    id_appel = request.session.get("essai_voix")
    if not id_appel:
        return JsonResponse({"etat": "aucun"})
    try:
        propositions = etat_lecture(id_appel)
    except Exception:
        logger.exception("Tester ma voix : le test a échoué")
        request.session.pop("essai_voix", None)
        return JsonResponse({"etat": "echoue"})
    if propositions is None:
        return JsonResponse({"etat": "en_cours"})
    request.session["essai_debuts"] = [p["debut"] for p in propositions]
    return JsonResponse({"etat": "pret", "propositions": propositions})


@login_required
def ecouter_ma_voix(request):
    # Chacun n'entend que SA voix : le fichier reste dans le dossier privé
    voix = VoixUtilisateur.objects.filter(user=request.user).first()
    if voix is None or not voix.extrait:
        raise Http404
    reponse = FileResponse(voix.extrait.open("rb"), content_type="audio/webm")
    reponse["Cache-Control"] = "no-store"   # ne pas garder de copie dans le navigateur
    return reponse


@login_required
def mes_videos(request):
    """Tableau de bord : mes envois, leur état et le lien YouTube."""
    from django.core.paginator import Paginator
    page = Paginator(Video.objects.filter(user=request.user).order_by("-created_at"), 20).get_page(request.GET.get("page"))
    return render(request, "youtube_uploader/mes_videos.html", {"page": page})


@login_required
def mes_preferences(request):
    """Réponses par défaut aux questions de YouTube : Claude Code ne les repose plus à chaque vidéo."""
    prefs, _ = PreferencesPublication.objects.get_or_create(user=request.user)
    if request.method == "POST":
        oui_non = {"oui": True, "non": False}
        prefs.pour_enfants = oui_non.get(request.POST.get("pour_enfants"))
        prefs.contenu_ia = oui_non.get(request.POST.get("contenu_ia"))
        visibilite = request.POST.get("visibilite", "")
        prefs.visibilite = visibilite if visibilite in dict(Video.VISIBILITES) else ""
        prefs.save()
        messages.success(request, "Tes préférences de publication sont enregistrées.")
        return redirect("mes_preferences")
    return render(request, "youtube_uploader/mes_preferences.html", {"prefs": prefs, "visibilites": Video.VISIBILITES})

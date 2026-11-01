"""Adresse de dépôt à usage unique : Claude Code y envoie la vidéo fabriquée, sans clé d'API.

L'adresse est signée (liée à une vidéo, donc à un seul compte), valable 1 heure, et ne sert qu'une fois :
dès que le fichier est reçu, la vidéo passe « en attente » et le worker l'envoie sur YouTube.
"""
from django.core import signing
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Video
from .validation import probleme_fichier

SEL_DEPOT = "depot-video"
VALIDITE_DEPOT = 3600   # 1 heure


def adresse_depot(request, video):
    jeton = signing.dumps({"video": video.id}, salt=SEL_DEPOT)
    return request.build_absolute_uri(reverse("depot_video", args=[jeton]))


@csrf_exempt          # appelée par Claude Code (curl), pas par un formulaire du site : le jeton signé protège
@require_POST
def depot_video(request, jeton):
    try:
        video_id = signing.loads(jeton, salt=SEL_DEPOT, max_age=VALIDITE_DEPOT)["video"]
    except (signing.BadSignature, KeyError, TypeError):
        return JsonResponse({"erreur": "Adresse de dépôt invalide ou expirée (1 h).", "code": "depot_invalide"}, status=404)
    video = Video.objects.filter(id=video_id, etat="attente_fichier").first()
    if video is None:
        return JsonResponse({"erreur": "Cette adresse a déjà servi.", "code": "depot_deja_utilise"}, status=409)
    fichier = request.FILES.get("fichier")
    if fichier is None:
        return JsonResponse({"erreur": "Fichier manquant (champ « fichier »).", "code": "donnees_invalides"}, status=400)
    probleme = probleme_fichier(fichier)
    if probleme:
        return JsonResponse({"erreur": probleme, "code": "donnees_invalides"}, status=400)
    # Réservation atomique : si deux dépôts arrivent en même temps, un seul passe
    if not Video.objects.filter(id=video.id, etat="attente_fichier").update(etat="reception"):
        return JsonResponse({"erreur": "Cette adresse a déjà servi.", "code": "depot_deja_utilise"}, status=409)
    video.fichier.save(fichier.name, fichier, save=False)
    video.etat = "en_attente"   # le worker youtube-worker l'enverra sur YouTube
    video.save(update_fields=["fichier", "etat"])
    return JsonResponse({"id": video.id, "etat": "en_attente"}, status=202)

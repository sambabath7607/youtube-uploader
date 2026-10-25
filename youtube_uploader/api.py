import threading

from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from .erreurs import message_erreur
from .models import Video, YouTubeCredentials
from .serializers import VideoSerializer
from .upload import upload_video
from .validation import LIMITE_ENVOIS_PAR_JOUR


class LimiteRequetes(UserRateThrottle):
    # Protège le serveur : 60 requêtes par minute et par utilisateur
    rate = "60/minute"


class PaginationVideos(PageNumberPagination):
    page_size = 20


def erreur(message, code, statut, details=None):
    contenu = {"erreur": message, "code": code}
    if details:
        contenu["details"] = details
    return Response(contenu, status=statut)


def envoyer_en_arriere_plan(video_id):
    video = Video.objects.get(id=video_id)
    video.etat = "en_cours"
    video.save()
    try:
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


@api_view(["GET", "POST"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([LimiteRequetes])
def api_videos(request):
    # GET : liste des vidéos de l'utilisateur, 20 par page
    if request.method == "GET":
        videos = Video.objects.filter(user=request.user).order_by("-created_at")
        pagination = PaginationVideos()
        page = pagination.paginate_queryset(videos, request)
        return pagination.get_paginated_response(VideoSerializer(page, many=True).data)

    # POST : nouvel envoi
    if not YouTubeCredentials.objects.filter(user=request.user).exists():
        return erreur(
            "Aucune chaîne YouTube connectée. Connecte ta chaîne sur la page d'accueil du site.",
            "youtube_non_connecte", status.HTTP_400_BAD_REQUEST,
        )
    debut_du_jour = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    envois_du_jour = Video.objects.filter(user=request.user, created_at__gte=debut_du_jour).count()
    if envois_du_jour >= LIMITE_ENVOIS_PAR_JOUR:
        return erreur(
            f"Limite de {LIMITE_ENVOIS_PAR_JOUR} envois par jour atteinte. Réessaie demain.",
            "limite_envois_atteinte", status.HTTP_429_TOO_MANY_REQUESTS,
        )
    serializer = VideoSerializer(data=request.data)
    if not serializer.is_valid():
        return erreur("Données invalides.", "donnees_invalides", status.HTTP_400_BAD_REQUEST, serializer.errors)
    video = serializer.save(user=request.user)
    threading.Thread(target=envoyer_en_arriere_plan, args=[video.id]).start()
    return Response(VideoSerializer(video).data, status=status.HTTP_202_ACCEPTED)


@api_view(["GET"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([LimiteRequetes])
def api_etat_video(request, video_id):
    # Une vidéo d'un autre utilisateur répond 404, comme si elle n'existait pas
    video = Video.objects.filter(id=video_id, user=request.user).first()
    if video is None:
        return erreur("Vidéo introuvable.", "video_introuvable", status.HTTP_404_NOT_FOUND)
    return Response(VideoSerializer(video).data)

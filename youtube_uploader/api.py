from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from accounts.authentification import CleApiAuthentication
from .envois import probleme_avant_envoi
from .models import Video
from .serializers import VideoSerializer


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


@api_view(["GET", "POST"])
@authentication_classes([CleApiAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([LimiteRequetes])
def api_videos(request):
    # GET : liste des vidéos de l'utilisateur, 20 par page
    if request.method == "GET":
        videos = Video.objects.filter(user=request.user).order_by("-created_at")
        pagination = PaginationVideos()
        page = pagination.paginate_queryset(videos, request)
        return pagination.get_paginated_response(VideoSerializer(page, many=True).data)

    # POST : nouvel envoi (le worker youtube-worker l'enverra sur YouTube)
    probleme = probleme_avant_envoi(request.user)
    if probleme:
        message, code = probleme
        statut = status.HTTP_429_TOO_MANY_REQUESTS if code == "limite_envois_atteinte" else status.HTTP_400_BAD_REQUEST
        return erreur(message, code, statut)
    serializer = VideoSerializer(data=request.data)
    if not serializer.is_valid():
        return erreur("Données invalides.", "donnees_invalides", status.HTTP_400_BAD_REQUEST, serializer.errors)
    video = serializer.save(user=request.user)
    return Response(VideoSerializer(video).data, status=status.HTTP_202_ACCEPTED)


@api_view(["GET"])
@authentication_classes([CleApiAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([LimiteRequetes])
def api_etat_video(request, video_id):
    # Une vidéo d'un autre utilisateur répond 404, comme si elle n'existait pas
    video = Video.objects.filter(id=video_id, user=request.user).first()
    if video is None:
        return erreur("Vidéo introuvable.", "video_introuvable", status.HTTP_404_NOT_FOUND)
    return Response(VideoSerializer(video).data)

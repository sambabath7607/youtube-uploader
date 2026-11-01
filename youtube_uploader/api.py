import logging

from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from accounts.authentification import CleApiAuthentication
from .envois import probleme_avant_envoi
from .models import Video, VoixUtilisateur, YouTubeCredentials
from .depot import adresse_depot
from .serializers import PreparationEnvoiSerializer, VideoSerializer
from .validation import LIMITE_ENVOIS_PAR_JOUR
from .voix import (essais_restants, etat_lecture, jeton_travail, lancer_lecture, lire_jeton, quota_restant,
                   secondes_estimees)

logger = logging.getLogger(__name__)
TEXTE_MAX = 120_000   # environ 1 h 20 d'audio


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


def duree_lisible(secondes):
    return f"{secondes // 60} min {secondes % 60:02d} s"


@api_view(["POST"])
@authentication_classes([CleApiAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([LimiteRequetes])
def api_voix(request):
    """Lance la lecture d'un texte avec la voix de l'utilisateur (calcul chez Modal)."""
    texte = str(request.data.get("texte") or "").strip()
    if not texte:
        return erreur("Le texte est vide.", "donnees_invalides", status.HTTP_400_BAD_REQUEST)
    if len(texte) > TEXTE_MAX:
        return erreur("Texte trop long (environ 1 h 20 maximum) : découpe-le en chapitres.", "texte_trop_long",
                      status.HTTP_400_BAD_REQUEST)
    voix = VoixUtilisateur.objects.filter(user=request.user).first()
    if voix is None or not voix.extrait or voix.consentement_le is None:
        return erreur("Aucune voix enregistrée. Enregistre ta voix sur la page « Ma voix » du site.", "voix_absente",
                      status.HTTP_400_BAD_REQUEST)
    if voix.mode != "en_ligne":
        return erreur(f"Ta voix est réglée sur « {voix.get_mode_display()} ». Choisis « En ligne » sur la page « Ma voix ».",
                      "mode_voix", status.HTTP_400_BAD_REQUEST)
    secondes, restant = secondes_estimees(texte), quota_restant(voix)
    if secondes > restant:
        return erreur(f"Quota de voix du mois insuffisant : il reste {duree_lisible(restant)}, ce texte demande environ "
                      f"{duree_lisible(secondes)}.", "quota_voix_atteint", status.HTTP_429_TOO_MANY_REQUESTS)
    try:
        with voix.extrait.open("rb") as f:
            id_appel = lancer_lecture(texte, f.read(), voix.passage_debut)
    except Exception:
        logger.exception("Service de voix : impossible de lancer la lecture")
        return erreur("Le service de voix est indisponible. Réessaie dans quelques minutes.", "service_voix_indisponible",
                      status.HTTP_503_SERVICE_UNAVAILABLE)
    voix.secondes_utilisees += secondes
    voix.save(update_fields=["secondes_utilisees"])
    return Response({"travail": jeton_travail(id_appel, request.user), "secondes_estimees": secondes,
                     "quota_restant": restant - secondes}, status=status.HTTP_202_ACCEPTED)


@api_view(["GET"])
@authentication_classes([CleApiAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([LimiteRequetes])
def api_etat_voix(request, travail):
    id_appel = lire_jeton(travail, request.user)
    if id_appel is None:
        return erreur("Travail de voix introuvable ou expiré.", "travail_introuvable", status.HTTP_404_NOT_FOUND)
    try:
        resultat = etat_lecture(id_appel)
    except Exception:
        logger.exception("Service de voix : le travail a échoué")
        return Response({"etat": "echoue", "erreur": "La fabrication de la voix a échoué. Relance fabriquer_voix."})
    if resultat is None:
        return Response({"etat": "en_cours"})
    return Response({"etat": "pret", "url_audio": resultat["url"], "duree": resultat["duree_audio"],
                     "minutage": resultat["minutage"]})


@api_view(["POST"])
@authentication_classes([CleApiAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([LimiteRequetes])
def api_preparer_envoi(request):
    """Réserve un envoi et renvoie une adresse de dépôt à usage unique (1 h) pour le fichier vidéo."""
    probleme = probleme_avant_envoi(request.user)
    if probleme:
        message, code = probleme
        statut = status.HTTP_429_TOO_MANY_REQUESTS if code == "limite_envois_atteinte" else status.HTTP_400_BAD_REQUEST
        return erreur(message, code, statut)
    serializer = PreparationEnvoiSerializer(data=request.data)
    if not serializer.is_valid():
        return erreur("Données invalides.", "donnees_invalides", status.HTTP_400_BAD_REQUEST, serializer.errors)
    video = serializer.save(user=request.user, etat="attente_fichier", fichier="")
    adresse = adresse_depot(request, video)
    return Response({
        "id": video.id,
        "adresse_depot": adresse,
        "expire_dans_secondes": 3600,
        "commande": f'curl -F "fichier=@CHEMIN_DE_LA_VIDEO" "{adresse}"',
    }, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@authentication_classes([CleApiAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([LimiteRequetes])
def api_mon_compte(request):
    """Résumé du compte pour Claude : chaîne connectée, voix, minutes restantes, envois restants aujourd'hui."""
    from django.utils import timezone
    youtube = YouTubeCredentials.objects.filter(user=request.user).first()
    voix = VoixUtilisateur.objects.filter(user=request.user).first()
    debut_du_jour = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    envois_du_jour = Video.objects.filter(user=request.user, created_at__gte=debut_du_jour).count()
    reponse = {
        "chaine_youtube": {
            "connectee": youtube is not None,
            "nom": (youtube.chaine_titre or None) if youtube else None,
            "remarque": None if (youtube is None or youtube.chaine_titre)
            else "Nom inconnu jusqu'au premier envoi (YouTube le donne à ce moment-là).",
        },
        "envois_restants_aujourd_hui": max(0, LIMITE_ENVOIS_PAR_JOUR - envois_du_jour),
        "voix": {"enregistree": False},
    }
    if voix is not None and voix.extrait and voix.consentement_le:
        restant = quota_restant(voix)
        reponse["voix"] = {
            "enregistree": True,
            "mode": voix.mode,
            "secondes_restantes_ce_mois": restant,
            "texte": f"{restant // 60} min {restant % 60:02d} s",
            "tests_restants_aujourd_hui": essais_restants(voix),
        }
    return Response(reponse)

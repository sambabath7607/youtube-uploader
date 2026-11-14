import logging

from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from accounts.authentification import AUTHENTIFICATIONS
from .envois import envoi_en_double, envois_du_jour, probleme_avant_envoi
from .fabrication import (MODELES, MUSIQUES, TYPES_SCENE, donnees_pour_modal, duree_estimee, duree_max,
                          lancer_fabrication, nouvelle_cle)
from .models import Video, VoixUtilisateur, YouTubeCredentials
from .depot import adresse_depot
from .serializers import FabricationSerializer, PreparationEnvoiSerializer, VideoSerializer
from .validation import LIMITE_ENVOIS_PAR_JOUR
from .voix import (essais_restants, etat_lecture, jeton_travail, lancer_lecture, lire_jeton, quota_restant,
                   secondes_estimees)

logger = logging.getLogger(__name__)
TEXTE_MAX = 120_000   # environ 1 h 20 d'audio
CODES_LIMITE = ("limite_envois_atteinte", "limite_service_atteinte")


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
@authentication_classes(AUTHENTIFICATIONS)
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
        statut = status.HTTP_429_TOO_MANY_REQUESTS if code in CODES_LIMITE else status.HTTP_400_BAD_REQUEST
        return erreur(message, code, statut)
    serializer = VideoSerializer(data=request.data)
    if not serializer.is_valid():
        return erreur("Données invalides.", "donnees_invalides", status.HTTP_400_BAD_REQUEST, serializer.errors)
    doublon = envoi_en_double(request.user, serializer.validated_data["titre"])
    if doublon is not None:
        return erreur(f"Cette vidéo est déjà en cours d'envoi (n° {doublon.id}) : suis-la avec etat_video.",
                      "envoi_en_double", status.HTTP_409_CONFLICT, {"id": doublon.id})
    video = serializer.save(user=request.user)
    return Response(VideoSerializer(video).data, status=status.HTTP_202_ACCEPTED)


@api_view(["GET"])
@authentication_classes(AUTHENTIFICATIONS)
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


def verifier_voix(user, texte):
    """Voix prête et quota suffisant pour lire ce texte. Renvoie (voix, secondes, restant, réponse d'erreur ou None)."""
    voix = VoixUtilisateur.objects.filter(user=user).first()
    if voix is None or not voix.extrait or voix.consentement_le is None:
        return None, 0, 0, erreur("Aucune voix enregistrée. Enregistre ta voix sur la page « Ma voix » du site.",
                                  "voix_absente", status.HTTP_400_BAD_REQUEST)
    if voix.mode != "en_ligne":
        return None, 0, 0, erreur(f"Ta voix est réglée sur « {voix.get_mode_display()} ». Choisis « En ligne » sur la "
                                  "page « Ma voix ».", "mode_voix", status.HTTP_400_BAD_REQUEST)
    secondes, restant = secondes_estimees(texte), quota_restant(voix)
    if secondes > restant:
        return None, 0, 0, erreur(f"Quota de voix du mois insuffisant : il reste {duree_lisible(restant)}, ce texte "
                                  f"demande environ {duree_lisible(secondes)}.", "quota_voix_atteint",
                                  status.HTTP_429_TOO_MANY_REQUESTS)
    return voix, secondes, restant, None


@api_view(["POST"])
@authentication_classes(AUTHENTIFICATIONS)
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
    voix, secondes, restant, probleme = verifier_voix(request.user, texte)
    if probleme:
        return probleme
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
@authentication_classes(AUTHENTIFICATIONS)
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
@authentication_classes(AUTHENTIFICATIONS)
@permission_classes([IsAuthenticated])
@throttle_classes([LimiteRequetes])
def api_preparer_envoi(request):
    """Réserve un envoi et renvoie une adresse de dépôt à usage unique (1 h) pour le fichier vidéo."""
    probleme = probleme_avant_envoi(request.user)
    if probleme:
        message, code = probleme
        statut = status.HTTP_429_TOO_MANY_REQUESTS if code in CODES_LIMITE else status.HTTP_400_BAD_REQUEST
        return erreur(message, code, statut)
    serializer = PreparationEnvoiSerializer(data=request.data)
    if not serializer.is_valid():
        return erreur("Données invalides.", "donnees_invalides", status.HTTP_400_BAD_REQUEST, serializer.errors)
    doublon = envoi_en_double(request.user, serializer.validated_data["titre"])
    if doublon is not None and doublon.etat != "attente_fichier":
        return erreur(f"Cette vidéo est déjà en cours d'envoi (n° {doublon.id}) : suis-la avec etat_video.",
                      "envoi_en_double", status.HTTP_409_CONFLICT, {"id": doublon.id})
    # Même demande répétée (Claude a réessayé) : on redonne une adresse pour le même envoi au lieu d'en créer un 2e
    video = doublon or serializer.save(user=request.user, etat="attente_fichier", fichier="")
    adresse = adresse_depot(request, video)
    return Response({
        "id": video.id,
        "adresse_depot": adresse,
        "expire_dans_secondes": 3600,
        "commande": f'curl -F "fichier=@CHEMIN_DE_LA_VIDEO" "{adresse}"',
    }, status=status.HTTP_201_CREATED)


def preferences_publication(user):
    """Réponses par défaut aux questions de YouTube ; None = « demander à l'utilisateur »."""
    from .models import PreferencesPublication
    prefs = PreferencesPublication.objects.filter(user=user).first()
    return {
        "pour_enfants": prefs.pour_enfants if prefs else None,
        "contenu_ia": prefs.contenu_ia if prefs else None,
        "visibilite": (prefs.visibilite or None) if prefs else None,
        "regle": "Une valeur null = pose la question à l'utilisateur. Sinon utilise la valeur sans redemander "
                 "et rappelle-la dans ton récapitulatif.",
    }


@api_view(["GET"])
@authentication_classes(AUTHENTIFICATIONS)
@permission_classes([IsAuthenticated])
@throttle_classes([LimiteRequetes])
def api_mon_compte(request):
    """Résumé du compte pour Claude : chaîne connectée, voix, minutes restantes, envois restants aujourd'hui."""
    youtube = YouTubeCredentials.objects.filter(user=request.user).first()
    voix = VoixUtilisateur.objects.filter(user=request.user).first()
    nb_envois = envois_du_jour().filter(user=request.user).count()
    reponse = {
        "chaine_youtube": {
            "connectee": youtube is not None,
            "nom": (youtube.chaine_titre or None) if youtube else None,
            "remarque": None if (youtube is None or youtube.chaine_titre)
            else "Nom inconnu jusqu'au premier envoi (YouTube le donne à ce moment-là).",
        },
        "envois_restants_aujourd_hui": max(0, LIMITE_ENVOIS_PAR_JOUR - nb_envois),
        "voix": {"enregistree": False},
        "preferences_publication": preferences_publication(request.user),
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


@api_view(["POST"])
@authentication_classes(AUTHENTIFICATIONS)
@permission_classes([IsAuthenticated])
@throttle_classes([LimiteRequetes])
def api_fabrications(request):
    """Fabrique une vidéo sur nos serveurs (Modal) à partir d'un modèle, puis l'envoie sur YouTube (202 + id).
    Suivi : GET /youtube/api/v1/videos/<id>/ (etat « fabrication » avec l'étape, puis l'envoi habituel)."""
    probleme = probleme_avant_envoi(request.user)
    if probleme:
        message, code = probleme
        statut = status.HTTP_429_TOO_MANY_REQUESTS if code in CODES_LIMITE else status.HTTP_400_BAD_REQUEST
        return erreur(message, code, statut)
    serializer = FabricationSerializer(data=request.data)
    if not serializer.is_valid():
        return erreur("Données invalides.", "donnees_invalides", status.HTTP_400_BAD_REQUEST, serializer.errors)
    d = serializer.validated_data
    en_cours = Video.objects.filter(user=request.user, etat="fabrication").first()
    if en_cours is not None:
        # Une fabrication à la fois par client (protège les machines et le budget)
        return erreur(f"Une vidéo est déjà en fabrication (n° {en_cours.id}) : attends qu'elle soit finie "
                      "(etat_video), puis relance.", "fabrication_en_cours", status.HTTP_409_CONFLICT,
                      {"id": en_cours.id})
    doublon = envoi_en_double(request.user, d["titre"])
    if doublon is not None:
        return erreur(f"Cette vidéo est déjà en cours (n° {doublon.id}) : suis-la avec etat_video.",
                      "envoi_en_double", status.HTTP_409_CONFLICT, {"id": doublon.id})
    duree, maximum = duree_estimee(d["script"]), duree_max(d["modele"])
    if duree > maximum:
        return erreur(f"Vidéo trop longue : environ {duree_lisible(round(duree))} pour ce script, "
                      f"{duree_lisible(maximum)} au maximum avec le modèle « {d['modele']} ». Raccourcis le script.",
                      "video_trop_longue", status.HTTP_400_BAD_REQUEST)
    voix, secondes = None, 0
    if d["avec_ma_voix"]:
        voix, secondes, _, probleme = verifier_voix(request.user, d["script"])
        if probleme:
            return probleme
    video = Video.objects.create(
        user=request.user, titre=d["titre"], description=d["description"], fichier="", pour_enfants=d["pour_enfants"],
        contenu_ia=d["contenu_ia"], visibilite=d["visibilite"], etat="fabrication", etape="Préparation",
        modele=d["modele"], duree_secondes=round(duree),
        donnees_modele={"script": d["script"], "scenes": d["scenes"], "accent": d["accent"], "musique": d["musique"],
                        "avec_ma_voix": d["avec_ma_voix"], "secondes_voix": 0},
    )
    video.donnees_modele["cle"] = nouvelle_cle(video.id)
    try:
        if voix is not None:
            with voix.extrait.open("rb") as f:
                donnees = donnees_pour_modal(video, f.read(), voix.passage_debut)
        else:
            donnees = donnees_pour_modal(video)
        video.appel_modal = lancer_fabrication(donnees)
    except Exception:
        logger.exception("Fabrication : impossible de lancer le rendu chez Modal")
        video.delete()   # rien n'a été lancé : la vidéo ne compte pas dans les limites
        return erreur("Le service de fabrication des vidéos est indisponible. Réessaie dans quelques minutes.",
                      "service_video_indisponible", status.HTTP_503_SERVICE_UNAVAILABLE)
    if voix is not None:
        voix.secondes_utilisees += secondes
        voix.save(update_fields=["secondes_utilisees"])
        video.donnees_modele["secondes_voix"] = secondes   # rendues au client si la fabrication échoue
    video.save(update_fields=["appel_modal", "donnees_modele"])
    return Response(VideoSerializer(video).data, status=status.HTTP_202_ACCEPTED)


def catalogue_modeles():
    """Liste des modèles et de leurs champs : l'agent IA sait exactement quoi remplir."""
    return {
        "modeles": [
            {"nom": nom, "titre": m["nom"], "description": m["description"], "format": m["format"],
             "duree_max_secondes": duree_max(nom), "scenes_max": m.get("max_scenes", 30), "types_de_scene": m["types"],
             "exemple": m["exemple"]}
            for nom, m in MODELES.items()
        ],
        "types_de_scene": TYPES_SCENE,
        "musiques": MUSIQUES,
        "regles": [
            "Une scène = un paragraphe du script (paragraphes séparés par une ligne vide) : même nombre des deux côtés.",
            "La durée de chaque scène suit la voix : aucune durée à donner.",
            "Champs d'une scène : type, texte (200 caractères max), points (6 max, 90 caractères chacun), "
            "code (20 lignes max), langage.",
            "accent : couleur #RRGGBB (facultatif). musique : calme, energique ou aucune.",
        ],
    }


@api_view(["GET"])
@authentication_classes(AUTHENTIFICATIONS)
@permission_classes([IsAuthenticated])
@throttle_classes([LimiteRequetes])
def api_modeles(request):
    """Modèles de vidéos disponibles et champs à remplir (outil modeles_video du connecteur)."""
    return Response(catalogue_modeles())

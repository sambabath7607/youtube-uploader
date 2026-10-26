import os
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import json

from .chiffrement import chiffrer, dechiffrer

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

DOSSIER = os.path.dirname(os.path.abspath(__file__))


def upload_video(chemin_video, titre, description="", statut="private", user=None,
                 pour_enfants=False, contenu_ia=False):
    # Toujours le jeton chiffré de l'utilisateur, rangé en base (plus de fichier token.json)
    if user is None:
        raise ValueError("Un envoi doit toujours être fait pour un utilisateur connecté.")
    creds = get_credentials_user(user)
    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {"title": titre, "description": description},
        "status": {
            "privacyStatus": statut,
            "selfDeclaredMadeForKids": pour_enfants,
            "containsSyntheticMedia": contenu_ia,
        },
    }
    media = MediaFileUpload(chemin_video, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    return response["id"]

def get_credentials_user(user):
    from .models import YouTubeCredentials
    ligne = YouTubeCredentials.objects.get(user=user)
    creds = Credentials.from_authorized_user_info(json.loads(dechiffrer(ligne.token_json)), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        ligne.token_json = chiffrer(creds.to_json())
        ligne.save()
    return creds
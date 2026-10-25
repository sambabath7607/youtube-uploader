import os
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import json

from .chiffrement import chiffrer, dechiffrer

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

DOSSIER = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRET = os.path.join(DOSSIER, "client_secret.json")
TOKEN = os.path.join(DOSSIER, "token.json")


def get_credentials():
    creds = None
    if os.path.exists(TOKEN):
        creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
            creds = flow.run_local_server(port=0 , open_browser= False)
        with open(TOKEN, "w") as f:
            f.write(creds.to_json())
    return creds


def upload_video(chemin_video, titre, description="", statut="private", user=None,
                 pour_enfants=False, contenu_ia=False):
    if user:
        creds = get_credentials_user(user)
    else:
        creds = get_credentials()
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
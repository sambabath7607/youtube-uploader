import json
import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from .erreurs import message_erreur
from .models import Video, YouTubeCredentials
from .validation import LIMITE_ENVOIS_PAR_JOUR

DOSSIER_MEDIA_TEST = tempfile.mkdtemp()


def faux_fichier(nom="video.mp4"):
    return SimpleUploadedFile(nom, b"contenu", content_type="video/mp4")


@override_settings(MEDIA_ROOT=DOSSIER_MEDIA_TEST)
@patch("youtube_uploader.api.threading.Thread")  # aucun vrai envoi vers YouTube pendant les tests
class ApiVideosTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER_MEDIA_TEST, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user(username="samba", password="motdepasse123")
        YouTubeCredentials.objects.create(user=self.user, token_json="{}")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Token " + Token.objects.create(user=self.user).key)
        self.url = reverse("api_videos")

    def envoyer(self, **donnees):
        valeurs = {"titre": "Test", "pour_enfants": "false", "fichier": faux_fichier()}
        valeurs.update(donnees)
        valeurs = {cle: valeur for cle, valeur in valeurs.items() if valeur is not None}
        return self.client.post(self.url, valeurs, format="multipart")

    def test_envoi_accepte_202_sans_chemin_du_fichier(self, thread):
        reponse = self.envoyer()
        self.assertEqual(reponse.status_code, 202)
        self.assertEqual(reponse.json()["etat"], "en_attente")
        self.assertNotIn("fichier", reponse.json())
        thread.return_value.start.assert_called_once()

    def test_pour_enfants_obligatoire(self, thread):
        reponse = self.envoyer(pour_enfants=None)
        self.assertEqual(reponse.status_code, 400)
        self.assertEqual(reponse.json()["code"], "donnees_invalides")
        self.assertIn("pour_enfants", reponse.json()["details"])
        self.assertFalse(Video.objects.exists())

    def test_format_de_fichier_refuse(self, thread):
        reponse = self.envoyer(fichier=faux_fichier("image.png"))
        self.assertEqual(reponse.status_code, 400)
        self.assertIn("fichier", reponse.json()["details"])

    def test_titre_trop_long(self, thread):
        reponse = self.envoyer(titre="a" * 101)
        self.assertEqual(reponse.status_code, 400)
        self.assertIn("titre", reponse.json()["details"])

    def test_chaine_non_connectee(self, thread):
        YouTubeCredentials.objects.all().delete()
        reponse = self.envoyer()
        self.assertEqual(reponse.status_code, 400)
        self.assertEqual(reponse.json()["code"], "youtube_non_connecte")

    def test_limite_envois_par_jour(self, thread):
        for _ in range(LIMITE_ENVOIS_PAR_JOUR):
            self.assertEqual(self.envoyer().status_code, 202)
        reponse = self.envoyer()
        self.assertEqual(reponse.status_code, 429)
        self.assertEqual(reponse.json()["code"], "limite_envois_atteinte")

    def test_cle_absente_401(self, thread):
        self.client.credentials()
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_liste_paginee_et_seulement_mes_videos(self, thread):
        autre = User.objects.create_user(username="autre", password="motdepasse123")
        Video.objects.create(user=autre, titre="Pas à moi", pour_enfants=False, fichier="videos/x.mp4")
        Video.objects.create(user=self.user, titre="À moi", pour_enfants=False, fichier="videos/y.mp4")
        reponse = self.client.get(self.url)
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()["count"], 1)
        self.assertEqual(reponse.json()["results"][0]["titre"], "À moi")

    def test_video_d_un_autre_404(self, thread):
        autre = User.objects.create_user(username="autre", password="motdepasse123")
        video = Video.objects.create(user=autre, titre="Pas à moi", pour_enfants=False, fichier="videos/x.mp4")
        reponse = self.client.get(reverse("api_etat_video", args=[video.id]))
        self.assertEqual(reponse.status_code, 404)
        self.assertEqual(reponse.json()["code"], "video_introuvable")

    def test_etat_de_ma_video(self, thread):
        video = Video.objects.create(user=self.user, titre="À moi", pour_enfants=False, fichier="videos/y.mp4")
        reponse = self.client.get(reverse("api_etat_video", args=[video.id]))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()["titre"], "À moi")

    @override_settings(REST_FRAMEWORK={"EXCEPTION_HANDLER": "youtube_uploader.erreurs.gestionnaire_erreurs_api"})
    def test_gestionnaire_d_erreurs_pret(self, thread):
        self.client.credentials()
        reponse = self.client.get(self.url)
        self.assertEqual(reponse.status_code, 401)
        self.assertEqual(reponse.json()["code"], "non_authentifie")


class MessageErreurTests(TestCase):
    def test_limite_youtube_garde_le_nom_de_l_erreur(self):
        from googleapiclient.errors import HttpError

        class FausseReponse(dict):
            status = 400
            reason = "Bad Request"

        contenu = {"error": {"errors": [{"reason": "uploadLimitExceeded", "message": "limite"}], "message": "limite"}}
        erreur = HttpError(FausseReponse(), json.dumps(contenu).encode())
        message = message_erreur(erreur)
        self.assertIn("uploadLimitExceeded", message)
        self.assertIn("24 h", message)


class DeconnecterYoutubeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="samba", password="motdepasse123")
        YouTubeCredentials.objects.create(user=self.user, token_json=json.dumps({"refresh_token": "abc"}))
        self.client.login(username="samba", password="motdepasse123")

    @patch("youtube_uploader.oauth.requests.post")
    def test_deconnecter_supprime_et_revoque(self, post):
        post.return_value.status_code = 200
        reponse = self.client.post(reverse("deconnecter_youtube"))
        self.assertRedirects(reponse, reverse("accueil"))
        self.assertFalse(YouTubeCredentials.objects.filter(user=self.user).exists())
        self.assertEqual(post.call_args.kwargs["params"], {"token": "abc"})

    def test_deconnecter_refuse_en_get(self):
        reponse = self.client.get(reverse("deconnecter_youtube"))
        self.assertEqual(reponse.status_code, 405)
        self.assertTrue(YouTubeCredentials.objects.filter(user=self.user).exists())

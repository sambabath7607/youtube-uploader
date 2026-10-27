import json
import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import CleApi

from .chiffrement import JetonIllisible, chiffrer, dechiffrer
from .envois import MESSAGE_INTERROMPU, prendre_prochaine_video
from .erreurs import message_erreur
from .models import Video, YouTubeCredentials
from .validation import LIMITE_ENVOIS_PAR_JOUR

DOSSIER_MEDIA_TEST = tempfile.mkdtemp()


def faux_fichier(nom="video.mp4"):
    return SimpleUploadedFile(nom, b"contenu", content_type="video/mp4")


@override_settings(MEDIA_ROOT=DOSSIER_MEDIA_TEST)
class ApiVideosTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER_MEDIA_TEST, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user(username="samba", password="motdepasse123")
        YouTubeCredentials.objects.create(user=self.user, token_json="{}")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Token " + CleApi.creer_pour(self.user))
        self.url = reverse("api_videos")

    def envoyer(self, **donnees):
        valeurs = {"titre": "Test", "pour_enfants": "false", "fichier": faux_fichier()}
        valeurs.update(donnees)
        valeurs = {cle: valeur for cle, valeur in valeurs.items() if valeur is not None}
        return self.client.post(self.url, valeurs, format="multipart")

    def test_envoi_accepte_202_sans_chemin_du_fichier(self):
        reponse = self.envoyer()
        self.assertEqual(reponse.status_code, 202)
        self.assertEqual(reponse.json()["etat"], "en_attente")
        self.assertNotIn("fichier", reponse.json())

    def test_pour_enfants_obligatoire(self):
        reponse = self.envoyer(pour_enfants=None)
        self.assertEqual(reponse.status_code, 400)
        self.assertEqual(reponse.json()["code"], "donnees_invalides")
        self.assertIn("pour_enfants", reponse.json()["details"])
        self.assertFalse(Video.objects.exists())

    def test_format_de_fichier_refuse(self):
        reponse = self.envoyer(fichier=faux_fichier("image.png"))
        self.assertEqual(reponse.status_code, 400)
        self.assertIn("fichier", reponse.json()["details"])

    def test_titre_trop_long(self):
        reponse = self.envoyer(titre="a" * 101)
        self.assertEqual(reponse.status_code, 400)
        self.assertIn("titre", reponse.json()["details"])

    def test_chaine_non_connectee(self):
        YouTubeCredentials.objects.all().delete()
        reponse = self.envoyer()
        self.assertEqual(reponse.status_code, 400)
        self.assertEqual(reponse.json()["code"], "youtube_non_connecte")

    def test_limite_envois_par_jour(self):
        for _ in range(LIMITE_ENVOIS_PAR_JOUR):
            self.assertEqual(self.envoyer().status_code, 202)
        reponse = self.envoyer()
        self.assertEqual(reponse.status_code, 429)
        self.assertEqual(reponse.json()["code"], "limite_envois_atteinte")

    def test_cle_absente_401(self):
        self.client.credentials()
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_fausse_cle_401(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + "0" * 40)
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_cle_d_un_compte_desactive_401(self):
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_liste_paginee_et_seulement_mes_videos(self):
        autre = User.objects.create_user(username="autre", password="motdepasse123")
        Video.objects.create(user=autre, titre="Pas à moi", pour_enfants=False, fichier="videos/x.mp4")
        Video.objects.create(user=self.user, titre="À moi", pour_enfants=False, fichier="videos/y.mp4")
        reponse = self.client.get(self.url)
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()["count"], 1)
        self.assertEqual(reponse.json()["results"][0]["titre"], "À moi")

    def test_video_d_un_autre_404(self):
        autre = User.objects.create_user(username="autre", password="motdepasse123")
        video = Video.objects.create(user=autre, titre="Pas à moi", pour_enfants=False, fichier="videos/x.mp4")
        reponse = self.client.get(reverse("api_etat_video", args=[video.id]))
        self.assertEqual(reponse.status_code, 404)
        self.assertEqual(reponse.json()["code"], "video_introuvable")

    def test_etat_de_ma_video(self):
        video = Video.objects.create(user=self.user, titre="À moi", pour_enfants=False, fichier="videos/y.mp4")
        reponse = self.client.get(reverse("api_etat_video", args=[video.id]))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()["titre"], "À moi")

    @override_settings(REST_FRAMEWORK={"EXCEPTION_HANDLER": "youtube_uploader.erreurs.gestionnaire_erreurs_api"})
    def test_gestionnaire_d_erreurs_pret(self):
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

    def test_autorisation_expiree_message_clair(self):
        from google.auth.exceptions import RefreshError
        self.assertIn("Reconnecte ta chaîne", message_erreur(RefreshError("invalid_grant")))

    def test_erreur_inattendue_sans_detail_interne(self):
        with self.assertLogs("youtube_uploader.erreurs", level="ERROR"):
            message = message_erreur(OSError("/home/batch/youtube-uploader/media/videos/secret.mp4"))
        self.assertNotIn("/home/batch", message)
        self.assertIn("Erreur inattendue", message)


class DeconnecterYoutubeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="samba", password="motdepasse123")
        YouTubeCredentials.objects.create(user=self.user, token_json=chiffrer(json.dumps({"refresh_token": "abc"})))
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

    @patch("youtube_uploader.oauth.requests.post")
    def test_deconnecter_meme_avec_jeton_illisible(self, post):
        YouTubeCredentials.objects.filter(user=self.user).update(token_json='{"refresh_token": "en clair"}')
        with self.assertLogs("youtube_uploader.chiffrement", level="ERROR"):
            self.client.post(reverse("deconnecter_youtube"))
        self.assertFalse(YouTubeCredentials.objects.filter(user=self.user).exists())
        post.assert_not_called()


class DechiffrementTests(TestCase):
    def test_jeton_en_clair_refuse(self):
        with self.assertLogs("youtube_uploader.chiffrement", level="ERROR"):
            with self.assertRaises(JetonIllisible):
                dechiffrer('{"token": "en clair"}')

    def test_jeton_illisible_message_clair(self):
        self.assertIn("Reconnecte ta chaîne", message_erreur(JetonIllisible()))


class RetourGoogleTests(TestCase):
    """Le retour de Google (oauth_callback) affiche un message clair au lieu d'une erreur 500."""

    def setUp(self):
        self.user = User.objects.create_user(username="samba", password="motdepasse123")
        self.client.force_login(self.user)
        self.url = reverse("oauth_callback")

    def test_connexion_annulee_chez_google(self):
        reponse = self.client.get(self.url + "?error=access_denied", follow=True)
        self.assertContains(reponse, "Connexion annulée")
        self.assertFalse(YouTubeCredentials.objects.filter(user=self.user).exists())

    def test_lien_invalide_sans_etat(self):
        reponse = self.client.get(self.url + "?code=abc&state=xyz", follow=True)
        self.assertContains(reponse, "Lien de connexion invalide")

    @patch("youtube_uploader.oauth.creer_flow")
    def test_google_refuse_le_code(self, creer_flow):
        creer_flow.return_value.fetch_token.side_effect = Exception("invalid_grant")
        session = self.client.session
        session["oauth_state"] = "xyz"
        session.save()
        reponse = self.client.get(self.url + "?code=abc&state=xyz", follow=True)
        self.assertContains(reponse, "pas pu confirmer la connexion")
        self.assertNotIn("oauth_state", self.client.session)
        self.assertFalse(YouTubeCredentials.objects.filter(user=self.user).exists())


class EnvoiSansUtilisateurTests(TestCase):
    def test_plus_d_envoi_avec_le_fichier_token_json(self):
        from .upload import upload_video
        with self.assertRaises(ValueError):
            upload_video("video.mp4", "Titre")


@override_settings(MEDIA_ROOT=DOSSIER_MEDIA_TEST)
class WorkerTests(TestCase):
    """La file d'attente : le worker (commande traiter_envois) envoie les vidéos une par une."""

    def setUp(self):
        self.user = User.objects.create_user(username="samba", password="motdepasse123")

    def video(self, etat="en_attente"):
        return Video.objects.create(user=self.user, titre="Test", pour_enfants=False, etat=etat,
                                    fichier=faux_fichier())

    @patch("youtube_uploader.envois.upload_video", return_value="abc123")
    def test_le_worker_envoie_la_video_en_attente(self, upload):
        video = self.video()
        call_command("traiter_envois", "--une-fois")
        video.refresh_from_db()
        self.assertEqual(video.etat, "reussi")
        self.assertEqual(video.youtube_id, "abc123")
        self.assertFalse(video.fichier)
        upload.assert_called_once()

    @patch("youtube_uploader.envois.upload_video", side_effect=RuntimeError("/home/batch/secret"))
    def test_echec_avec_message_sans_detail(self, upload):
        video = self.video()
        with self.assertLogs("youtube_uploader.erreurs", level="ERROR"):
            call_command("traiter_envois", "--une-fois")
        video.refresh_from_db()
        self.assertEqual(video.etat, "echoue")
        self.assertNotIn("/home/batch", video.erreur)

    def test_une_video_n_est_jamais_prise_deux_fois(self):
        video = self.video()
        self.assertEqual(prendre_prochaine_video().id, video.id)
        self.assertIsNone(prendre_prochaine_video())

    @patch("youtube_uploader.envois.upload_video")
    def test_envoi_interrompu_passe_en_echec_sans_renvoi(self, upload):
        video = self.video(etat="en_cours")
        with self.assertLogs("youtube_uploader.envois", level="WARNING"):
            call_command("traiter_envois", "--une-fois")
        video.refresh_from_db()
        self.assertEqual(video.etat, "echoue")
        self.assertEqual(video.erreur, MESSAGE_INTERROMPU)
        upload.assert_not_called()


@override_settings(MEDIA_ROOT=DOSSIER_MEDIA_TEST)
class FormulaireEnvoiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="samba", password="motdepasse123")
        YouTubeCredentials.objects.create(user=self.user, token_json="{}")
        self.client.force_login(self.user)

    def envoyer(self):
        return self.client.post(reverse("nouvelle_video"),
                                {"titre": "Test", "pour_enfants": "False", "fichier": faux_fichier()})

    @patch("youtube_uploader.envois.upload_video")
    def test_formulaire_met_en_attente_sans_envoyer(self, upload):
        reponse = self.envoyer()
        video = Video.objects.get()
        self.assertRedirects(reponse, reverse("suivi_video", args=[video.id]))
        self.assertEqual(video.etat, "en_attente")
        upload.assert_not_called()
        suivi = self.client.get(reverse("suivi_video", args=[video.id]))
        self.assertContains(suivi, 'http-equiv="refresh"')

    def test_formulaire_refuse_sans_chaine_connectee(self):
        YouTubeCredentials.objects.all().delete()
        self.assertContains(self.envoyer(), "Aucune chaîne YouTube connectée")
        self.assertFalse(Video.objects.exists())

    def test_formulaire_respecte_la_limite_par_jour(self):
        for _ in range(LIMITE_ENVOIS_PAR_JOUR):
            Video.objects.create(user=self.user, titre="x", pour_enfants=False, fichier="videos/x.mp4")
        self.assertContains(self.envoyer(), "envois par jour atteinte")
        self.assertEqual(Video.objects.count(), LIMITE_ENVOIS_PAR_JOUR)

    def test_suivi_de_la_video_d_un_autre_404(self):
        autre = User.objects.create_user(username="autre", password="motdepasse123")
        video = Video.objects.create(user=autre, titre="x", pour_enfants=False, fichier="videos/x.mp4")
        self.assertEqual(self.client.get(reverse("suivi_video", args=[video.id])).status_code, 404)

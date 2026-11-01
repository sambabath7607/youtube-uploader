import json
from datetime import date, timedelta
import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import CleApi

from .chiffrement import JetonIllisible, chiffrer, dechiffrer
from .envois import MESSAGE_INTERROMPU, prendre_prochaine_video
from .erreurs import message_erreur
from .models import Video, VoixUtilisateur, YouTubeCredentials
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
        for i in range(LIMITE_ENVOIS_PAR_JOUR):
            self.assertEqual(self.envoyer(titre=f"Vidéo {i}").status_code, 202)
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

    @patch("youtube_uploader.envois.upload_video", return_value={"id": "abc123", "snippet": {"channelTitle": "BATCH CODE AI", "channelId": "UC123"}})
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
                                {"titre": "Test", "pour_enfants": "False", "visibilite": "private", "fichier": faux_fichier()})

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


@override_settings(MEDIA_ROOT=DOSSIER_MEDIA_TEST)
class MaVoixTests(TestCase):
    """Page « Ma voix » : enregistrement avec consentement, suppression, choix du mode."""

    def setUp(self):
        from . import models
        self.dossier = tempfile.mkdtemp()
        self.ancien_emplacement = models.stockage_prive.location
        models.stockage_prive.location = self.dossier   # les tests n'écrivent jamais dans src/prive/
        self.user = User.objects.create_user(username="samba", password="motdepasse123")
        self.client.force_login(self.user)
        self.url = reverse("ma_voix")

    def tearDown(self):
        from . import models
        models.stockage_prive.location = self.ancien_emplacement
        shutil.rmtree(self.dossier, ignore_errors=True)

    def envoyer(self, consentement=True, contenu=b"son"):
        donnees = {"action": "enregistrer", "extrait": SimpleUploadedFile("voix.webm", contenu, content_type="audio/webm")}
        if consentement:
            donnees["consentement"] = "on"
        return self.client.post(self.url, donnees, follow=True)

    def test_page_interdite_sans_connexion(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_refus_sans_consentement(self):
        self.assertContains(self.envoyer(consentement=False), "propre voix")
        self.assertFalse(VoixUtilisateur.objects.get(user=self.user).extrait)

    def test_refus_fichier_trop_lourd(self):
        with patch("youtube_uploader.views.TAILLE_MAX_VOIX", 2):
            self.assertContains(self.envoyer(), "trop lourd")
        self.assertFalse(VoixUtilisateur.objects.get(user=self.user).extrait)

    def test_enregistrement_accepte(self):
        self.assertContains(self.envoyer(), "Ta voix est enregistrée")
        voix = VoixUtilisateur.objects.get(user=self.user)
        self.assertTrue(voix.extrait)
        self.assertIsNotNone(voix.consentement_le)

    def test_suppression(self):
        self.envoyer()
        self.client.post(self.url, {"action": "supprimer"})
        voix = VoixUtilisateur.objects.get(user=self.user)
        self.assertFalse(voix.extrait)
        self.assertIsNone(voix.consentement_le)

    def test_ecouter_sa_voix(self):
        self.envoyer()
        reponse = self.client.get(reverse("ecouter_ma_voix"))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(b"".join(reponse.streaming_content), b"son")
        self.assertEqual(reponse["Cache-Control"], "no-store")

    def test_ecouter_sans_voix_404(self):
        self.assertEqual(self.client.get(reverse("ecouter_ma_voix")).status_code, 404)

    def test_choix_du_mode(self):
        self.envoyer()
        self.client.post(self.url, {"action": "mode", "mode": "en_ligne"})
        self.assertEqual(VoixUtilisateur.objects.get(user=self.user).mode, "en_ligne")
        self.client.post(self.url, {"action": "mode", "mode": "nimporte"})
        self.assertEqual(VoixUtilisateur.objects.get(user=self.user).mode, "aucune")


class ApiVoixTests(TestCase):
    """API de voix : vérifications avant d'appeler Modal (le calcul lui-même est simulé)."""

    def setUp(self):
        from . import models
        self.dossier = tempfile.mkdtemp()
        self.ancien_emplacement = models.stockage_prive.location
        models.stockage_prive.location = self.dossier
        self.user = User.objects.create_user(username="samba", password="motdepasse123")
        self.voix = VoixUtilisateur.objects.create(user=self.user, mode="en_ligne", consentement_le=timezone.now())
        self.voix.extrait.save("voix.webm", SimpleUploadedFile("voix.webm", b"son"))
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Token " + CleApi.creer_pour(self.user))

    def tearDown(self):
        from . import models
        models.stockage_prive.location = self.ancien_emplacement
        shutil.rmtree(self.dossier, ignore_errors=True)

    def lancer(self, texte="Bonjour à tous. " * 10):
        return self.client.post(reverse("api_voix"), {"texte": texte}, format="json")

    @patch("youtube_uploader.api.lancer_lecture", return_value="fc-123")
    def test_lecture_lancee_et_quota_decompte(self, lancer):
        reponse = self.lancer()
        self.assertEqual(reponse.status_code, 202)
        self.assertIn("travail", reponse.json())
        self.assertEqual(lancer.call_args.args[1], b"son")
        self.assertEqual(lancer.call_args.args[2], 0)      # passage choisi transmis à Modal
        self.voix.refresh_from_db()
        self.assertEqual(self.voix.secondes_utilisees, reponse.json()["secondes_estimees"])

    def test_sans_voix_enregistree(self):
        self.voix.extrait.delete()
        self.assertEqual(self.lancer().json()["code"], "voix_absente")

    def test_mode_autre_que_en_ligne(self):
        self.voix.mode = "aucune"
        self.voix.save()
        self.assertEqual(self.lancer().json()["code"], "mode_voix")

    def test_quota_atteint(self):
        self.voix.secondes_utilisees = 600
        self.voix.mois_du_compteur = timezone.localdate().replace(day=1)
        self.voix.save()
        reponse = self.lancer()
        self.assertEqual(reponse.status_code, 429)
        self.assertEqual(reponse.json()["code"], "quota_voix_atteint")

    def test_compteur_remis_a_zero_chaque_mois(self):
        self.voix.secondes_utilisees = 600
        self.voix.mois_du_compteur = date(2020, 1, 1)
        self.voix.save()
        with patch("youtube_uploader.api.lancer_lecture", return_value="fc-1"):
            self.assertEqual(self.lancer().status_code, 202)

    @patch("youtube_uploader.api.lancer_lecture", side_effect=RuntimeError("modal en panne"))
    def test_service_indisponible_sans_decompte(self, lancer):
        with self.assertLogs("youtube_uploader.api", level="ERROR"):
            self.assertEqual(self.lancer().status_code, 503)
        self.voix.refresh_from_db()
        self.assertEqual(self.voix.secondes_utilisees, 0)

    @patch("youtube_uploader.api.lancer_lecture", return_value="fc-123")
    def test_etat_en_cours_puis_pret(self, lancer):
        travail = self.lancer().json()["travail"]
        url = reverse("api_etat_voix", args=[travail])
        with patch("youtube_uploader.api.etat_lecture", return_value=None):
            self.assertEqual(self.client.get(url).json()["etat"], "en_cours")
        resultat = {"url": "https://exemple.modal.run/?jeton=abc", "duree_audio": 4.0, "minutage": []}
        with patch("youtube_uploader.api.etat_lecture", return_value=resultat) as etat:
            reponse = self.client.get(url).json()
        self.assertEqual(reponse["etat"], "pret")
        self.assertEqual(etat.call_args.args[0], "fc-123")

    @patch("youtube_uploader.api.lancer_lecture", return_value="fc-123")
    def test_travail_d_un_autre_404(self, lancer):
        travail = self.lancer().json()["travail"]
        autre = User.objects.create_user(username="autre", password="motdepasse123")
        self.client.credentials(HTTP_AUTHORIZATION="Token " + CleApi.creer_pour(autre))
        self.assertEqual(self.client.get(reverse("api_etat_voix", args=[travail])).status_code, 404)

    def test_jeton_falsifie_404(self):
        self.assertEqual(self.client.get(reverse("api_etat_voix", args=["faux:jeton"])).status_code, 404)


@override_settings(MEDIA_ROOT=DOSSIER_MEDIA_TEST)
class TesterMaVoixTests(TestCase):
    """« Tester ma voix » : 3 propositions, choix mémorisé, 3 tests par jour (Modal simulé)."""

    PROPOSITIONS = [{"debut": 0.0, "url": "https://x.modal.run/?jeton=a"},
                    {"debut": 25.0, "url": "https://x.modal.run/?jeton=b"},
                    {"debut": 49.0, "url": "https://x.modal.run/?jeton=c"}]

    def setUp(self):
        from . import models
        self.dossier = tempfile.mkdtemp()
        self.ancien_emplacement = models.stockage_prive.location
        models.stockage_prive.location = self.dossier
        self.user = User.objects.create_user(username="samba", password="motdepasse123")
        self.voix = VoixUtilisateur.objects.create(user=self.user, consentement_le=timezone.now())
        self.voix.extrait.save("voix.webm", SimpleUploadedFile("voix.webm", b"son"))
        self.client.force_login(self.user)

    def tearDown(self):
        from . import models
        models.stockage_prive.location = self.ancien_emplacement
        shutil.rmtree(self.dossier, ignore_errors=True)

    def tester(self):
        return self.client.post(reverse("ma_voix"), {"action": "tester"}, follow=True)

    @patch("youtube_uploader.views.lancer_essai", return_value="fc-essai")
    def test_essai_lance_puis_propositions(self, lancer):
        self.assertContains(self.tester(), "Test lancé")
        self.assertEqual(lancer.call_args.args[0], b"son")
        with patch("youtube_uploader.views.etat_lecture", return_value=None):
            self.assertEqual(self.client.get(reverse("essai_ma_voix")).json()["etat"], "en_cours")
        with patch("youtube_uploader.views.etat_lecture", return_value=self.PROPOSITIONS):
            reponse = self.client.get(reverse("essai_ma_voix")).json()
        self.assertEqual(reponse["etat"], "pret")
        self.assertEqual(len(reponse["propositions"]), 3)

    @patch("youtube_uploader.views.lancer_essai", return_value="fc-essai")
    def test_choisir_une_proposition(self, lancer):
        self.tester()
        with patch("youtube_uploader.views.etat_lecture", return_value=self.PROPOSITIONS):
            self.client.get(reverse("essai_ma_voix"))
        self.client.post(reverse("ma_voix"), {"action": "choisir", "debut": "25.0"})
        self.voix.refresh_from_db()
        self.assertEqual(self.voix.passage_debut, 25.0)

    def test_choix_inconnu_refuse(self):
        reponse = self.client.post(reverse("ma_voix"), {"action": "choisir", "debut": "12"}, follow=True)
        self.assertContains(reponse, "Proposition introuvable")
        self.voix.refresh_from_db()
        self.assertEqual(self.voix.passage_debut, 0)

    @patch("youtube_uploader.views.lancer_essai", return_value="fc-essai")
    def test_trois_tests_par_jour(self, lancer):
        for _ in range(3):
            self.tester()
        self.assertContains(self.tester(), "Réessaie demain")
        self.assertEqual(lancer.call_count, 3)

    @patch("youtube_uploader.views.lancer_essai", return_value="fc-essai")
    def test_reenregistrer_remet_le_passage_a_zero(self, lancer):
        self.voix.passage_debut = 25.0
        self.voix.save()
        self.client.post(reverse("ma_voix"), {"action": "enregistrer", "consentement": "on",
                                              "extrait": SimpleUploadedFile("v.webm", b"nouveau")})
        self.voix.refresh_from_db()
        self.assertEqual(self.voix.passage_debut, 0)

    @patch("youtube_uploader.views.lancer_essai", side_effect=RuntimeError("modal en panne"))
    def test_service_indisponible_sans_decompte(self, lancer):
        with self.assertLogs("youtube_uploader.views", level="ERROR"):
            self.assertContains(self.tester(), "indisponible")
        self.voix.refresh_from_db()
        self.assertEqual(self.voix.essais_du_jour, 0)


@override_settings(MEDIA_ROOT=DOSSIER_MEDIA_TEST)
class PreparerEnvoiTests(TestCase):
    """Partie 23 : adresse de dépôt à usage unique, sans clé d'API."""

    def setUp(self):
        self.user = User.objects.create_user(username="samba", password="motdepasse123")
        YouTubeCredentials.objects.create(user=self.user, token_json="{}")
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION="Token " + CleApi.creer_pour(self.user))

    def preparer(self, **autres):
        donnees = {"titre": "Les ensembles", "pour_enfants": False, "contenu_ia": True}
        donnees.update(autres)
        return self.api.post(reverse("api_preparer_envoi"), donnees, format="json")

    def deposer(self, adresse, nom="video.mp4"):
        return Client().post(adresse, {"fichier": faux_fichier(nom)})

    def test_preparer_puis_deposer(self):
        reponse = self.preparer()
        self.assertEqual(reponse.status_code, 201)
        video = Video.objects.get(id=reponse.json()["id"])
        self.assertEqual(video.etat, "attente_fichier")
        self.assertIn("curl -F", reponse.json()["commande"])
        depot = self.deposer(reponse.json()["adresse_depot"])
        self.assertEqual(depot.status_code, 202)
        video.refresh_from_db()
        self.assertEqual(video.etat, "en_attente")      # le worker va l'envoyer
        self.assertTrue(video.fichier)
        self.assertTrue(video.contenu_ia)

    def test_adresse_utilisable_une_seule_fois(self):
        adresse = self.preparer().json()["adresse_depot"]
        self.assertEqual(self.deposer(adresse).status_code, 202)
        self.assertEqual(self.deposer(adresse).status_code, 409)

    def test_adresse_falsifiee(self):
        self.assertEqual(Client().post("/youtube/depot/faux:jeton/", {"fichier": faux_fichier()}).status_code, 404)

    def test_adresse_expiree(self):
        adresse = self.preparer().json()["adresse_depot"]
        with patch("youtube_uploader.depot.VALIDITE_DEPOT", -1):
            self.assertEqual(self.deposer(adresse).status_code, 404)

    def test_format_refuse_au_depot(self):
        adresse = self.preparer().json()["adresse_depot"]
        self.assertEqual(self.deposer(adresse, "image.png").status_code, 400)
        self.assertEqual(Video.objects.get().etat, "attente_fichier")   # l'adresse reste utilisable

    def test_pour_enfants_obligatoire(self):
        reponse = self.api.post(reverse("api_preparer_envoi"), {"titre": "x"}, format="json")
        self.assertEqual(reponse.status_code, 400)
        self.assertFalse(Video.objects.exists())

    def test_sans_cle_refuse(self):
        self.assertEqual(APIClient().post(reverse("api_preparer_envoi"), {}, format="json").status_code, 401)

    def test_limite_par_jour(self):
        for i in range(LIMITE_ENVOIS_PAR_JOUR):
            self.assertEqual(self.preparer(titre=f"Vidéo {i}").status_code, 201)
        self.assertEqual(self.preparer().status_code, 429)

    def test_le_worker_ignore_les_videos_sans_fichier(self):
        self.preparer()
        self.assertIsNone(prendre_prochaine_video())



@override_settings(MEDIA_ROOT=DOSSIER_MEDIA_TEST)
class VisibiliteEtChaineTests(TestCase):
    """A1 : la visibilité choisie est transmise à YouTube ; A2 : le nom de la chaîne est enregistré après l'envoi."""

    def setUp(self):
        self.user = User.objects.create_user(username="samba", password="motdepasse123")
        YouTubeCredentials.objects.create(user=self.user, token_json="{}")

    @patch("youtube_uploader.envois.upload_video",
           return_value={"id": "abc", "snippet": {"channelTitle": "BATCH CODE AI", "channelId": "UC1"}})
    def test_visibilite_transmise_et_chaine_enregistree(self, upload):
        Video.objects.create(user=self.user, titre="T", pour_enfants=False, visibilite="unlisted", fichier=faux_fichier())
        call_command("traiter_envois", "--une-fois")
        self.assertEqual(upload.call_args.args[3], "unlisted")
        self.assertEqual(YouTubeCredentials.objects.get(user=self.user).chaine_titre, "BATCH CODE AI")

    def test_visibilite_privee_par_defaut(self):
        video = Video.objects.create(user=self.user, titre="T", pour_enfants=False, fichier="videos/x.mp4")
        self.assertEqual(video.visibilite, "private")

    def test_visibilite_inconnue_refusee_par_l_api(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Token " + CleApi.creer_pour(self.user))
        reponse = client.post(reverse("api_preparer_envoi"),
                              {"titre": "T", "pour_enfants": False, "visibilite": "amis"}, format="json")
        self.assertEqual(reponse.status_code, 400)

    def test_mon_compte(self):
        YouTubeCredentials.objects.filter(user=self.user).update(chaine_titre="BATCH CODE AI")
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Token " + CleApi.creer_pour(self.user))
        donnees = client.get(reverse("api_mon_compte")).json()
        self.assertEqual(donnees["chaine_youtube"]["nom"], "BATCH CODE AI")
        self.assertEqual(donnees["envois_restants_aujourd_hui"], LIMITE_ENVOIS_PAR_JOUR)
        self.assertFalse(donnees["voix"]["enregistree"])

    def test_mon_compte_sans_cle_refuse(self):
        self.assertEqual(APIClient().get(reverse("api_mon_compte")).status_code, 401)


@override_settings(MEDIA_ROOT=DOSSIER_MEDIA_TEST)
class TachesAutomatiquesTests(TestCase):
    """C6 abandon, A3 règle des 30 jours, A4 révocation, D2 sauvegarde, C8 courriels, C7 doublons."""

    def setUp(self):
        self.user = User.objects.create_user(username="samba", password="motdepasse123", email="samba@exemple.com")
        YouTubeCredentials.objects.create(user=self.user, token_json="{}", chaine_titre="BATCH CODE AI",
                                          chaine_maj_le=timezone.now())

    def test_envoi_abandonne_supprime_apres_1_heure(self):
        from .envois import nettoyer_envois_abandonnes
        video = Video.objects.create(user=self.user, titre="T", pour_enfants=False, etat="attente_fichier", fichier="")
        Video.objects.filter(id=video.id).update(created_at=timezone.now() - timedelta(hours=2))
        self.assertEqual(nettoyer_envois_abandonnes(), 1)
        self.assertFalse(Video.objects.exists())

    def test_regle_des_30_jours(self):
        from .envois import appliquer_regle_30_jours
        video = Video.objects.create(user=self.user, titre="T", pour_enfants=False, etat="reussi", fichier="",
                                     youtube_id="abc", envoye_le=timezone.now() - timedelta(days=31))
        YouTubeCredentials.objects.filter(user=self.user).update(chaine_maj_le=timezone.now() - timedelta(days=31))
        appliquer_regle_30_jours()
        video.refresh_from_db()
        self.assertEqual(video.youtube_id, "")
        self.assertEqual(YouTubeCredentials.objects.get(user=self.user).chaine_titre, "")

    def test_revocation_chez_google_efface_les_donnees(self):
        from google.auth.exceptions import RefreshError
        from django.core import mail
        Video.objects.create(user=self.user, titre="Ancienne", pour_enfants=False, etat="reussi", fichier="", youtube_id="xyz")
        Video.objects.create(user=self.user, titre="T", pour_enfants=False, fichier=faux_fichier())
        with patch("youtube_uploader.envois.upload_video", side_effect=RefreshError("invalid_grant")):
            call_command("traiter_envois", "--une-fois")
        self.assertFalse(YouTubeCredentials.objects.filter(user=self.user).exists())
        self.assertFalse(Video.objects.exclude(youtube_id="").exists())
        self.assertIn("Reconnecte", mail.outbox[0].subject)

    @patch("youtube_uploader.envois.upload_video", return_value={"id": "abc", "snippet": {}})
    def test_courriel_video_en_ligne(self, upload):
        from django.core import mail
        Video.objects.create(user=self.user, titre="Les ensembles", pour_enfants=False, fichier=faux_fichier())
        call_command("traiter_envois", "--une-fois")
        self.assertIn("Les ensembles", mail.outbox[0].subject)
        self.assertIn("https://youtu.be/abc", mail.outbox[0].body)

    def test_sauvegarde_quotidienne(self):
        from .envois import sauvegarder_base
        dossier = tempfile.mkdtemp()
        try:
            premiere = sauvegarder_base(dossier)
            self.assertTrue(premiere.exists())
            self.assertIsNone(sauvegarder_base(dossier))   # moins de 24 h : pas de 2e copie
        finally:
            shutil.rmtree(dossier, ignore_errors=True)

    def test_pas_de_doublon_preparer_envoi(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Token " + CleApi.creer_pour(self.user))
        donnees = {"titre": "Les ensembles", "pour_enfants": False}
        premiere = client.post(reverse("api_preparer_envoi"), donnees, format="json").json()
        deuxieme = client.post(reverse("api_preparer_envoi"), donnees, format="json").json()
        self.assertEqual(premiere["id"], deuxieme["id"])        # même envoi, nouvelle adresse
        self.assertEqual(Video.objects.count(), 1)
        Video.objects.filter(id=premiere["id"]).update(etat="en_attente")
        self.assertEqual(client.post(reverse("api_preparer_envoi"), donnees, format="json").status_code, 409)


class PagesCompteTests(TestCase):
    """C1 préférences, C5 Mes vidéos, C4 quota par utilisateur."""

    def setUp(self):
        self.user = User.objects.create_user(username="samba", password="motdepasse123")
        self.client.force_login(self.user)

    def test_preferences_enregistrees_et_donnees_a_claude(self):
        from .models import PreferencesPublication
        self.client.post(reverse("mes_preferences"), {"pour_enfants": "non", "contenu_ia": "oui", "visibilite": "unlisted"})
        prefs = PreferencesPublication.objects.get(user=self.user)
        self.assertEqual((prefs.pour_enfants, prefs.contenu_ia, prefs.visibilite), (False, True, "unlisted"))
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION="Token " + CleApi.creer_pour(self.user))
        self.assertEqual(api.get(reverse("api_mon_compte")).json()["preferences_publication"]["visibilite"], "unlisted")

    def test_preferences_me_demander(self):
        from .models import PreferencesPublication
        self.client.post(reverse("mes_preferences"), {"pour_enfants": "", "contenu_ia": "", "visibilite": ""})
        prefs = PreferencesPublication.objects.get(user=self.user)
        self.assertIsNone(prefs.pour_enfants)

    def test_mes_videos_seulement_les_miennes(self):
        autre = User.objects.create_user(username="autre", password="motdepasse123")
        Video.objects.create(user=autre, titre="Pas à moi", pour_enfants=False, fichier="")
        Video.objects.create(user=self.user, titre="À moi", pour_enfants=False, fichier="", etat="reussi", youtube_id="abc")
        reponse = self.client.get(reverse("mes_videos_site"))
        self.assertContains(reponse, "À moi")
        self.assertContains(reponse, "https://youtu.be/abc")
        self.assertNotContains(reponse, "Pas à moi")

    def test_quota_propre_a_l_utilisateur(self):
        from .voix import quota_restant
        voix = VoixUtilisateur.objects.create(user=self.user, quota_secondes=3600)
        self.assertEqual(quota_restant(voix), 3600)

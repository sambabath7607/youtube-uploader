"""Lot 6 — tests de bout en bout (B1, B3 et B5 simulés, B4 côté service).

Le parcours entier passe par les vraies pages, la vraie API et le vrai connecteur MCP (mcp_server.py) ; seuls Modal,
Google/YouTube et le site vitrine sont simulés : aucun appel réel, aucune dépense.
  1. inscription → clé d'API → chaîne connectée → voix → fabriquer_video (connecteur) → Modal simulé → worker
     → envoi YouTube simulé → courriel « ta vidéo est sur YouTube » → etat_video donne le lien ;
  2. pont de paiement signé → offre Pro → limites Pro → annulation → retour aux limites Gratuit ;
  3. erreurs : chaîne déconnectée, Modal en panne, quota de voix atteint → message clair, rien de relancé.
"""
import json
import re
import shutil
import tempfile
import time
import uuid
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.pont import signature

from .models import EtatExploitation, Video, VoixUtilisateur, YouTubeCredentials
from .tests_fabrication import SCENES, SCRIPT
from .tests_mcp import charger_connecteur

SECRET_PONT = "secret-de-test-du-pont"
DOSSIER_MEDIA = tempfile.mkdtemp()


class ReponseApi:
    """Réponse du site vue par le connecteur (comme requests.Response : status_code et json())."""

    def __init__(self, reponse):
        self.status_code = reponse.status_code
        self.contenu = reponse.content

    def json(self):
        return json.loads(self.contenu)


@override_settings(MEDIA_ROOT=DOSSIER_MEDIA, PONT_SECRET=SECRET_PONT, ADMINS=[("Samba", "alertes@exemple.com")])
class BaseBoutEnBout(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.connecteur = charger_connecteur()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER_MEDIA, ignore_errors=True)

    def setUp(self):
        from . import models
        self.dossier_prive = tempfile.mkdtemp()
        self.ancien = models.stockage_prive.location
        models.stockage_prive.location = self.dossier_prive
        self.api = APIClient()
        # Le connecteur appelle l'API du site : ses requêtes HTTP sont dirigées vers le site de test
        for nom, fonction in (("get", self.faux_get), ("post", self.faux_post)):
            remplacement = patch.object(self.connecteur.requests, nom, side_effect=fonction)
            remplacement.start()
            self.addCleanup(remplacement.stop)

        async def run_sync(fonction, *args):   # même fil : la base de test reste visible
            return fonction(*args)
        remplacement = patch.object(self.connecteur.anyio.to_thread, "run_sync", run_sync)
        remplacement.start()
        self.addCleanup(remplacement.stop)

    def tearDown(self):
        from . import models
        models.stockage_prive.location = self.ancien
        shutil.rmtree(self.dossier_prive, ignore_errors=True)

    # ---------- le connecteur MCP, branché sur le site de test ----------

    def faux_get(self, url, headers=None, params=None, timeout=None):
        return ReponseApi(self.api.get(urlparse(url).path, params or {}, HTTP_AUTHORIZATION=headers["Authorization"]))

    def faux_post(self, url, headers=None, json=None, data=None, files=None, timeout=None):
        return ReponseApi(self.api.post(urlparse(url).path, json, format="json",
                                        HTTP_AUTHORIZATION=headers["Authorization"]))

    def outil(self, nom, **arguments):
        jeton = self.connecteur.cle_courante.set("Token " + self.cle)
        try:
            # En vrai, le connecteur et le site sont deux programmes. Ici l'outil est déroulé sans boucle
            # asynchrone (il n'attend que run_sync, remplacé) : le site de test répond avec la même connexion à la base
            outil = getattr(self.connecteur, nom)(**arguments)
            try:
                outil.send(None)
            except StopIteration as fin:
                return fin.value
            raise AssertionError(f"L'outil {nom} attend autre chose que l'API du site")
        finally:
            self.connecteur.cle_courante.reset(jeton)

    # ---------- étapes faites par le client sur le site ----------

    def s_inscrire(self, nom="ana", courriel="ana@exemple.com"):
        reponse = self.client.post(reverse("inscription"), {
            "username": nom, "email": courriel, "password1": "Un-mot-de-passe-solide-42",
            "password2": "Un-mot-de-passe-solide-42", "age_minimum": "on", "accepte_conditions": "on"})
        self.assertRedirects(reponse, reverse("accueil"), fetch_redirect_response=False)
        self.user = User.objects.get(username=nom)
        # « Mes clés » : la clé n'est montrée qu'une fois, à sa création
        self.cle = self.client.post(reverse("ma_cle"), {"nom": "claude.ai"}).context["nouvelle_cle"]
        return self.user

    def connecter_chaine(self):
        # Retour de Google simulé : le jeton (chiffré en vrai) est rangé en base
        YouTubeCredentials.objects.create(user=self.user, token_json="{}")

    def enregistrer_voix(self):
        voix = VoixUtilisateur.objects.create(user=self.user, mode="en_ligne", consentement_le=timezone.now(),
                                              voix_validee=True)
        voix.extrait.save("voix.webm", SimpleUploadedFile("voix.webm", b"son"))
        return voix

    def fabriquer(self, script=SCRIPT, scenes=None, titre="Les listes en Python"):
        return self.outil("fabriquer_video", modele="lecon", script=script, scenes=scenes or SCENES, titre=titre,
                          pour_enfants=False, contenu_ia=True)

    def pont(self, **donnees):
        valeurs = {"evenement": str(uuid.uuid4()), "email": self.user.email, "offre": "pro", "statut": "active",
                   "reference": "sub_1", "fin_periode": (timezone.now() + timedelta(days=30)).isoformat(),
                   "etat_le": timezone.now().isoformat()}
        valeurs.update(donnees)
        corps = json.dumps(valeurs).encode()
        horodatage = str(int(time.time()))
        return self.client.post(reverse("pont_abonnements"), corps, content_type="application/json",
                                HTTP_X_PONT_HORODATAGE=horodatage,
                                HTTP_X_PONT_SIGNATURE=signature(SECRET_PONT, horodatage, corps))


def video_prete_chez_modal(nom, chemin):
    with open(chemin, "wb") as fichier:
        fichier.write(b"\x00\x00\x00\x18ftypmp42" + b"0" * 1024)


class ParcoursCompletTests(BaseBoutEnBout):
    """B1 / B3 simulé : de l'inscription au lien youtu.be, sans rien sur l'ordinateur du client."""

    @patch("youtube_uploader.envois.upload_video",
           return_value={"id": "yt-abc123", "snippet": {"channelTitle": "Chaîne d'Ana", "channelId": "UC1"}})
    @patch("youtube_uploader.fabrication.effacer_chez_modal")
    @patch("youtube_uploader.fabrication.telecharger_video", side_effect=video_prete_chez_modal)
    @patch("youtube_uploader.fabrication.lire_progression", return_value={"etape": "rendu", "fait": 3, "total": 5})
    @patch("youtube_uploader.fabrication.resultat_fabrication", return_value=None)
    @patch("youtube_uploader.api.lancer_fabrication", return_value="fc-ana-1")
    def test_inscription_jusqu_au_lien_youtube_et_au_courriel(self, lancer, resultat, progression, telecharger,
                                                              effacer, upload):
        self.s_inscrire()
        self.connecter_chaine()
        voix = self.enregistrer_voix()

        compte = self.outil("mon_compte")                        # l'agent lit le compte avant de fabriquer
        self.assertTrue(compte["chaine_youtube"]["connectee"])
        self.assertEqual(compte["offre"]["offre"], "gratuit")
        self.assertEqual(compte["envois_restants_aujourd_hui"], settings.OFFRES["gratuit"]["envois_par_jour"])

        reponse = self.fabriquer()
        self.assertEqual(reponse["etat"], "fabrication", reponse)
        video_id = reponse["id"]
        envoye = lancer.call_args.args[0]                        # ce qui part chez Modal
        self.assertEqual((envoye["modele"], envoye["titre"]), ("lecon", "Les listes en Python"))
        self.assertEqual(envoye["voix"]["reference"], b"son")    # la voix part chez Modal, jamais gardée ailleurs
        voix.refresh_from_db()
        self.assertGreater(voix.secondes_utilisees, 0)

        # Le worker suit la fabrication : l'agent voit l'étape
        call_command("traiter_envois", "--une-fois")
        self.assertEqual(self.outil("etat_video", video_id=video_id)["etape"], "Rendu 3/5")

        # Modal a fini : le worker récupère la vidéo, l'efface chez Modal, l'envoie sur YouTube, prévient le client
        resultat.return_value = {"fichier": "video-ana.mp4", "duree": 18.4, "mesures": {"rendu": 12.0}}
        with self.assertLogs("youtube_uploader.fabrication", level="WARNING"):
            call_command("traiter_envois", "--une-fois")
        etat = self.outil("etat_video", video_id=video_id)
        self.assertEqual((etat["etat"], etat["youtube_id"]), ("reussi", "yt-abc123"))
        effacer.assert_called_once_with("video-ana.mp4")
        video = Video.objects.get(id=video_id)
        self.assertFalse(video.fichier)                          # effacée du serveur après l'envoi
        self.assertTrue(upload.call_args.kwargs["contenu_ia"])   # voix clonée = contenu IA déclaré à YouTube
        self.assertEqual(upload.call_args.kwargs["user"], self.user)

        courriels = [m for m in mail.outbox if m.to == ["ana@exemple.com"]]
        self.assertEqual(len(courriels), 1)
        self.assertIn("https://youtu.be/yt-abc123", courriels[0].body)
        self.assertEqual(YouTubeCredentials.objects.get(user=self.user).chaine_titre, "Chaîne d'Ana")

        # Le compteur du jour et la page de santé suivent
        compte = self.outil("mon_compte")
        self.assertEqual(compte["envois_restants_aujourd_hui"], settings.OFFRES["gratuit"]["envois_par_jour"] - 1)
        self.assertTrue(EtatExploitation.objects.filter(nom="worker").exists())
        self.assertEqual(self.client.get(reverse("sante")).json()["worker"], "ok")

    def test_un_autre_client_ne_voit_pas_la_video(self):
        with patch("youtube_uploader.api.lancer_fabrication", return_value="fc-1"):
            self.s_inscrire()
            self.connecter_chaine()
            self.enregistrer_voix()
            video_id = self.fabriquer()["id"]
        self.client.logout()
        self.s_inscrire("bob", "bob@exemple.com")
        self.assertEqual(self.outil("etat_video", video_id=video_id)["code"], "video_introuvable")


@patch("youtube_uploader.api.lancer_fabrication", return_value="fc-1")
class PaiementEtLimitesTests(BaseBoutEnBout):
    """B4 côté service : paiement sur le site vitrine (pont signé) → Pro tout de suite → annulation → Gratuit."""

    def script_de(self, minutes):
        """Script d'environ N minutes (débit de la voix : 2,5 mots par seconde), en 4 paragraphes."""
        mots = int(minutes * 60 * 2.5 / 4)
        return "\n\n".join(" ".join(["mot"] * mots) + "." for _ in range(4))

    def test_pont_pro_limites_puis_annulation(self, lancer):
        self.s_inscrire()
        self.connecter_chaine()
        script = self.script_de(2)                               # 2 min : plus que la limite Gratuit par vidéo

        refus = self.outil("fabriquer_video", modele="lecon", script=script, scenes=SCENES, titre="Long",
                           pour_enfants=False, contenu_ia=False, avec_ma_voix=False)
        self.assertEqual(refus["code"], "duree_max_atteinte")
        lancer.assert_not_called()

        reponse = self.pont()                                    # paiement accepté sur le site vitrine
        self.assertEqual(reponse.json()["resultat"], "pro_active")
        compte = self.outil("mon_compte")
        self.assertEqual(compte["offre"]["offre"], "pro")
        self.assertEqual(compte["envois_restants_aujourd_hui"], settings.OFFRES["pro"]["envois_par_jour"])

        accepte = self.outil("fabriquer_video", modele="lecon", script=script, scenes=SCENES, titre="Long",
                             pour_enfants=False, contenu_ia=False, avec_ma_voix=False)
        self.assertEqual(accepte["etat"], "fabrication", accepte)

        # Les guides affichent les vraies limites du compte (pas de chiffres écrits en dur)
        guide = self.client.get(reverse("guide_claude")).content.decode()
        self.assertIn(f"{settings.OFFRES['pro']['envois_par_jour']} envois par jour", guide)

        self.pont(offre="gratuit", statut="canceled", fin_periode=None)   # annulation
        self.assertEqual(self.outil("mon_compte")["offre"]["offre"], "gratuit")
        Video.objects.filter(user=self.user).update(etat="reussi")
        refus = self.outil("fabriquer_video", modele="lecon", script=script, scenes=SCENES, titre="Long 2",
                           pour_enfants=False, contenu_ia=False, avec_ma_voix=False)
        self.assertEqual(refus["code"], "duree_max_atteinte")

    def test_paiement_avant_inscription_compte_cree(self, lancer):
        self.user = User(email="nouveau@exemple.com")
        with self.captureOnCommitCallbacks(execute=True):
            reponse = self.pont()
        self.assertEqual(reponse.json(), {"resultat": "pro_active", "compte_cree": True})
        courriels = [m for m in mail.outbox if m.to == ["nouveau@exemple.com"]]
        self.assertEqual(len(courriels), 1)                      # « Choisis ton mot de passe »
        lien = re.search(r"https?://\S+/nouveau-mot-de-passe/\S+/", courriels[0].body).group(0)
        self.assertEqual(self.client.get(lien, follow=True).status_code, 200)
        self.assertEqual(User.objects.get(email="nouveau@exemple.com").abonnement.offre, "pro")


class ErreursTests(BaseBoutEnBout):
    """B5 simulé : chaque panne donne un message clair à l'agent, rien n'est relancé, le quota est rendu."""

    def test_chaine_deconnectee(self):
        self.s_inscrire()
        self.enregistrer_voix()
        with patch("youtube_uploader.api.lancer_fabrication") as lancer:
            reponse = self.fabriquer()
        self.assertEqual(reponse["code"], "youtube_non_connecte")
        lancer.assert_not_called()

    def test_modal_en_panne(self):
        self.s_inscrire()
        self.connecter_chaine()
        voix = self.enregistrer_voix()
        with patch("youtube_uploader.api.lancer_fabrication", side_effect=ConnectionError("Modal en panne")):
            reponse = self.fabriquer()
        self.assertEqual(reponse["code"], "service_video_indisponible")
        voix.refresh_from_db()
        self.assertEqual(voix.secondes_utilisees, 0)             # rien n'est décompté
        self.assertFalse(Video.objects.exists())                 # ne compte pas dans la limite du jour
        self.assertTrue(any(m.to == ["alertes@exemple.com"] for m in mail.outbox))   # Samba est prévenu

    def test_quota_de_voix_atteint(self):
        self.s_inscrire()
        self.connecter_chaine()
        voix = self.enregistrer_voix()
        voix.mois_du_compteur = timezone.localdate().replace(day=1)
        voix.secondes_utilisees = settings.OFFRES["gratuit"]["minutes_voix_par_mois"] * 60
        voix.save()
        with patch("youtube_uploader.api.lancer_fabrication") as lancer:
            reponse = self.fabriquer()
        self.assertEqual(reponse["code"], "quota_voix_atteint")
        lancer.assert_not_called()

    @patch("youtube_uploader.fabrication.resultat_fabrication", side_effect=RuntimeError("Remotion a planté"))
    def test_echec_de_fabrication_quota_rendu_sans_relance(self, resultat):
        self.s_inscrire()
        self.connecter_chaine()
        voix = self.enregistrer_voix()
        with patch("youtube_uploader.api.lancer_fabrication", return_value="fc-1") as lancer:
            video_id = self.fabriquer()["id"]
        with self.assertLogs("youtube_uploader.fabrication", level="ERROR"):
            call_command("traiter_envois", "--une-fois")
        etat = self.outil("etat_video", video_id=video_id)
        self.assertEqual(etat["etat"], "fabrication_echouee")
        self.assertNotIn("Remotion", etat["erreur"])             # aucun détail interne pour le client
        voix.refresh_from_db()
        self.assertEqual(voix.secondes_utilisees, 0)
        call_command("traiter_envois", "--une-fois")
        self.assertEqual(lancer.call_count, 1)                   # jamais relancée automatiquement

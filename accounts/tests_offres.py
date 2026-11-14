"""Lot 4 : offres Gratuit / Pro, pont signé du site vitrine, page Tarifs, « Mon compte », coûts par client."""
import json
import re
import time
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from youtube_uploader.envois import probleme_avant_envoi
from youtube_uploader.models import Video, VoixUtilisateur, YouTubeCredentials
from youtube_uploader.voix import quota_restant
from .models import Abonnement, CleApi, EvenementPont
from .offres import limites, probleme_fabrication, quota_voix_secondes
from .pont import signature

SECRET = "secret-de-test-du-pont"
ADRESSE = "/youtube/api/v1/interne/abonnements/"


def rendre_pro(user, fin=None):
    return Abonnement.objects.create(user=user, email=user.email, offre="pro", actif=True,
                                     fin_periode=fin or timezone.now() + timedelta(days=30), etat_le=timezone.now())


class LimitesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ana", "ana@exemple.com", "x")

    def test_sans_abonnement_offre_gratuite(self):
        offre = limites(self.user)
        self.assertEqual(offre.offre, "gratuit")
        self.assertEqual(offre.envois_par_jour, settings.OFFRES["gratuit"]["envois_par_jour"])

    def test_abonnement_actif_offre_pro(self):
        rendre_pro(self.user)
        offre = limites(self.user)
        self.assertTrue(offre.est_pro)
        self.assertEqual(offre.secondes_voix_par_mois, settings.OFFRES["pro"]["minutes_voix_par_mois"] * 60)

    def test_pro_inactif_ou_periode_depassee_repasse_gratuit(self):
        abonnement = rendre_pro(self.user, fin=timezone.now() - timedelta(days=4))   # au-delà des 3 jours de grâce
        self.assertEqual(limites(self.user).offre, "gratuit")
        abonnement.fin_periode = timezone.now() - timedelta(days=1)                  # dans le délai de grâce
        abonnement.save()
        self.assertEqual(limites(self.user).offre, "pro")
        abonnement.actif = False
        abonnement.save()
        self.assertEqual(limites(self.user).offre, "gratuit")

    @override_settings(OFFRES={**settings.OFFRES, "gratuit": {**settings.OFFRES["gratuit"], "envois_par_jour": 1}})
    def test_envois_par_jour_selon_l_offre(self):
        YouTubeCredentials.objects.create(user=self.user, token_json="{}")
        Video.objects.create(user=self.user, titre="v1", pour_enfants=False, fichier="videos/a.mp4")
        self.assertEqual(probleme_avant_envoi(self.user)[1], "limite_envois_atteinte")
        rendre_pro(self.user)
        self.assertIsNone(probleme_avant_envoi(self.user))

    def test_minutes_de_voix_selon_l_offre(self):
        voix = VoixUtilisateur.objects.create(user=self.user)
        self.assertEqual(quota_restant(voix), settings.OFFRES["gratuit"]["minutes_voix_par_mois"] * 60)
        rendre_pro(self.user)
        self.assertEqual(quota_restant(voix), settings.OFFRES["pro"]["minutes_voix_par_mois"] * 60)

    def test_quota_de_voix_regle_a_la_main_l_emporte(self):
        voix = VoixUtilisateur.objects.create(user=self.user, quota_secondes=500 * 60)
        self.assertEqual(quota_voix_secondes(voix), 500 * 60)
        rendre_pro(self.user)
        voix.quota_secondes = 30
        self.assertEqual(quota_voix_secondes(voix), 30)

    def test_fabrication_limitee_par_l_offre(self):
        maximum = settings.OFFRES["gratuit"]["minutes_max_par_video"] * 60
        self.assertIsNone(probleme_fabrication(self.user, maximum))
        self.assertEqual(probleme_fabrication(self.user, maximum + 1)[1], "duree_max_atteinte")
        rendre_pro(self.user)
        self.assertIsNone(probleme_fabrication(self.user, maximum + 1))


@override_settings(PONT_SECRET=SECRET)
class PontTests(TestCase):
    def appeler(self, horodatage=None, secret=SECRET, corps=None, **donnees):
        valeurs = {"evenement": str(uuid.uuid4()), "email": "ana@exemple.com", "offre": "pro", "statut": "active",
                   "reference": "sub_1", "fin_periode": (timezone.now() + timedelta(days=30)).isoformat(),
                   "etat_le": timezone.now().isoformat()}
        valeurs.update(donnees)
        corps = corps if corps is not None else json.dumps(valeurs).encode()
        horodatage = str(horodatage or int(time.time()))
        return self.client.post(ADRESSE, corps, content_type="application/json",
                                HTTP_X_PONT_HORODATAGE=horodatage,
                                HTTP_X_PONT_SIGNATURE=signature(secret, horodatage, corps))

    def setUp(self):
        self.user = User.objects.create_user("ana", "Ana@Exemple.com", "x")

    def test_compte_connu_passe_pro(self):
        reponse = self.appeler()
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json(), {"resultat": "pro_active", "compte_cree": False})
        self.assertEqual(limites(self.user).offre, "pro")

    def test_signature_fausse_refusee(self):
        reponse = self.appeler(secret="mauvais-secret")
        self.assertEqual(reponse.status_code, 401)
        self.assertEqual(reponse.json()["code"], "signature_invalide")
        self.assertFalse(Abonnement.objects.exists())

    def test_signature_absente_refusee(self):
        reponse = self.client.post(ADRESSE, b"{}", content_type="application/json")
        self.assertEqual(reponse.json()["code"], "signature_absente")

    def test_appel_trop_vieux_refuse(self):
        reponse = self.appeler(horodatage=int(time.time()) - 6 * 60)
        self.assertEqual(reponse.status_code, 401)
        self.assertEqual(reponse.json()["code"], "appel_expire")

    @override_settings(PONT_SECRET="")
    def test_pont_sans_secret_ferme(self):
        self.assertEqual(self.appeler(secret="").status_code, 503)

    def test_meme_evenement_une_seule_fois(self):
        self.appeler(evenement="evt_1")
        reponse = self.appeler(evenement="evt_1", offre="gratuit")   # rejeu : ne doit rien changer
        self.assertEqual(reponse.json()["resultat"], "deja_traite")
        self.assertEqual(limites(self.user).offre, "pro")
        self.assertEqual(EvenementPont.objects.count(), 1)

    def test_annulation_repasse_gratuit(self):
        self.appeler()
        reponse = self.appeler(offre="gratuit", statut="canceled", fin_periode=None)
        self.assertEqual(reponse.json()["resultat"], "gratuit")
        self.assertEqual(limites(self.user).offre, "gratuit")

    def test_etat_plus_ancien_ignore(self):
        self.appeler()
        reponse = self.appeler(offre="gratuit", etat_le=(timezone.now() - timedelta(hours=1)).isoformat())
        self.assertEqual(reponse.json()["resultat"], "ancien_etat_ignore")
        self.assertEqual(limites(self.user).offre, "pro")

    def test_compte_retrouve_par_reference_si_courriel_change(self):
        self.appeler()
        self.appeler(email="nouvelle@exemple.com", offre="gratuit")
        self.assertEqual(limites(self.user).offre, "gratuit")
        self.assertEqual(User.objects.count(), 1)

    def test_courriel_inconnu_compte_cree_avec_lien_mot_de_passe(self):
        with self.captureOnCommitCallbacks(execute=True):
            reponse = self.appeler(email="bob@exemple.com", reference="sub_2")
        self.assertEqual(reponse.json(), {"resultat": "pro_active", "compte_cree": True})
        bob = User.objects.get(email="bob@exemple.com")
        self.assertEqual(limites(bob).offre, "pro")
        self.assertEqual(len(mail.outbox), 1)
        lien = re.search(r"https?://\S+/nouveau-mot-de-passe/\S+/", mail.outbox[0].body).group(0)
        page = self.client.get(lien, follow=True)
        self.assertContains(page, "password")   # formulaire « nouveau mot de passe » ouvert
        # « Mot de passe oublié » fonctionne aussi pour ce compte (mot de passe aléatoire, pas inutilisable)
        self.assertTrue(bob.has_usable_password())

    def test_courriel_inconnu_et_gratuit_ignore(self):
        reponse = self.appeler(email="inconnu@exemple.com", offre="gratuit")
        self.assertEqual(reponse.json()["resultat"], "ignore")
        self.assertFalse(User.objects.filter(email="inconnu@exemple.com").exists())

    def test_donnees_invalides(self):
        reponse = self.appeler(offre="platine")
        self.assertEqual(reponse.status_code, 400)
        self.assertEqual(reponse.json()["code"], "donnees_invalides")
        self.assertEqual(self.appeler(corps=b"pas du json").status_code, 400)

    def test_get_refuse(self):
        self.assertEqual(self.client.get(ADRESSE).status_code, 405)


class PagesOffresTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ana", "ana@exemple.com", "x")

    def test_page_tarifs_visiteur(self):
        page = self.client.get(reverse("tarifs"))
        self.assertContains(page, "Passer à Pro")
        self.assertContains(page, settings.URL_PAIEMENT_PRO)
        self.assertContains(page, "Commencer gratuitement")

    def test_page_tarifs_client_pro(self):
        rendre_pro(self.user)
        self.client.force_login(self.user)
        page = self.client.get(reverse("tarifs"))
        self.assertContains(page, "Gérer mon abonnement")
        self.assertNotContains(page, "Commencer gratuitement")

    def test_mon_compte_affiche_l_offre(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse("mon_compte"))
        self.assertContains(page, "Mon offre : Gratuit")
        self.assertContains(page, "Passer à Pro")
        rendre_pro(self.user)
        page = self.client.get(reverse("mon_compte"))
        self.assertContains(page, "Mon offre : Pro")
        self.assertContains(page, settings.URL_GERER_ABONNEMENT)

    def test_api_mon_compte_donne_l_offre(self):
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION="Token " + CleApi.creer_pour(self.user))
        donnees = api.get("/youtube/api/v1/compte/").json()
        self.assertEqual(donnees["offre"]["offre"], "gratuit")
        self.assertEqual(donnees["envois_restants_aujourd_hui"], settings.OFFRES["gratuit"]["envois_par_jour"])

    @override_settings(COUT_MODAL_MINUTE_VOIX=0.5)
    def test_tableau_des_couts_par_client(self):
        voix = VoixUtilisateur.objects.create(user=self.user, secondes_utilisees=120,
                                              mois_du_compteur=timezone.localdate().replace(day=1))
        self.assertTrue(voix.pk)
        admin = User.objects.create_superuser("chef", "chef@exemple.com", "x")
        self.client.force_login(admin)
        page = self.client.get(reverse("admin:accounts_coutclient_changelist"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "1.00")   # 2 min de voix × 0,50 $


class LimitesAfficheesTests(TestCase):
    """Les guides et la présentation affichent les limites réelles (settings.OFFRES), jamais des chiffres en dur."""

    REGLAGE = {
        "gratuit": dict(settings.OFFRES["gratuit"], envois_par_jour=2, minutes_voix_par_mois=3),
        "pro": dict(settings.OFFRES["pro"], envois_par_jour=7, minutes_voix_par_mois=45),
    }

    def test_visiteur_voit_l_offre_gratuite(self):
        with self.settings(OFFRES=self.REGLAGE):
            guide = self.client.get(reverse("guide_claude")).content.decode()
            api = self.client.get(reverse("guide_api")).content.decode()
            accueil = self.client.get(reverse("accueil")).content.decode()
        self.assertIn("2 envois par jour, 3 minutes de voix", guide)
        self.assertNotIn("5 envois par jour", guide)
        self.assertIn("2 envois par jour et par compte", api)
        self.assertIn("3 minutes offertes par mois", accueil)
        self.assertIn("45 avec l'offre Pro", accueil)

    def test_client_pro_voit_ses_limites(self):
        user = User.objects.create_user("ana", "ana@exemple.com", "x")
        rendre_pro(user)
        self.client.force_login(user)
        with self.settings(OFFRES=self.REGLAGE):
            guide = self.client.get(reverse("guide_claude")).content.decode()
        self.assertIn("Limites (offre Pro) : 7 envois par jour, 45 minutes de voix", guide)

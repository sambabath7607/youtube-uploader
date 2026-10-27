import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from youtube_uploader.models import Video, YouTubeCredentials
from .models import CleApi, empreinte


class MaCleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="test", password="motdepasse123")

    def test_visiteur_non_connecte_renvoye_vers_connexion(self):
        reponse = self.client.get(reverse("ma_cle"))
        self.assertEqual(reponse.status_code, 302)
        self.assertIn(reverse("login"), reponse.url)

    def test_cle_existante_jamais_affichee_en_entier(self):
        cle = CleApi.creer_pour(self.user)
        self.client.login(username="test", password="motdepasse123")
        reponse = self.client.get(reverse("ma_cle"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, cle[:8])
        self.assertNotContains(reponse, cle)

    def test_nouvelle_cle_affichee_une_seule_fois(self):
        self.client.login(username="test", password="motdepasse123")
        reponse = self.client.post(reverse("ma_cle"))
        cle = reponse.context["nouvelle_cle"]
        self.assertContains(reponse, cle)
        self.assertNotContains(self.client.get(reverse("ma_cle")), cle)

    def test_nouvelle_cle_remplace_l_ancienne(self):
        self.client.login(username="test", password="motdepasse123")
        ancienne = CleApi.creer_pour(self.user)
        self.client.post(reverse("ma_cle"))
        self.assertEqual(CleApi.objects.filter(user=self.user).count(), 1)
        self.assertFalse(CleApi.objects.filter(empreinte=empreinte(ancienne)).exists())

    def test_la_base_ne_contient_jamais_la_cle(self):
        cle = CleApi.creer_pour(self.user)
        ligne = CleApi.objects.get(user=self.user)
        self.assertNotIn(cle, [ligne.empreinte, ligne.debut])
        self.assertEqual(ligne.empreinte, empreinte(cle))


class InscriptionTests(TestCase):
    def donnees(self, **autres):
        valeurs = {"username": "nouveau", "password1": "UnMotDePasse!2026", "password2": "UnMotDePasse!2026",
                   "age_minimum": "on", "accepte_conditions": "on"}
        valeurs.update(autres)
        return {cle: valeur for cle, valeur in valeurs.items() if valeur is not None}

    def test_inscription_avec_les_deux_cases(self):
        self.client.post(reverse("inscription"), self.donnees())
        self.assertTrue(User.objects.filter(username="nouveau").exists())

    def test_inscription_mene_a_l_accueil_connecte(self):
        reponse = self.client.post(reverse("inscription"), self.donnees(), follow=True)
        self.assertRedirects(reponse, reverse("accueil"))
        self.assertTrue(reponse.context["user"].is_authenticated)
        self.assertContains(reponse, "Bienvenue")

    def test_inscription_refusee_sans_accepter_les_conditions(self):
        self.client.post(reverse("inscription"), self.donnees(accepte_conditions=None))
        self.assertFalse(User.objects.filter(username="nouveau").exists())

    def test_inscription_refusee_sans_age_minimum(self):
        self.client.post(reverse("inscription"), self.donnees(age_minimum=None))
        self.assertFalse(User.objects.filter(username="nouveau").exists())


class DonneesEtSuppressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="samba", password="motdepasse123")
        YouTubeCredentials.objects.create(user=self.user, token_json=json.dumps({"refresh_token": "secret"}))
        self.cle = CleApi.creer_pour(self.user)
        Video.objects.create(user=self.user, titre="Ma vidéo", pour_enfants=False, fichier="")
        self.client.login(username="samba", password="motdepasse123")

    def test_export_sans_aucun_secret(self):
        reponse = self.client.get(reverse("mes_donnees"))
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("attachment", reponse["Content-Disposition"])
        donnees = json.loads(reponse.content)
        self.assertEqual(donnees["videos"][0]["titre"], "Ma vidéo")
        self.assertTrue(donnees["chaine_youtube_connectee"])
        self.assertNotIn(b"secret", reponse.content)
        self.assertNotIn(self.cle.encode(), reponse.content)

    @patch("accounts.views.revoquer_token_google")
    def test_suppression_avec_mauvais_mot_de_passe(self, revoquer):
        self.client.post(reverse("supprimer_compte"), {"mot_de_passe": "faux"})
        self.assertTrue(User.objects.filter(username="samba").exists())
        revoquer.assert_not_called()

    @patch("accounts.views.revoquer_token_google")
    def test_suppression_efface_tout(self, revoquer):
        reponse = self.client.post(reverse("supprimer_compte"), {"mot_de_passe": "motdepasse123"})
        self.assertRedirects(reponse, reverse("login"))
        revoquer.assert_called_once()
        self.assertFalse(User.objects.filter(username="samba").exists())
        self.assertFalse(YouTubeCredentials.objects.exists())
        self.assertFalse(CleApi.objects.exists())
        self.assertFalse(Video.objects.exists())


class PagesPubliquesTests(TestCase):
    def test_pages_legales_accessibles_sans_compte(self):
        for nom in ["confidentialite", "conditions"]:
            reponse = self.client.get(reverse(nom))
            self.assertEqual(reponse.status_code, 200)
            self.assertContains(reponse, "youtube.com/t/terms")

    def test_accueil_affiche_les_liens(self):
        User.objects.create_user(username="samba", password="motdepasse123")
        self.client.login(username="samba", password="motdepasse123")
        reponse = self.client.get(reverse("accueil"))
        for nom in ["ma_cle", "mes_donnees", "supprimer_compte", "nouvelle_video", "conditions", "confidentialite"]:
            self.assertContains(reponse, reverse(nom))

    def test_style_servi_par_le_site_sans_cdn(self):
        reponse = self.client.get(reverse("conditions"))
        self.assertContains(reponse, "css/pico-2.1.1.min.css")
        self.assertNotContains(reponse, "cdn.jsdelivr.net")

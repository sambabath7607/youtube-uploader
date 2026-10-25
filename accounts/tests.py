import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token

from youtube_uploader.models import Video, YouTubeCredentials


class MaCleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="test", password="motdepasse123")

    def test_visiteur_non_connecte_renvoye_vers_connexion(self):
        reponse = self.client.get(reverse("ma_cle"))
        self.assertEqual(reponse.status_code, 302)
        self.assertIn(reverse("login"), reponse.url)

    def test_utilisateur_connecte_voit_sa_cle(self):
        self.client.login(username="test", password="motdepasse123")
        reponse = self.client.get(reverse("ma_cle"))
        token = Token.objects.get(user=self.user)
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, token.key)

    def test_regenerer_remplace_la_cle(self):
        self.client.login(username="test", password="motdepasse123")
        ancienne = Token.objects.create(user=self.user).key
        reponse = self.client.post(reverse("ma_cle"))
        self.assertRedirects(reponse, reverse("ma_cle"))
        nouvelle = Token.objects.get(user=self.user).key
        self.assertNotEqual(ancienne, nouvelle)


class InscriptionTests(TestCase):
    def donnees(self, **autres):
        valeurs = {"username": "nouveau", "password1": "UnMotDePasse!2026", "password2": "UnMotDePasse!2026",
                   "age_minimum": "on", "accepte_conditions": "on"}
        valeurs.update(autres)
        return {cle: valeur for cle, valeur in valeurs.items() if valeur is not None}

    def test_inscription_avec_les_deux_cases(self):
        self.client.post(reverse("inscription"), self.donnees())
        self.assertTrue(User.objects.filter(username="nouveau").exists())

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
        Token.objects.create(user=self.user)
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
        self.assertNotIn(Token.objects.get(user=self.user).key.encode(), reponse.content)

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
        self.assertFalse(Token.objects.exists())
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

"""Lot 3 : courriel du compte, mot de passe oublié, page Contact, liste d'attente Google."""
import re
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.urls import reverse

from youtube_uploader.models import YouTubeCredentials
from .models import ConnexionGoogle, ListeAttente


def donnees_inscription(**autres):
    valeurs = {"username": "nouveau", "email": "nouveau@exemple.com", "password1": "UnMotDePasse!2026",
               "password2": "UnMotDePasse!2026", "age_minimum": "on", "accepte_conditions": "on"}
    valeurs.update(autres)
    return {cle: valeur for cle, valeur in valeurs.items() if valeur is not None}


class CourrielInscriptionTests(TestCase):
    def test_courriel_enregistre(self):
        self.client.post(reverse("inscription"), donnees_inscription())
        self.assertEqual(User.objects.get(username="nouveau").email, "nouveau@exemple.com")

    def test_courriel_obligatoire(self):
        reponse = self.client.post(reverse("inscription"), donnees_inscription(email=None))
        self.assertFalse(User.objects.filter(username="nouveau").exists())
        self.assertTrue(reponse.context["form"].errors["email"])

    def test_courriel_deja_utilise_refuse_meme_en_majuscules(self):
        User.objects.create_user(username="ancien", email="nouveau@exemple.com", password="motdepasse123")
        reponse = self.client.post(reverse("inscription"), donnees_inscription(email="Nouveau@Exemple.COM"))
        self.assertFalse(User.objects.filter(username="nouveau").exists())
        self.assertContains(reponse, "Mot de passe oublié")


class MonCompteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ancien", password="motdepasse123")   # compte sans courriel

    def test_connexion_sans_courriel_mene_a_mon_compte(self):
        reponse = self.client.post(reverse("login"), {"username": "ancien", "password": "motdepasse123"})
        self.assertRedirects(reponse, reverse("mon_compte"))

    def test_connexion_avec_courriel_mene_a_l_accueil(self):
        self.user.email = "ancien@exemple.com"
        self.user.save()
        reponse = self.client.post(reverse("login"), {"username": "ancien", "password": "motdepasse123"})
        self.assertRedirects(reponse, reverse("accueil"))

    def test_connexion_avec_next_n_est_pas_interrompue(self):
        # ex. un agent IA qui demande l'autorisation : on revient bien là où on allait
        reponse = self.client.post(reverse("login") + "?next=" + reverse("ma_cle"),
                                   {"username": "ancien", "password": "motdepasse123"})
        self.assertRedirects(reponse, reverse("ma_cle"))

    def test_accueil_invite_a_ajouter_le_courriel(self):
        self.client.login(username="ancien", password="motdepasse123")
        self.assertContains(self.client.get(reverse("accueil")), "Ajouter mon courriel")

    def test_ajouter_son_courriel(self):
        self.client.login(username="ancien", password="motdepasse123")
        self.client.post(reverse("mon_compte"), {"email": "ancien@exemple.com", "mot_de_passe": "motdepasse123"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "ancien@exemple.com")

    def test_mot_de_passe_obligatoire_pour_changer_le_courriel(self):
        self.client.login(username="ancien", password="motdepasse123")
        self.client.post(reverse("mon_compte"), {"email": "pirate@exemple.com", "mot_de_passe": "faux"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "")

    def test_courriel_d_un_autre_compte_refuse(self):
        User.objects.create_user(username="autre", email="pris@exemple.com", password="motdepasse123")
        self.client.login(username="ancien", password="motdepasse123")
        reponse = self.client.post(reverse("mon_compte"), {"email": "PRIS@exemple.com", "mot_de_passe": "motdepasse123"})
        self.assertContains(reponse, "déjà utilisé")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "")

    def test_mon_compte_protege(self):
        reponse = self.client.get(reverse("mon_compte"))
        self.assertIn(reverse("login"), reponse.url)


class MotDePasseOublieTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="samba", email="samba@exemple.com", password="ancienMotDePasse1")

    def lien_recu(self):
        self.assertEqual(len(mail.outbox), 1)
        return re.search(r"https?://[^/\s]+(/\S+)", mail.outbox[0].body).group(1)

    def test_lien_sur_la_page_de_connexion(self):
        self.assertContains(self.client.get(reverse("login")), reverse("password_reset"))

    def test_parcours_complet_lien_valable_une_seule_fois(self):
        reponse = self.client.post(reverse("password_reset"), {"email": "SAMBA@exemple.com"})
        self.assertRedirects(reponse, reverse("password_reset_done"))
        lien = self.lien_recu()
        self.assertEqual(mail.outbox[0].to, ["samba@exemple.com"])
        self.assertIn("1 heure", mail.outbox[0].body)
        # Le lien mène au formulaire du nouveau mot de passe
        reponse = self.client.get(lien, follow=True)
        self.assertTrue(reponse.context["validlink"])
        reponse = self.client.post(reponse.redirect_chain[-1][0],
                                   {"new_password1": "NouveauMotDePasse!26", "new_password2": "NouveauMotDePasse!26"})
        self.assertRedirects(reponse, reverse("password_reset_complete"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NouveauMotDePasse!26"))
        # Nouveau mot de passe accepté à la connexion
        self.assertTrue(self.client.login(username="samba", password="NouveauMotDePasse!26"))
        self.client.logout()
        # Le même lien ne fonctionne plus
        reponse = self.client.get(lien, follow=True)
        self.assertFalse(reponse.context["validlink"])
        self.assertContains(reponse, "ne fonctionne plus")

    def test_courriel_inconnu_meme_reponse_sans_envoi(self):
        reponse = self.client.post(reverse("password_reset"), {"email": "inconnu@exemple.com"})
        self.assertRedirects(reponse, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(LIMITE_REINITIALISATION_PAR_HEURE=2)
    def test_limite_par_heure(self):
        for _ in range(4):
            self.client.post(reverse("password_reset"), {"email": "samba@exemple.com"})
        self.assertEqual(len(mail.outbox), 2)


@override_settings(SUPPORT_EMAIL="support@exemple.com")
class ContactTests(TestCase):
    def setUp(self):
        cache.clear()

    def message(self, **autres):
        valeurs = {"sujet": "probleme", "email": "client@exemple.com", "message": "Ma vidéo ne part pas sur YouTube."}
        valeurs.update(autres)
        return valeurs

    def test_page_et_lien_dans_le_pied_de_page(self):
        reponse = self.client.get(reverse("conditions"))
        self.assertContains(reponse, reverse("contact"))
        self.assertEqual(self.client.get(reverse("contact")).status_code, 200)

    def test_message_envoye_au_support_sans_etre_enregistre(self):
        reponse = self.client.post(reverse("contact"), self.message())
        self.assertRedirects(reponse, reverse("contact_envoye"))
        self.assertEqual(len(mail.outbox), 1)
        courriel = mail.outbox[0]
        self.assertEqual(courriel.to, ["support@exemple.com"])
        self.assertEqual(courriel.reply_to, ["client@exemple.com"])
        self.assertIn("Ma vidéo ne part pas", courriel.body)
        self.assertIn("Un problème technique", courriel.subject)

    def test_robot_ignore(self):
        reponse = self.client.post(reverse("contact"), self.message(site_web="http://pub.example"))
        self.assertRedirects(reponse, reverse("contact_envoye"))
        self.assertEqual(len(mail.outbox), 0)

    def test_message_trop_court_refuse(self):
        self.client.post(reverse("contact"), self.message(message="Salut"))
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(LIMITE_CONTACT_PAR_HEURE=2)
    def test_limite_par_heure(self):
        for _ in range(3):
            reponse = self.client.post(reverse("contact"), self.message())
        self.assertEqual(len(mail.outbox), 2)
        self.assertContains(reponse, "Réessaie dans une heure")

    def test_echec_d_envoi_explique(self):
        with patch("accounts.views.EmailMessage.send", side_effect=OSError("smtp")):
            reponse = self.client.post(reverse("contact"), self.message())
        self.assertContains(reponse, "pas pu partir")
        self.assertEqual(len(mail.outbox), 0)

    def test_courriel_prerempli_pour_un_membre(self):
        User.objects.create_user(username="samba", email="samba@exemple.com", password="motdepasse123")
        self.client.login(username="samba", password="motdepasse123")
        self.assertContains(self.client.get(reverse("contact")), "samba@exemple.com")

    def test_pages_legales_utilisent_l_adresse_de_support(self):
        for nom in ["conditions", "confidentialite"]:
            reponse = self.client.get(reverse(nom))
            self.assertContains(reponse, "support@exemple.com")
            self.assertNotContains(reponse, "outlook.fr")
            self.assertNotContains(reponse, "Batch Code AI")


@override_settings(SEUIL_LISTE_ATTENTE_GOOGLE=2, GOOGLE_APPLICATION_VERIFIEE=False, SUPPORT_EMAIL="support@exemple.com")
class ListeAttenteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="client", email="client@exemple.com", password="motdepasse123")
        self.client.login(username="client", password="motdepasse123")

    def connecter_chaines(self, nombre):
        for i in range(nombre):
            autre = User.objects.create_user(username=f"chaine{i}", password="motdepasse123")
            YouTubeCredentials.objects.create(user=autre, token_json="{}")

    @patch("accounts.views.connecter_youtube", return_value=HttpResponse("vers Google"))
    def test_sous_le_seuil_connexion_normale(self, connecter):
        self.connecter_chaines(1)
        reponse = self.client.get(reverse("connecter_youtube"))
        self.assertEqual(reponse.content, b"vers Google")

    @patch("accounts.views.connecter_youtube", return_value=HttpResponse("vers Google"))
    def test_au_seuil_liste_d_attente(self, connecter):
        self.connecter_chaines(2)
        reponse = self.client.get(reverse("connecter_youtube"))
        self.assertRedirects(reponse, reverse("liste_attente"))
        connecter.assert_not_called()

    def test_deconnexion_ne_libere_pas_de_place(self):
        # Google compte à vie : une chaîne déconnectée reste comptée
        self.connecter_chaines(2)
        YouTubeCredentials.objects.all().delete()
        self.assertEqual(ConnexionGoogle.objects.count(), 2)
        self.assertRedirects(self.client.get(reverse("connecter_youtube")), reverse("liste_attente"))

    @patch("accounts.views.connecter_youtube", return_value=HttpResponse("vers Google"))
    def test_reconnexion_toujours_possible(self, connecter):
        YouTubeCredentials.objects.create(user=self.user, token_json="{}")
        YouTubeCredentials.objects.filter(user=self.user).delete()
        self.connecter_chaines(2)
        self.assertEqual(self.client.get(reverse("connecter_youtube")).content, b"vers Google")

    @override_settings(GOOGLE_APPLICATION_VERIFIEE=True)
    @patch("accounts.views.connecter_youtube", return_value=HttpResponse("vers Google"))
    def test_application_verifiee_plus_de_limite(self, connecter):
        self.connecter_chaines(2)
        self.assertEqual(self.client.get(reverse("connecter_youtube")).content, b"vers Google")

    def test_inscription_et_samba_prevenu(self):
        self.connecter_chaines(2)
        reponse = self.client.post(reverse("liste_attente"), {"email": "client@exemple.com"}, follow=True)
        self.assertContains(reponse, "Tu es sur la liste d'attente")
        self.assertEqual(ListeAttente.objects.get().user, self.user)
        self.assertEqual(mail.outbox[0].to, ["support@exemple.com"])
        # Une seule inscription par compte
        self.client.post(reverse("liste_attente"), {"email": "autre@exemple.com"})
        self.assertEqual(ListeAttente.objects.count(), 1)

    def test_liste_d_attente_protegee(self):
        self.client.logout()
        self.assertIn(reverse("login"), self.client.get(reverse("liste_attente")).url)

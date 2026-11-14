"""Design et accessibilité : badge d'état, page de suivi en direct (vue JSON protégée), attributs d'accessibilité."""
import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .chiffrement import chiffrer
from .models import Video, YouTubeCredentials


class BadgeEtatTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="moi", password="motdepasse123")
        self.client.force_login(self.user)

    def test_classe_par_etat(self):
        attendu = {
            "en_attente": "badge-en_attente", "attente_fichier": "badge-en_attente",
            "en_cours": "badge-en_cours", "fabrication": "badge-en_cours", "reception": "badge-en_cours",
            "reussi": "badge-reussi",
            "echoue": "badge-echoue", "fabrication_echouee": "badge-echoue",
        }
        for etat, classe in attendu.items():
            with self.subTest(etat=etat):
                self.assertEqual(Video(user=self.user, titre="x", etat=etat).classe_badge, classe)

    def test_mes_videos_affiche_le_badge_avec_son_texte(self):
        Video.objects.create(user=self.user, titre="Ok", pour_enfants=False, fichier="videos/x.mp4",
                             etat="reussi", youtube_id="abc")
        reponse = self.client.get(reverse("mes_videos_site"))
        self.assertContains(reponse, 'class="badge badge-reussi"')
        self.assertContains(reponse, "Réussi")

    def test_resultat_erreur_en_message_error(self):
        video = Video.objects.create(user=self.user, titre="Ko", pour_enfants=False, fichier="videos/x.mp4",
                                     etat="echoue", erreur="Titre refusé")
        reponse = self.client.get(reverse("suivi_video", args=[video.id]))
        self.assertContains(reponse, 'class="message error"')
        self.assertContains(reponse, "Erreur : Titre refusé")
        self.assertContains(reponse, 'class="badge badge-echoue"')


class SuiviEnDirectTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="moi", password="motdepasse123")
        self.autre = User.objects.create_user(username="autre", password="motdepasse123")
        self.video = Video.objects.create(user=self.user, titre="Ma vidéo", pour_enfants=False,
                                          fichier="videos/x.mp4", etat="fabrication", etape="Rendu 3/12")
        self.client.force_login(self.user)

    def url_json(self, video=None):
        return reverse("etat_video_json", args=[(video or self.video).id])

    def test_page_sans_meta_refresh_avec_zone_aria_live(self):
        reponse = self.client.get(reverse("suivi_video", args=[self.video.id]))
        self.assertContains(reponse, 'id="etat-direct"')
        self.assertContains(reponse, 'aria-live="polite"')
        self.assertContains(reponse, f'data-url="{self.url_json()}"')
        self.assertContains(reponse, 'data-actif="1"')
        self.assertNotContains(reponse, 'http-equiv="refresh"')

    def test_zone_inactive_pour_une_video_terminee(self):
        self.video.etat = "reussi"
        self.video.save()
        reponse = self.client.get(reverse("suivi_video", args=[self.video.id]))
        self.assertContains(reponse, 'data-actif="0"')

    def test_json_donne_l_etat_au_proprietaire(self):
        reponse = self.client.get(self.url_json())
        self.assertEqual(reponse.status_code, 200)
        donnees = reponse.json()
        self.assertEqual(donnees["etat"], "fabrication")
        self.assertEqual(donnees["etat_libelle"], "Fabrication de la vidéo")
        self.assertEqual(donnees["classe"], "badge-en_cours")
        self.assertIn("Rendu 3/12", donnees["detail"])
        self.assertTrue(donnees["suivi_actif"])
        self.assertEqual(reponse["Cache-Control"], "max-age=0, no-cache, no-store, must-revalidate, private")

    def test_json_suivi_inactif_une_fois_termine(self):
        self.video.etat = "reussi"
        self.video.youtube_id = "yt-123"
        self.video.save()
        donnees = self.client.get(self.url_json()).json()
        self.assertFalse(donnees["suivi_actif"])
        self.assertEqual(donnees["youtube_id"], "yt-123")
        self.assertEqual(donnees["classe"], "badge-reussi")

    def test_json_refuse_la_video_d_un_autre(self):
        video_autre = Video.objects.create(user=self.autre, titre="Pas à moi", pour_enfants=False,
                                           fichier="videos/y.mp4", etat="en_cours")
        reponse = self.client.get(self.url_json(video_autre))
        self.assertEqual(reponse.status_code, 404)
        self.assertNotIn("Pas à moi", reponse.content.decode())
        self.assertNotIn("etat", reponse.json().keys())

    def test_json_refuse_un_visiteur_non_connecte(self):
        self.client.logout()
        reponse = self.client.get(self.url_json())
        self.assertEqual(reponse.status_code, 302)
        self.assertIn(reverse("login"), reponse["Location"])

    def test_json_refuse_une_video_inconnue(self):
        self.assertEqual(self.client.get(reverse("etat_video_json", args=[999999])).status_code, 404)


class AccessibiliteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="moi", password="motdepasse123", email="moi@example.com")
        self.client.force_login(self.user)

    def test_mes_videos_tableau_defilant_et_lien_voir_nomme(self):
        Video.objects.create(user=self.user, titre="Leçon 1", pour_enfants=False, fichier="videos/x.mp4",
                             etat="reussi", youtube_id="abc")
        reponse = self.client.get(reverse("mes_videos_site"))
        self.assertContains(reponse, '<div class="tableau-defilant">')
        self.assertContains(reponse, 'aria-label="Voir « Leçon 1 » sur YouTube (nouvel onglet)"')

    def test_accueil_boutons_de_deconnexion_secondaires(self):
        YouTubeCredentials.objects.create(user=self.user, token_json=chiffrer(json.dumps({"refresh_token": "abc"})))
        reponse = self.client.get(reverse("accueil"))
        self.assertContains(reponse, 'class="secondary">Se déconnecter')
        self.assertContains(reponse, 'class="secondary">Déconnecter ma chaîne YouTube')

    def test_accueil_connecter_est_un_bouton_accessible(self):
        reponse = self.client.get(reverse("accueil"))
        self.assertContains(reponse, f'href="{reverse("connecter_youtube")}" role="button">Connecter ma chaîne YouTube')

    def test_accueil_etapes_avec_texte_cache(self):
        reponse = self.client.get(reverse("accueil"))
        self.assertContains(reponse, '<span aria-hidden="true">⬜</span><span class="visuellement-cachee">à faire :</span>')

    def test_guide_zone_de_statut_et_entete_de_colonne(self):
        self.client.logout()
        reponse = self.client.get(reverse("guide_claude"))
        self.assertContains(reponse, 'id="prompt-copie" role="status"')
        self.assertContains(reponse, '<th><span class="visuellement-cachee">Action</span></th>')
        self.assertNotContains(reponse, "<th></th>")

    def test_supprimer_mon_compte_est_marque_danger(self):
        reponse = self.client.get(reverse("mon_compte"))
        self.assertContains(reponse, f'<a href="{reverse("supprimer_compte")}" class="danger">Supprimer mon compte</a>')

    def test_theme_clair_force_et_pied_de_page(self):
        self.client.logout()
        reponse = self.client.get(reverse("guide_claude"))
        self.assertContains(reponse, '<html lang="fr" data-theme="light">')
        self.assertContains(reponse, 'class="liens-pied"')

    def test_inscription_du_header_en_bouton(self):
        self.client.logout()
        reponse = self.client.get(reverse("guide_claude"))
        self.assertContains(reponse, f'href="{reverse("inscription")}" role="button">S\'inscrire')

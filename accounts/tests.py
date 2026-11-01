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

    def test_plusieurs_cles_et_suppression(self):
        # B2 : une clé par appareil ; en créer une n'annule pas les autres, on supprime clé par clé
        self.client.login(username="test", password="motdepasse123")
        ancienne = CleApi.creer_pour(self.user, "PC")
        self.client.post(reverse("ma_cle"), {"action": "creer", "nom": "claude.ai"})
        self.assertEqual(CleApi.objects.filter(user=self.user).count(), 2)
        self.assertTrue(CleApi.objects.filter(empreinte=empreinte(ancienne)).exists())
        self.assertTrue(CleApi.objects.filter(user=self.user, nom="claude.ai").exists())
        cle_pc = CleApi.objects.get(user=self.user, nom="PC")
        self.client.post(reverse("ma_cle"), {"action": "supprimer", "id": cle_pc.id})
        self.assertFalse(CleApi.objects.filter(id=cle_pc.id).exists())

    def test_on_ne_supprime_pas_la_cle_d_un_autre(self):
        autre = User.objects.create_user(username="autre", password="motdepasse123")
        cle_autre = CleApi.creer_pour(autre)
        self.client.login(username="test", password="motdepasse123")
        self.client.post(reverse("ma_cle"), {"action": "supprimer", "id": CleApi.objects.get(user=autre).id})
        self.assertTrue(CleApi.objects.filter(empreinte=empreinte(cle_autre)).exists())

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
        for nom in ["confidentialite", "conditions", "guide_claude"]:
            reponse = self.client.get(reverse(nom))
            self.assertEqual(reponse.status_code, 200)
            if nom != "guide_claude":
                self.assertContains(reponse, "youtube.com/t/terms")

    def test_accueil_affiche_les_liens(self):
        User.objects.create_user(username="samba", password="motdepasse123")
        self.client.login(username="samba", password="motdepasse123")
        reponse = self.client.get(reverse("accueil"))
        for nom in ["ma_cle", "mes_donnees", "supprimer_compte", "nouvelle_video", "conditions", "confidentialite", "ma_voix", "guide_claude"]:
            self.assertContains(reponse, reverse(nom))

    def test_style_servi_par_le_site_sans_cdn(self):
        reponse = self.client.get(reverse("conditions"))
        self.assertContains(reponse, "css/pico-2.1.1.min.css")
        self.assertNotContains(reponse, "cdn.jsdelivr.net")


class GuideClaudeTests(TestCase):
    def test_prompt_general_et_outils(self):
        reponse = self.client.get(reverse("guide_claude"))
        self.assertEqual(reponse.status_code, 200)
        for mot in ["fabriquer_voix", "preparer_envoi", "etat_video", "x-api-key", "Copier le prompt"]:
            self.assertContains(reponse, mot)


class BoutonClaudeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="samba", password="motdepasse123")
        self.client.login(username="samba", password="motdepasse123")

    def test_bouton_absent_sans_chaine_youtube(self):
        self.assertNotContains(self.client.get(reverse("accueil")), "Créer une vidéo avec Claude Code")

    def test_bouton_avec_chaine_youtube(self):
        YouTubeCredentials.objects.create(user=self.user, token_json="{}")
        reponse = self.client.get(reverse("accueil"))
        self.assertContains(reponse, "Créer une vidéo avec Claude Code")
        self.assertContains(reponse, reverse("guide_claude") + "#creer-une-video")
        self.assertNotContains(reponse, "claude.ai/new")
        self.assertContains(reponse, reverse("guide_claude") + "#autres-agents")


class ConnexionEnUnClicTests(TestCase):
    """B1 : parcours OAuth complet d'un agent IA (enregistrement → Autoriser → jeton → API → rafraîchissement)."""

    RETOUR = "https://claude.ai/api/mcp/auth_callback"

    def setUp(self):
        import base64, hashlib
        self.user = User.objects.create_user(username="samba", password="motdepasse123")
        self.verificateur = "v" * 50
        self.defi = base64.urlsafe_b64encode(hashlib.sha256(self.verificateur.encode()).digest()).rstrip(b"=").decode()

    def enregistrer(self, uris=None):
        return self.client.post("/oauth/register/", json.dumps({"client_name": "Claude", "redirect_uris": uris or [self.RETOUR]}),
                                content_type="application/json")

    def autoriser(self, client_id, decision="autoriser", **autres):
        params = {"response_type": "code", "client_id": client_id, "redirect_uri": self.RETOUR, "state": "etat123",
                  "code_challenge": self.defi, "code_challenge_method": "S256", "resource": "http://testserver/mcp",
                  "decision": decision}
        params.update(autres)
        return self.client.post("/oauth/authorize/", params)

    def code_depuis(self, reponse):
        from urllib.parse import parse_qs, urlparse
        return parse_qs(urlparse(reponse["Location"]).query)

    def test_metadonnees(self):
        serveur = self.client.get("/.well-known/oauth-authorization-server").json()
        self.assertEqual(serveur["code_challenge_methods_supported"], ["S256"])
        ressource = self.client.get("/.well-known/oauth-protected-resource/mcp").json()
        self.assertEqual(ressource["resource"], "http://testserver/mcp")

    def test_parcours_complet(self):
        from rest_framework.test import APIClient
        client_id = self.enregistrer().json()["client_id"]
        self.client.force_login(self.user)
        self.assertContains(self.client.get("/oauth/authorize/", {
            "response_type": "code", "client_id": client_id, "redirect_uri": self.RETOUR,
            "code_challenge": self.defi, "code_challenge_method": "S256"}), "Autoriser « Claude »")
        retour = self.code_depuis(self.autoriser(client_id))
        self.assertEqual(retour["state"], ["etat123"])
        self.assertEqual(retour["iss"], ["http://testserver"])
        jetons = self.client.post("/oauth/token/", {"grant_type": "authorization_code", "code": retour["code"][0],
                                                    "redirect_uri": self.RETOUR, "client_id": client_id,
                                                    "code_verifier": self.verificateur}).json()
        self.assertEqual(jetons["token_type"], "Bearer")
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION="Bearer " + jetons["access_token"])
        self.assertEqual(api.get(reverse("api_mon_compte")).status_code, 200)
        # le code ne sert qu'une fois
        deuxieme = self.client.post("/oauth/token/", {"grant_type": "authorization_code", "code": retour["code"][0],
                                                      "redirect_uri": self.RETOUR, "client_id": client_id,
                                                      "code_verifier": self.verificateur})
        self.assertEqual(deuxieme.json()["error"], "invalid_grant")
        # rafraîchissement avec rotation
        nouveaux = self.client.post("/oauth/token/", {"grant_type": "refresh_token", "client_id": client_id,
                                                      "refresh_token": jetons["refresh_token"]}).json()
        self.assertIn("access_token", nouveaux)
        rejoue = self.client.post("/oauth/token/", {"grant_type": "refresh_token", "client_id": client_id,
                                                    "refresh_token": jetons["refresh_token"]})
        self.assertEqual(rejoue.json()["error"], "invalid_grant")

    def test_pkce_incorrect_refuse(self):
        client_id = self.enregistrer().json()["client_id"]
        self.client.force_login(self.user)
        code = self.code_depuis(self.autoriser(client_id))["code"][0]
        reponse = self.client.post("/oauth/token/", {"grant_type": "authorization_code", "code": code, "redirect_uri": self.RETOUR,
                                                     "client_id": client_id, "code_verifier": "mauvais" * 8})
        self.assertEqual(reponse.json()["error"], "invalid_grant")

    def test_refus_renvoie_access_denied(self):
        client_id = self.enregistrer().json()["client_id"]
        self.client.force_login(self.user)
        self.assertEqual(self.code_depuis(self.autoriser(client_id, decision="refuser"))["error"], ["access_denied"])

    def test_adresse_de_retour_inconnue_jamais_suivie(self):
        client_id = self.enregistrer().json()["client_id"]
        self.client.force_login(self.user)
        reponse = self.autoriser(client_id, redirect_uri="https://pirate.example/vol")
        self.assertEqual(reponse.status_code, 400)

    def test_enregistrement_refuse_http_hors_localhost(self):
        self.assertEqual(self.enregistrer(["http://pirate.example/cb"]).status_code, 400)
        self.assertEqual(self.enregistrer(["http://127.0.0.1:33418/callback"]).status_code, 201)

    def test_retirer_l_acces(self):
        from rest_framework.test import APIClient
        client_id = self.enregistrer().json()["client_id"]
        self.client.force_login(self.user)
        code = self.code_depuis(self.autoriser(client_id))["code"][0]
        jeton = self.client.post("/oauth/token/", {"grant_type": "authorization_code", "code": code, "redirect_uri": self.RETOUR,
                                                   "client_id": client_id, "code_verifier": self.verificateur}).json()["access_token"]
        from .models import ClientOAuth
        self.client.post(reverse("oauth_retirer"), {"client": ClientOAuth.objects.get(client_id=client_id).id})
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION="Bearer " + jeton)
        self.assertEqual(api.get(reverse("api_mon_compte")).status_code, 401)


class AccueilTests(TestCase):
    def test_visiteur_voit_la_presentation_publique(self):
        reponse = self.client.get(reverse("accueil"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Comment ça marche")
        self.assertContains(reponse, reverse("confidentialite"))

    def test_etapes_demarrer(self):
        User.objects.create_user(username="samba", password="motdepasse123")
        self.client.login(username="samba", password="motdepasse123")
        reponse = self.client.get(reverse("accueil"))
        self.assertContains(reponse, "Démarrer (0 / 5)")
        YouTubeCredentials.objects.create(user=User.objects.get(username="samba"), token_json="{}")
        self.assertContains(self.client.get(reverse("accueil")), "Démarrer (1 / 5)")

"""Tests des lots 1 et 2 : vidéos fabriquées sur Modal (Modal est toujours simulé : aucun appel réel, aucune dépense)."""
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import CleApi
from fabrication_modal import modeles

from . import fabrication
from .models import Video, VoixUtilisateur, YouTubeCredentials
from .validation import LIMITE_ENVOIS_PAR_JOUR

DOSSIER_MEDIA = tempfile.mkdtemp()

SCRIPT = ("Les listes en Python.\n\n"
          "Une liste est ordonnée et modifiable.\n\n"
          "On ajoute un élément avec append.\n\n"
          "Merci d'avoir regardé !")
SCENES = [
    {"type": "titre", "texte": "Les listes en Python"},
    {"type": "points", "texte": "Une liste, c'est :", "points": ["ordonnée", "modifiable"]},
    {"type": "code", "texte": "Ajouter", "code": "fruits.append(\"kiwi\")", "langage": "python"},
    {"type": "fin", "texte": "Merci !"},
]


class CalculsDesModelesTests(TestCase):
    """fabrication_modal/modeles.py : le même code sert au site et au service Modal."""

    def test_quatre_modeles_avec_exemple_valide(self):
        self.assertEqual(set(modeles.MODELES), {"lecon", "astuces", "presentation", "short"})
        for nom, modele in modeles.MODELES.items():
            exemple = modele["exemple"]
            self.assertEqual(len(modeles.paragraphes(exemple["script"])), len(exemple["scenes"]), nom)
            self.assertTrue({s["type"] for s in exemple["scenes"]} <= set(modele["types"]), nom)
            self.assertLessEqual(modeles.duree_estimee(exemple["script"]), modele["duree_max"], nom)

    def test_decoupage_en_morceaux_de_200_images_au_plus_30(self):
        morceaux = modeles.decouper(900)                  # 30 s
        self.assertEqual(len(morceaux), 5)
        self.assertEqual(morceaux[0], (0, 199))
        self.assertEqual(morceaux[-1], (800, 899))
        longs = modeles.decouper(18000)                   # 10 min : jamais plus de 30 machines
        self.assertEqual(len(longs), 30)
        self.assertEqual(longs[-1][1], 17999)
        # Aucune image oubliée ni rendue deux fois
        images = [i for debut, fin in longs for i in range(debut, fin + 1)]
        self.assertEqual(images, list(range(18000)))

    def test_scenes_calees_sur_le_minutage_de_la_voix(self):
        minutage = [{"debut": 0, "duree": 3.0}, {"debut": 3.7, "duree": 4.0}, {"debut": 8.4, "duree": 2.0}]
        scenes, total = modeles.images_des_scenes(minutage, 3)
        self.assertEqual(scenes[0], (0, 111))             # jusqu'au début du 2e paragraphe (3,7 s)
        self.assertEqual(scenes[1], (111, 141))
        self.assertEqual(scenes[2][0], 252)
        self.assertEqual(total, round((8.4 + 2.0 + modeles.FIN_VIDEO) * 30))

    def test_props_remotion_numerotees(self):
        props = modeles.props_remotion("astuces", "Titre", SCENES, "#3B8BFF", modeles.minutage_estime(SCRIPT))
        self.assertEqual((props["largeur"], props["hauteur"]), (1920, 1080))
        self.assertEqual([s["numero"] for s in props["scenes"]], [0, 1, 2, 0])
        self.assertEqual(props["duree"], props["scenes"][-1]["debut"] + props["scenes"][-1]["duree"])
        short = modeles.props_remotion("short", "Titre", SCENES, "#3B8BFF", modeles.minutage_estime(SCRIPT))
        self.assertEqual((short["largeur"], short["hauteur"]), (1080, 1920))


@override_settings(MEDIA_ROOT=DOSSIER_MEDIA)
class BaseFabrication(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(DOSSIER_MEDIA, ignore_errors=True)

    def setUp(self):
        from . import models
        self.dossier_prive = tempfile.mkdtemp()
        self.ancien_emplacement = models.stockage_prive.location
        models.stockage_prive.location = self.dossier_prive
        self.user = User.objects.create_user(username="samba", password="motdepasse123")
        YouTubeCredentials.objects.create(user=self.user, token_json="{}")
        self.voix = VoixUtilisateur.objects.create(user=self.user, mode="en_ligne", consentement_le=timezone.now())
        self.voix.extrait.save("voix.webm", SimpleUploadedFile("voix.webm", b"son"))
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Token " + CleApi.creer_pour(self.user))

    def tearDown(self):
        from . import models
        models.stockage_prive.location = self.ancien_emplacement
        shutil.rmtree(self.dossier_prive, ignore_errors=True)

    def demander(self, **champs):
        donnees = {"modele": "lecon", "titre": "Les listes", "script": SCRIPT, "scenes": SCENES,
                   "pour_enfants": False, "contenu_ia": False}
        donnees.update(champs)
        donnees = {cle: valeur for cle, valeur in donnees.items() if valeur is not None}
        return self.client.post(reverse("api_fabrications"), donnees, format="json")


@patch("youtube_uploader.api.lancer_fabrication", return_value="fc-video-1")
class ApiFabricationTests(BaseFabrication):
    """C1 : POST /youtube/api/v1/fabrications/ (Modal simulé)."""

    def test_fabrication_lancee_202(self, lancer):
        reponse = self.demander()
        self.assertEqual(reponse.status_code, 202, reponse.content)
        corps = reponse.json()
        self.assertEqual((corps["etat"], corps["modele"]), ("fabrication", "lecon"))
        self.assertTrue(corps["contenu_ia"])             # voix clonée = contenu IA, même si l'agent a répondu non
        video = Video.objects.get(id=corps["id"])
        self.assertEqual(video.appel_modal, "fc-video-1")
        donnees = lancer.call_args.args[0]
        self.assertEqual(donnees["voix"]["reference"], b"son")    # l'extrait part chez Modal…
        self.assertNotIn("reference", str(video.donnees_modele))   # … mais n'est jamais gardé en base
        self.assertEqual(donnees["scenes"][2]["code"], "fruits.append(\"kiwi\")")
        self.voix.refresh_from_db()
        self.assertGreater(self.voix.secondes_utilisees, 0)
        self.assertEqual(video.donnees_modele["secondes_voix"], self.voix.secondes_utilisees)

    def test_sans_voix_rien_n_est_decompte(self, lancer):
        reponse = self.demander(avec_ma_voix=False)
        self.assertEqual(reponse.status_code, 202)
        self.assertFalse(reponse.json()["contenu_ia"])
        self.assertIsNone(lancer.call_args.args[0]["voix"])
        self.voix.refresh_from_db()
        self.assertEqual(self.voix.secondes_utilisees, 0)

    def test_modal_indisponible_503_sans_trace(self, lancer):
        lancer.side_effect = RuntimeError("panne")
        with self.assertLogs("youtube_uploader.api", level="ERROR"):
            reponse = self.demander()
        self.assertEqual(reponse.status_code, 503)
        self.assertEqual(reponse.json()["code"], "service_video_indisponible")
        self.assertFalse(Video.objects.exists())
        self.voix.refresh_from_db()
        self.assertEqual(self.voix.secondes_utilisees, 0)

    def test_une_fabrication_a_la_fois(self, lancer):
        self.assertEqual(self.demander().status_code, 202)
        reponse = self.demander(titre="Autre vidéo")
        self.assertEqual(reponse.status_code, 409)
        self.assertEqual(reponse.json()["code"], "fabrication_en_cours")

    def test_doublon_meme_titre(self, lancer):
        Video.objects.create(user=self.user, titre="Les listes", pour_enfants=False, etat="en_attente", fichier="x.mp4")
        reponse = self.demander()
        self.assertEqual(reponse.status_code, 409)
        self.assertEqual(reponse.json()["code"], "envoi_en_double")

    def test_duree_maximale_du_modele(self, lancer):
        long = "\n\n".join(["mot " * 60] * 3)               # ~72 s : trop long pour un Short (60 s)
        scenes = [{"type": "texte", "texte": "Idée"}] * 3
        reponse = self.demander(modele="short", script=long, scenes=scenes)
        self.assertEqual(reponse.status_code, 400)
        self.assertEqual(reponse.json()["code"], "video_trop_longue")
        lancer.assert_not_called()

    @override_settings(RENDU_DUREE_MAX_SECONDES=5)
    def test_duree_maximale_du_service(self, lancer):
        self.assertEqual(self.demander().json()["code"], "video_trop_longue")

    def test_quota_de_voix_insuffisant(self, lancer):
        self.voix.quota_secondes = 1
        self.voix.save()
        reponse = self.demander()
        self.assertEqual(reponse.status_code, 429)
        self.assertEqual(reponse.json()["code"], "quota_voix_atteint")
        lancer.assert_not_called()

    def test_sans_voix_enregistree(self, lancer):
        self.voix.delete()
        self.assertEqual(self.demander().json()["code"], "voix_absente")

    def test_chaine_non_connectee(self, lancer):
        YouTubeCredentials.objects.all().delete()
        reponse = self.demander()
        self.assertEqual(reponse.status_code, 400)
        self.assertEqual(reponse.json()["code"], "youtube_non_connecte")

    def test_limite_du_jour(self, lancer):
        for i in range(LIMITE_ENVOIS_PAR_JOUR):
            Video.objects.create(user=self.user, titre=f"V{i}", pour_enfants=False, etat="reussi", fichier="")
        self.assertEqual(self.demander().status_code, 429)

    def test_une_fabrication_echouee_ne_compte_pas_dans_la_limite(self, lancer):
        for i in range(LIMITE_ENVOIS_PAR_JOUR):
            Video.objects.create(user=self.user, titre=f"V{i}", pour_enfants=False, etat="fabrication_echouee",
                                 fichier="")
        self.assertEqual(self.demander().status_code, 202)

    @override_settings(ENVOIS_SERVICE_PAR_JOUR=2)
    def test_limite_de_tout_le_service(self, lancer):
        autre = User.objects.create_user(username="autre", password="motdepasse123")
        for i in range(2):
            Video.objects.create(user=autre, titre=f"V{i}", pour_enfants=False, etat="reussi", fichier="")
        reponse = self.demander()
        self.assertEqual(reponse.status_code, 429)
        self.assertEqual(reponse.json()["code"], "limite_service_atteinte")

    def test_sans_cle_401(self, lancer):
        self.client.credentials()
        self.assertEqual(self.demander().status_code, 401)


@patch("youtube_uploader.api.lancer_fabrication", return_value="fc-video-1")
class ValidationDesChampsTests(BaseFabrication):
    """M3 : chaque champ invalide est refusé avec un message clair pour l'agent IA."""

    def refus(self, champ, **champs):
        reponse = self.demander(**champs)
        self.assertEqual(reponse.status_code, 400, reponse.content)
        self.assertEqual(reponse.json()["code"], "donnees_invalides")
        self.assertIn(champ, reponse.json()["details"])
        return reponse.json()["details"][champ]

    def test_modele_inconnu(self, lancer):
        self.refus("modele", modele="film")

    def test_pour_enfants_obligatoire(self, lancer):
        self.refus("pour_enfants", pour_enfants=None)

    def test_un_paragraphe_par_scene(self, lancer):
        message = self.refus("script", script="Un seul paragraphe.")
        self.assertIn("une scène = un paragraphe", str(message))

    def test_type_de_scene_inconnu(self, lancer):
        self.refus("scenes", scenes=[{"type": "video", "texte": "x"}] + SCENES[1:])

    def test_type_non_permis_par_le_modele(self, lancer):
        message = self.refus("scenes", modele="presentation")   # pas de scène « code » dans une présentation
        self.assertIn("code", str(message))

    def test_scene_points_sans_points(self, lancer):
        scenes = [dict(SCENES[0]), {"type": "points", "texte": "Liste"}, SCENES[2], SCENES[3]]
        self.refus("scenes", scenes=scenes)

    def test_code_trop_long(self, lancer):
        scenes = [SCENES[0], SCENES[1], {"type": "code", "texte": "x", "code": "a = 1\n" * 25}, SCENES[3]]
        self.refus("scenes", scenes=scenes)

    def test_texte_trop_long(self, lancer):
        scenes = [{"type": "titre", "texte": "a" * 201}] + SCENES[1:]
        self.refus("scenes", scenes=scenes)

    def test_couleur_invalide(self, lancer):
        self.refus("accent", accent="bleu")

    def test_trop_de_scenes_pour_un_short(self, lancer):
        scenes = [{"type": "texte", "texte": "Idée"}] * 9
        self.refus("scenes", modele="short", script="\n\n".join(["Court."] * 9), scenes=scenes)

    def test_titre_trop_long(self, lancer):
        self.refus("titre", titre="a" * 101)


class ApiModelesTests(BaseFabrication):
    """C3 : la liste des modèles et de leurs champs."""

    def test_liste_des_modeles(self):
        reponse = self.client.get(reverse("api_modeles"))
        self.assertEqual(reponse.status_code, 200)
        noms = [m["nom"] for m in reponse.json()["modeles"]]
        self.assertEqual(noms, ["lecon", "astuces", "presentation", "short"])
        self.assertEqual(reponse.json()["modeles"][3]["duree_max_secondes"], 60)
        self.assertIn("code", reponse.json()["types_de_scene"])

    def test_sans_cle_401(self):
        self.client.credentials()
        self.assertEqual(self.client.get(reverse("api_modeles")).status_code, 401)

    def test_page_modeles_publique(self):
        reponse = Client().get(reverse("modeles_video"))
        self.assertEqual(reponse.status_code, 200)
        for nom in ("Leçon", "Astuces", "Présentation", "Short (vertical)"):
            self.assertContains(reponse, nom)
        self.assertContains(reponse, "<h1>", count=1)


def ecrire_video(nom, chemin):
    Path(chemin).write_bytes(b"video fabriquee")


class SuiviParLeWorkerTests(BaseFabrication):
    """T2 et F5 : le worker suit la fabrication, récupère la vidéo, l'envoie puis efface tout."""

    def fabrication(self, secondes_voix=30, il_y_a=timedelta(0)):
        self.voix.secondes_utilisees = secondes_voix
        self.voix.save()
        video = Video.objects.create(
            user=self.user, titre="Les listes", pour_enfants=False, contenu_ia=True, etat="fabrication", fichier="",
            modele="lecon", appel_modal="fc-1", etape="Préparation",
            donnees_modele={"cle": "video-1-abc", "script": SCRIPT, "scenes": SCENES, "accent": "#3B8BFF",
                            "musique": "calme", "avec_ma_voix": True, "secondes_voix": secondes_voix})
        Video.objects.filter(id=video.id).update(created_at=timezone.now() - il_y_a)
        video.refresh_from_db()
        return video

    @patch("youtube_uploader.fabrication.lire_progression", return_value={"etape": "rendu", "fait": 7, "total": 12})
    @patch("youtube_uploader.fabrication.resultat_fabrication", return_value=None)
    def test_etape_en_cours_affichee(self, resultat, progression):
        video = self.fabrication()
        fabrication.suivre_fabrications()
        video.refresh_from_db()
        self.assertEqual((video.etat, video.etape), ("fabrication", "Rendu 7/12"))
        corps = self.client.get(reverse("api_etat_video", args=[video.id])).json()
        self.assertEqual((corps["etat"], corps["etape"]), ("fabrication", "Rendu 7/12"))

    @patch("youtube_uploader.envois.upload_video", return_value={"id": "yt123", "snippet": {}})
    @patch("youtube_uploader.fabrication.effacer_chez_modal")
    @patch("youtube_uploader.fabrication.telecharger_video", side_effect=ecrire_video)
    @patch("youtube_uploader.fabrication.resultat_fabrication",
           return_value={"fichier": "video-1-abc.mp4", "duree": 17.2, "taille": 15, "mesures": {"rendu": 20.5}})
    def test_video_prete_recuperee_envoyee_puis_effacee(self, resultat, telecharger, effacer, upload):
        video = self.fabrication()
        with self.assertLogs("youtube_uploader.fabrication", level="WARNING"):
            call_command("traiter_envois", "--une-fois")
        video.refresh_from_db()
        self.assertEqual((video.etat, video.youtube_id), ("reussi", "yt123"))
        telecharger.assert_called_once()
        effacer.assert_called_once_with("video-1-abc.mp4")          # effacée chez Modal
        self.assertFalse(video.fichier)                              # et sur le serveur après l'envoi
        self.assertEqual(video.duree_secondes, 17)
        self.assertEqual(video.donnees_modele["mesures"]["rendu"], 20.5)
        self.assertIn("recuperation", video.donnees_modele["mesures"])   # mesure T4
        self.voix.refresh_from_db()
        self.assertEqual(self.voix.secondes_utilisees, 30)           # réussite : le quota reste décompté

    @patch("youtube_uploader.fabrication.resultat_fabrication", side_effect=RuntimeError("Remotion a planté"))
    def test_echec_quota_rendu(self, resultat):
        video = self.fabrication()
        with self.assertLogs("youtube_uploader.fabrication", level="ERROR"):
            fabrication.suivre_fabrications()
        video.refresh_from_db()
        self.assertEqual(video.etat, "fabrication_echouee")
        self.assertNotIn("Remotion", video.erreur)                   # aucun détail interne pour le client
        self.voix.refresh_from_db()
        self.assertEqual(self.voix.secondes_utilisees, 0)
        fabrication.suivre_fabrications()                            # jamais rendu deux fois
        self.voix.refresh_from_db()
        self.assertEqual(self.voix.secondes_utilisees, 0)

    @patch("youtube_uploader.fabrication.arreter_fabrication")
    @patch("youtube_uploader.fabrication.resultat_fabrication", return_value=None)
    def test_delai_maximal_depasse(self, resultat, arreter):
        video = self.fabrication(il_y_a=timedelta(minutes=31))
        with self.assertLogs("youtube_uploader.fabrication", level="WARNING"):
            fabrication.suivre_fabrications()
        video.refresh_from_db()
        self.assertEqual(video.etat, "fabrication_echouee")
        arreter.assert_called_once_with("fc-1")
        self.voix.refresh_from_db()
        self.assertEqual(self.voix.secondes_utilisees, 0)

    @patch("youtube_uploader.fabrication.effacer_chez_modal")
    @patch("youtube_uploader.fabrication.telecharger_video", side_effect=ConnectionError("coupure"))
    @patch("youtube_uploader.fabrication.resultat_fabrication", return_value={"fichier": "v.mp4", "duree": 10})
    def test_recuperation_impossible(self, resultat, telecharger, effacer):
        video = self.fabrication()
        with self.assertLogs("youtube_uploader.fabrication", level="ERROR"):
            fabrication.suivre_fabrications()
        video.refresh_from_db()
        self.assertEqual(video.etat, "fabrication_echouee")
        effacer.assert_called_once_with("v.mp4")
        self.voix.refresh_from_db()
        self.assertEqual(self.voix.secondes_utilisees, 0)

    def test_mon_compte_ne_compte_pas_les_echecs(self):
        Video.objects.create(user=self.user, titre="X", pour_enfants=False, etat="fabrication_echouee", fichier="")
        corps = self.client.get(reverse("api_mon_compte")).json()
        self.assertEqual(corps["envois_restants_aujourd_hui"], LIMITE_ENVOIS_PAR_JOUR)

    def test_pages_du_site_affichent_l_etape(self):
        video = self.fabrication()
        Video.objects.filter(id=video.id).update(etape="Voix en cours")
        navigateur = Client()
        navigateur.force_login(self.user)
        self.assertContains(navigateur.get(reverse("suivi_video", args=[video.id])), "Voix en cours")
        self.assertContains(navigateur.get(reverse("mes_videos_site")), "Voix en cours")

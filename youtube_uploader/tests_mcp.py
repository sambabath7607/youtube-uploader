"""Tests du connecteur MCP (mcp_server.py) : téléchargement des vidéos seulement depuis une adresse publique."""
import asyncio
import http.server
import tempfile
import threading
from unittest.mock import patch

import importlib.util
import unittest

import requests
from django.test import SimpleTestCase

# Le paquet mcp n'est installé que sur le serveur : sans lui, ces tests sont sautés
MCP_INSTALLE = importlib.util.find_spec("mcp") is not None
if MCP_INSTALLE:
    import mcp_server


class ServeurLocal:
    """Petit serveur sur 127.0.0.1 qui compte les requêtes reçues."""

    def __enter__(self):
        compteur = self.requetes = []

        class Gestionnaire(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                compteur.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"secret interne")

            def log_message(self, *args):
                pass

        self.serveur = http.server.HTTPServer(("127.0.0.1", 0), Gestionnaire)
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.serveur.server_port}/video.mp4"
        return self

    def __exit__(self, *args):
        self.serveur.shutdown()
        self.serveur.server_close()


@unittest.skipUnless(MCP_INSTALLE, "paquet mcp absent (installé seulement sur le serveur)")
class TelechargementTests(SimpleTestCase):
    def telecharger(self, url):
        with tempfile.TemporaryFile() as fichier:
            return mcp_server.telecharger(url, fichier), fichier.tell()

    def test_lien_interne_refuse(self):
        with ServeurLocal() as serveur:
            message, taille = self.telecharger(serveur.url)
        self.assertIn("Lien refusé", message)
        self.assertEqual(serveur.requetes, [])

    def test_dns_rebinding_refuse_a_la_connexion(self):
        # Le premier filtre (DNS) est trompé : il croit l'adresse publique. La connexion réelle doit être refusée.
        with ServeurLocal() as serveur, patch("mcp_server.adresse_autorisee", return_value=True):
            with self.assertLogs("mcp_server", level="WARNING"):
                message, taille = self.telecharger(serveur.url)
        self.assertIn("Lien refusé", message)
        self.assertEqual(taille, 0)
        self.assertEqual(serveur.requetes, [])  # aucune requête n'a atteint le service interne

    def test_proxy_ignore(self):
        self.assertFalse(mcp_server.session_de_telechargement().trust_env)

    @patch("mcp_server.requests.get", side_effect=requests.ConnectionError("/home/batch/détail interne"))
    def test_message_de_connexion_sans_detail(self, get):
        with self.assertLogs("mcp_server", level="ERROR"):
            reponse = mcp_server.lire("Token abc", "https://exemple.com/")
        self.assertEqual(reponse, {"erreur": mcp_server.MESSAGE_CONNEXION})


@unittest.skipUnless(MCP_INSTALLE, "paquet mcp absent (installé seulement sur le serveur)")
class VerifierCleTests(SimpleTestCase):
    """La clé peut arriver dans Authorization (Claude Code) ou dans X-API-Key (claude.ai)."""

    def appeler(self, entetes):
        recu, envoye = {}, []

        async def application(scope, receive, send):
            recu["cle"] = mcp_server.cle_courante.get()

        async def envoyer(message):
            envoye.append(message)

        scope = {"type": "http", "headers": [(nom.encode(), valeur.encode()) for nom, valeur in entetes]}
        asyncio.run(mcp_server.VerifierCle(application)(scope, None, envoyer))
        statut = envoye[0]["status"] if envoye else 200
        return statut, recu.get("cle")

    def test_cle_dans_x_api_key_acceptee(self):
        self.assertEqual(self.appeler([("x-api-key", "a" * 40)]), (200, "Token " + "a" * 40))

    def test_cle_dans_authorization_toujours_acceptee(self):
        self.assertEqual(self.appeler([("authorization", "Token " + "b" * 40)]), (200, "Token " + "b" * 40))

    def test_sans_cle_refuse(self):
        self.assertEqual(self.appeler([]), (401, None))


class OrdreDuFichierTests(SimpleTestCase):
    """Le serveur démarre à la ligne « if __name__ == '__main__' » : tous les outils doivent être déclarés AVANT."""

    def test_demarrage_apres_tous_les_outils(self):
        from pathlib import Path
        lignes = (Path(__file__).resolve().parent.parent / "mcp_server.py").read_text(encoding="utf-8").splitlines()
        demarrage = next(i for i, l in enumerate(lignes) if l.startswith("if __name__"))
        outils = [i for i, l in enumerate(lignes) if l.startswith("@mcp.tool()")]
        self.assertEqual(len(outils), 8)   # 7 − preparer_envoi + fabriquer_video + modeles_video
        self.assertGreater(demarrage, max(outils))



@unittest.skipUnless(MCP_INSTALLE, "paquet mcp absent (installé seulement sur le serveur)")
class ConnexionEnUnClicMcpTests(SimpleTestCase):
    def appeler(self, entetes):
        envoye, recu = [], {}

        async def application(scope, receive, send):
            recu["cle"] = mcp_server.cle_courante.get()

        async def envoyer(message):
            envoye.append(message)

        scope = {"type": "http", "headers": [(n.encode(), v.encode()) for n, v in entetes]}
        asyncio.run(mcp_server.VerifierCle(application)(scope, None, envoyer))
        return envoye, recu.get("cle")

    def test_jeton_bearer_transmis_tel_quel(self):
        _, cle = self.appeler([("authorization", "Bearer " + "j" * 40)])
        self.assertEqual(cle, "Bearer " + "j" * 40)

    def test_401_indique_le_serveur_de_connexion(self):
        envoye, _ = self.appeler([])
        entetes = dict(envoye[0]["headers"])
        self.assertEqual(envoye[0]["status"], 401)
        self.assertIn(b"resource_metadata=", entetes[b"www-authenticate"])


# ---------- Lot 2 : outils fabriquer_video / modeles_video, correction d'envoyer_video ----------
# Le paquet mcp n'est installé que sur le serveur : sur le PC, le connecteur est chargé avec de petites doublures
# (FastMCP, anyio, uvicorn) pour tester quand même ses outils.

def charger_connecteur():
    if MCP_INSTALLE:
        return mcp_server
    import importlib.util as outils_import
    import sys
    import types
    from pathlib import Path

    class FauxFastMCP:
        def __init__(self, *args, **kwargs):
            self.outils = {}

        def tool(self):
            def declarer(fonction):
                self.outils[fonction.__name__] = fonction
                return fonction
            return declarer

        def streamable_http_app(self):
            return None

    class Semaphore:
        def __init__(self, nombre):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    async def run_sync(fonction, *args):
        return fonction(*args)

    modules = {name: types.ModuleType(name) for name in
               ("mcp", "mcp.server", "mcp.server.fastmcp", "anyio", "anyio.to_thread", "uvicorn")}
    modules["mcp.server.fastmcp"].FastMCP = FauxFastMCP
    modules["anyio"].Semaphore = Semaphore
    modules["anyio.to_thread"].run_sync = run_sync
    modules["anyio"].to_thread = modules["anyio.to_thread"]
    chemin = Path(__file__).resolve().parent.parent / "mcp_server.py"
    with patch.dict(sys.modules, modules):
        spec = outils_import.spec_from_file_location("mcp_server_essai", chemin)
        module = outils_import.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class FausseReponse:
    status_code = 202

    def __init__(self, corps):
        self.corps = corps

    def json(self):
        return self.corps


class OutilsFabricationTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.connecteur = charger_connecteur()

    def appeler(self, outil, **arguments):
        jeton = self.connecteur.cle_courante.set("Token " + "a" * 40)
        try:
            return asyncio.run(getattr(self.connecteur, outil)(**arguments))
        finally:
            self.connecteur.cle_courante.reset(jeton)

    def test_huit_outils_sans_preparer_envoi(self):
        outils = {nom for nom in dir(self.connecteur) if nom in (
            "envoyer_video", "etat_video", "mes_videos", "fabriquer_voix", "etat_voix", "mon_compte",
            "fabriquer_video", "modeles_video", "preparer_envoi")}
        self.assertNotIn("preparer_envoi", outils)
        self.assertEqual(len(outils), 8)

    def test_fabriquer_video_transmet_les_champs(self):
        with patch.object(self.connecteur.requests, "post", return_value=FausseReponse({"id": 9})) as post:
            reponse = self.appeler("fabriquer_video", modele="short", script="Un.\n\nDeux.", titre="Titre",
                                   scenes=[{"type": "titre", "texte": "Un"}, {"type": "fin", "texte": "Deux"}],
                                   pour_enfants=False, contenu_ia=True)
        self.assertEqual(reponse, {"id": 9})
        self.assertTrue(post.call_args.args[0].endswith("/youtube/api/v1/fabrications/"))
        envoye = post.call_args.kwargs["json"]
        self.assertEqual((envoye["modele"], envoye["avec_ma_voix"], envoye["visibilite"]), ("short", True, "private"))
        self.assertEqual(len(envoye["scenes"]), 2)

    def test_modeles_video_lit_la_liste(self):
        with patch.object(self.connecteur.requests, "get", return_value=FausseReponse({"modeles": []})) as get:
            self.assertEqual(self.appeler("modeles_video"), {"modeles": []})
        self.assertTrue(get.call_args.args[0].endswith("/youtube/api/v1/modeles/"))

    def test_envoyer_video_par_lien_public_corrige(self):
        """T3 (bug du 31/10) : « a bytes-like object is required, not '_TemporaryFileWrapper' »."""
        def faux_telechargement(url, fichier):
            fichier.write(b"contenu de la video")
            return None

        def faux_post(url, headers=None, data=None, files=None, timeout=None):
            # Prépare la vraie requête multipart : c'est ici que l'erreur se produisait
            corps = requests.Request("POST", url, headers=headers, data=data, files=files).prepare().body
            self.assertIn(b"contenu de la video", corps)
            return FausseReponse({"id": 3, "etat": "en_attente"})

        with patch.object(self.connecteur, "telecharger", side_effect=faux_telechargement), \
                patch.object(self.connecteur.requests, "post", side_effect=faux_post):
            reponse = self.connecteur.envoyer("Token abc", "https://exemple.com/v.mp4", "Titre", "", False, False)
        self.assertEqual(reponse, {"id": 3, "etat": "en_attente"})


class AucuneFabricationLocaleTests(SimpleTestCase):
    """C4 / C6 : aucune page, aucun outil, aucun guide ne demande de fabriquer ou déposer la vidéo chez le client."""

    def test_aucune_consigne_ordinateur(self):
        import re
        from pathlib import Path
        racine = Path(__file__).resolve().parent.parent
        fichiers = [racine / "mcp_server.py", racine / "CLAUDE.md", racine / "README.md",
                    *sorted((racine / "template").rglob("*.html"))]
        motif = re.compile(r"ordinateur|npx remotion|--concurrency", re.IGNORECASE)
        trouves = [f"{f.relative_to(racine)}:{n}" for f in fichiers
                   for n, ligne in enumerate(f.read_text(encoding="utf-8").splitlines(), 1) if motif.search(ligne)]
        self.assertEqual(trouves, [])

    def test_preparer_envoi_absent_des_guides_pour_agents(self):
        from pathlib import Path
        racine = Path(__file__).resolve().parent.parent
        for chemin in ("mcp_server.py", "template/accounts/guide_claude.html", "README.md"):
            self.assertNotIn("preparer_envoi", (racine / chemin).read_text(encoding="utf-8"), chemin)

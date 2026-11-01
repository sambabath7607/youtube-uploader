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
        self.assertEqual(len(outils), 7)
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

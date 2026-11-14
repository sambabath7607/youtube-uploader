import signal
import threading
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from youtube_uploader.envois import envoyer, marquer_envois_interrompus, prendre_prochaine_video, taches_periodiques
from youtube_uploader.fabrication import suivre_fabrications

INTERVALLE_TACHES = 3600         # nettoyage, règle des 30 jours et sauvegarde : vérifiés toutes les heures
INTERVALLE_FABRICATIONS = 5      # vidéos en fabrication chez Modal : vérifiées toutes les 5 s


class Command(BaseCommand):
    help = ("Suit les vidéos en fabrication chez Modal et envoie sur YouTube les vidéos en attente, une par une "
            "(service systemd youtube-worker).")

    def add_arguments(self, parser):
        parser.add_argument("--une-fois", action="store_true", help="Traiter la file une fois puis s'arrêter.")

    def suivre_en_continu(self):
        """Fil séparé : une vidéo fabriquée est récupérée tout de suite, même pendant l'envoi YouTube d'une autre."""
        while not self.arreter:
            close_old_connections()
            suivre_fabrications()
            time.sleep(INTERVALLE_FABRICATIONS)

    def handle(self, *args, **options):
        self.arreter = False
        # systemctl stop / restart : on termine la vidéo en cours avant de s'arrêter
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "arreter", True))
        marquer_envois_interrompus()
        if options["une_fois"]:
            suivre_fabrications()
        else:
            threading.Thread(target=self.suivre_en_continu, daemon=True).start()
        derniere_verification = 0.0
        while not self.arreter:
            close_old_connections()
            if not options["une_fois"] and time.monotonic() - derniere_verification > INTERVALLE_TACHES:
                taches_periodiques()
                derniere_verification = time.monotonic()
            video = prendre_prochaine_video()
            if video:
                envoyer(video)
            elif options["une_fois"]:
                break
            else:
                time.sleep(5)

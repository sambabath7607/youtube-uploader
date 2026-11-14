from django.core.management.base import BaseCommand, CommandError

from youtube_uploader.exploitation import sauvegarde_quotidienne, verifier_sauvegarde


class Command(BaseCommand):
    help = ("Copie la base tout de suite (comme la sauvegarde quotidienne du worker), la vérifie, et l'envoie hors du "
            "serveur si SAUVEGARDE_HORS_SERVEUR=modal.")

    def handle(self, *args, **options):
        copie = sauvegarde_quotidienne(forcer=True)
        if copie is None:
            self.stderr.write("Sauvegarde impossible : Samba a reçu une alerte (détail : journal du serveur).")
            return
        try:
            resultat = verifier_sauvegarde(copie)
        except ValueError as e:
            raise CommandError(f"Copie faite mais NON restaurable : {e}")
        self.stdout.write(f"Copie faite et vérifiée : {resultat['fichier']} ({resultat['taille_mo']} Mo, "
                          f"{resultat['comptes']} comptes, {resultat['videos']} vidéos).")

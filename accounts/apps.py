from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = 'accounts'

    def ready(self):
        from . import signaux  # noqa: F401  (compteur des connexions Google)

from django.apps import AppConfig


class LoginHermineConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'login_hermine'

    def ready(self) -> None:
        # connect signals
        __import__("login_hermine.signals")

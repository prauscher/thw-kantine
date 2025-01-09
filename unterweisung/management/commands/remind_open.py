import argparse
from collections.abc import Callable

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q, QuerySet

from kantine.hermine import get_hermine_client
from unterweisung import models


class Command(BaseCommand):
    help = "Lade die Liste der Teilnehmenden mit offenen Unterweisungen"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.actions = [
            ("list", "Ausgabe auf Stdout", self.action_list),
            ("hermine", "Schicke eine Erinnerung per Hermine", self.action_hermine),
        ]

    def action_list(self, **kwargs) -> Callable[[models.Teilnehmer, QuerySet[models.Unterweisung]], None]:
        def _action(teilnehmer: models.Teilnehmer,
                    unterweisungen: QuerySet[models.Unterweisung]) -> None:
            self.stdout.write(f"{teilnehmer}: {', '.join(str(unterweisung) for unterweisung in unterweisungen)}")
        return _action

    def action_hermine(self, hermine_text: str, **kwargs) -> Callable[[models.Teilnehmer, QuerySet[models.Unterweisung]], None]:
        if not hermine_text:
            raise CommandError("Eine Textvorlage muss als --hermine-text angegeben werden.")

        hermine_client = get_hermine_client()

        if not hermine_client:
            raise CommandError("Konnte Hermine-Client initialisieren.")

        def _action(teilnehmer: models.Teilnehmer,
                    unterweisungen: QuerySet[models.Unterweisung]) -> None:
            if not teilnehmer.fullname:
                self.stderr.write(self.style.WARNING(
                    f"Konnte keinen vollen Namen für {teilnehmer.username} finden."))
                return

            # surname may not contain spaces in our NextCloud
            fullname = teilnehmer.fullname.replace("_", " ")

            users = hermine_client.search_user(f"{fullname} (OV Darmstadt)")
            if not users:
                self.stderr.write(self.style.WARNING(
                    f"Konnte {fullname} nicht in Hermine finden."))
                return

            conversation = hermine_client.open_conversation(users)
            hermine_client.send_msg_to_user(
                conversation["id"],
                hermine_text.format(fullname=fullname,
                                    unterweisungen=", ".join(str(unterweisung)
                                                             for unterweisung in unterweisungen))
            )

        return _action

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--hermine-text", type=str, default="",
            help="Vorlage der Hermine-Nachricht. {fullname} wird durch den Nam"
                 "en, {unterweisungen} durch eine Kommaseparierte Liste der of"
                 "fenen Unterweisungen ersetzt.")
        parser.add_argument(
            "--filter-username", type=str, default=None,
            help="Nutze nur Teilnehmende mit diesem Benutzername")
        parser.add_argument(
            "--filter-gruppe", type=str, default=None,
            help="Nutze nur Teilnehmende aus dieser Gruppe")
        parser.add_argument(
            "--action", choices=[name for name, _, _ in self.actions],
            default=self.actions[0][0],
            help=f"Welche Aktion für die Teilnehmenden ausgeführt werden soll: "
                 f"{'; '.join(f'{key} - {help}' for key, help, _ in self.actions)}. "
                 f"Standard: %(default)s")

    def handle(self, *args, action: str, filter_username: str | None,
               filter_gruppe: str | None, **kwargs) -> None:
        action_handler = next(handler
                              for name, _, handler in self.actions
                              if name == action)(**kwargs)

        search_filter = (
            Q(teilnahmen__abgeschlossen_at__isnull=True) &
            Q(teilnahmen__unterweisung__active=True)
        )

        if filter_username is not None:
            search_filter &= Q(username=filter_username)

        if filter_gruppe is not None:
            search_filter &= Q(gruppe=filter_gruppe)

        delinquents = models.Teilnehmer.objects.filter(search_filter)

        for teilnehmer in delinquents:
            open_unterweisungen = models.Unterweisung.objects.filter(
                teilnahmen__abgeschlossen_at__isnull=True,
                active=True,
                teilnahmen__teilnehmer=teilnehmer,
            )

            action_handler(teilnehmer, open_unterweisungen)

# Installation
1. Datenbank mittels Umgebungsvariable angeben z.B. `DB_NAME=./database.sqlite`
2. Migration ausführen `python manage.py migrate`
3. Server ausführen `python manage.py runserver localhost:8000`
4. Auf http://localhost:8000 gehen und ausprobieren

# Offene Aufgaben / TODOs
- Stornierungsmöglichkeit -> Auf null setzen geht doch?
- Ausgabe markieren (später ggf. inkl Bezahlung)
- Neue Buchung unterhalb wenn obere Ressource gebucht?
- Tags (Laut / Leise)

- ResourceManager: Funktion, Voting Group, Recursive
 - Inform?
- Vote: ResourceUsage, User, Comment, Approval / Reject
 - Voting Group: Abgelehnt wenn eine Ablehnung; Zugestimmt wenn eine Zustimmung; Offen sonst

- Genauen Zeitraum bei mehrtägigen Terminen irgendwo anzeigen
- Infotext je Ressource (0,5to Anhänger)
- Vorabfrage Verfügbarkeit in Unterweisung?

## Hermine Anbindung
- Ankündigung in Kantine
- Nachricht an Bestellenden
  - Bestellung aufgegeben/aktualisiert/storniert
- Nachricht an Kochenden
  - Stärkeänderung

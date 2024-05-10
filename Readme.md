# Installation
1. Datenbank mittels Umgebungsvariable angeben z.B. `DB_NAME=./database.sqlite`
2. Migration ausführen `python manage.py migrate`
3. Server ausführen `python manage.py runserver localhost:8000`
4. Auf http://localhost:8000 gehen und ausprobieren

# Offene Aufgaben / TODOs
- Stornierungsmöglichkeit -> Auf null setzen geht doch?
- Ausgabe markieren (später ggf. inkl Bezahlung)

## Hermine Anbindung
- Ankündigung in Kantine
- Nachricht an Bestellenden
  - Bestellung aufgegeben/aktualisiert/storniert
- Nachricht an Kochenden
  - Stärkeänderung

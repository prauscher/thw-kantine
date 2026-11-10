# Installation
1. Datenbank mittels Umgebungsvariable angeben z.B. `DB_NAME=./database.sqlite`
2. Migration ausführen `python manage.py migrate`
3. Server ausführen `python manage.py runserver localhost:8000`
4. Auf http://localhost:8000 gehen und ausprobieren

# Strichliste
Erreichbar unter `/strichliste/`. Beim ersten Aufruf wählt man sein Konto aus der alten Strichliste aus oder legt ein neues an.
Mit Nextcloud-Login bucht man nur auf das eigene Konto. Bareinzahlungen und Buchungen für externe Personen
laufen über das Theken-Tablet unter `/strichliste/tablet/<PIN>/`.
Ausgabe-Buttons, Tags und Konten werden im Django-Admin gepflegt.

Einstellungen in den Django-Settings oder per Umgebungsvariable:
- `STRILI_TABLET_PIN`: PIN in der Tablet-URL, ohne Wert gibt es keinen Tablet-Zugang
- `STRILI_TRANSFERS`: Überweisungen zwischen Konten erlauben (Standard: aus)
- `STRILI_PAYPAL_LINK`: Ziel des QR-Codes unter `/strichliste/paypal`, Gutschriften bucht ein separates Skript
- `STRILI_WARN_BELOW` (−4000), `STRILI_HARD_LIMIT` (−20000): Warnschwelle und Untergrenze in Cent
- `STRILI_UNDO_MINUTES` (5), `STRILI_TABLET_IDLE_SECONDS` (30), `STRILI_STALE_DAYS` (100)
- `STRILI_DEPOSIT_STEPS` (`10,50,100,200,500,1000`): Einzahlungs-Buttons in Cent

## Übernahme der alten Strichliste
Einmalig in die leere Datenbank:

```
STRILI_IMPORT_AUTH=benutzer:passwort ./manage.py strichliste_import --dry-run
STRILI_IMPORT_AUTH=benutzer:passwort ./manage.py strichliste_import
```

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
- Reservierung: Koppeln mit Stein (Einsatz / Werkstatt)

## Hermine Anbindung
- Ankündigung in Kantine
- Nachricht an Bestellenden
  - Bestellung aufgegeben/aktualisiert/storniert
- Nachricht an Kochenden
  - Stärkeänderung

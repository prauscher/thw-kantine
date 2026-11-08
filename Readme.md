# Installation
1. Datenbank mittels Umgebungsvariable angeben z.B. `DB_NAME=./database.sqlite`
2. Migration ausführen `python manage.py migrate`
3. Server ausführen `python manage.py runserver localhost:8000`
4. Auf http://localhost:8000 gehen und ausprobieren

# Strichliste
Erreichbar unter `/strichliste/`. Das Konto hängt am Nextcloud-Login und wird beim ersten Aufruf angelegt.
Externe Personen ohne Nextcloud-Konto legt jeder unter „Theke & Externe“ an, sie sind überall als EXTERN gekennzeichnet.
Ausgabe-Buttons, Tags und Konten werden im Django-Admin gepflegt.

Einstellungen per Umgebungsvariable:
- `STRICHLISTE_TABLET_PIN`: Theken-Tablet unter `/strichliste/tablet/<PIN>/`, ohne Wert gibt es keinen Tablet-Zugang
- `STRICHLISTE_TRANSFERS`: Überweisungen zwischen Konten erlauben (Standard: aus)
- `STRICHLISTE_PAYPAL_LINK`: Ziel des QR-Codes unter „Mit PayPal aufladen“, Gutschriften bucht ein separates Skript
- `STRICHLISTE_WARN_BELOW` (−4000), `STRICHLISTE_HARD_LIMIT` (−20000): Warnschwelle und Untergrenze in Cent
- `STRICHLISTE_UNDO_MINUTES` (5), `STRICHLISTE_TABLET_IDLE_SECONDS` (30), `STRICHLISTE_STALE_DAYS` (100)
- `STRICHLISTE_DEPOSIT_STEPS` (`10,50,100,200,500,1000`): Einzahlungs-Buttons in Cent

## Übernahme der alten Strichliste
Einmalig in die leere Datenbank, bevor sich jemand anmeldet:

```
STRICHLISTE_IMPORT_AUTH=benutzer:passwort ./manage.py strichliste_import --dry-run
STRICHLISTE_IMPORT_AUTH=benutzer:passwort ./manage.py strichliste_import
```

Übernommene Konten werden beim ersten Nextcloud-Login mit exakt gleichem Namen automatisch verknüpft,
der Rest wird im Django-Admin zugeordnet (Art und Benutzername setzen) oder als extern geführt.

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

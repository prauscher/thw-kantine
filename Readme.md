# Installation
1. Datenbank mittels Umgebungsvariable angeben z.B. `DB_NAME=./database.sqlite`
2. Migration ausführen `python manage.py migrate`
3. Server ausführen `python manage.py runserver localhost:8000`
4. Auf http://localhost:8000 gehen und ausprobieren

# Strichliste
Erreichbar unter `/strichliste/`. Das Konto hängt am Nextcloud-Login und wird beim ersten Aufruf angelegt.
Externe Personen ohne Nextcloud-Konto legt jeder unter „Theke & Externe“ an, sie sind überall als EXTERN gekennzeichnet.

- `STRICHLISTE_ADMINS`: kommagetrennte Nextcloud-Benutzernamen mit Zugriff auf die Verwaltung (Konten, Tags, Tablets, Einstellungen)
- Theken-Tablet: in der Verwaltung unter „Theken-Tablets“ einen Zugang mit PIN anlegen und die Adresse einmal auf dem Tablet öffnen.
  Nach der PIN bleibt das Gerät dauerhaft angemeldet. Sperren oder „Alle Geräte abmelden“ macht den Zugang ungültig.
- Ausgabe-Buttons (z.B. „Getränke“ für 1,10 €) werden in der Verwaltung angelegt, benannt und sortiert.
- Überweisungen zwischen Konten sind standardmäßig aus und lassen sich unter Einstellungen einschalten.
- PayPal: unter Einstellungen den Link für den QR-Code eintragen. Gutschriften bucht ein separates Skript.

## Testbetrieb und Übernahme der alten Strichliste
Nach der Installation enthält die Strichliste Spieldaten (Benutzernamen `spiel-…`), auf allen Seiten steht ein Hinweis auf den Testbetrieb.
Nach dem Testen wird die bestehende Strichliste in einem Schritt übernommen:

```
STRICHLISTE_IMPORT_AUTH=benutzer:passwort ./manage.py strichliste_import --dry-run
STRICHLISTE_IMPORT_AUTH=benutzer:passwort ./manage.py strichliste_import
```

Dabei werden alle Konten und Buchungen aus dem Testbetrieb gelöscht (Tags, Ausgabe-Buttons, Tablets und Einstellungen bleiben), die Konten mit ihrem Saldo übernommen
und der Testbetrieb beendet. Übernommene Konten werden beim ersten Nextcloud-Login mit exakt gleichem Namen automatisch verknüpft,
der Rest wird in der Verwaltung zugeordnet oder als extern geführt. Die alte Strichliste sollte ab dem Import nicht mehr benutzt werden.

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

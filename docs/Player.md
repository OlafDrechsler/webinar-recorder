# Anleitung: Tool „Player"

Der Player spielt eine fertige Aufnahme ab – **System-Ton als Taktgeber**, Mikro-Segmente
synchron eingemischt, und zu jedem Zeitpunkt die passende Folie. Er ist zugleich das
Werkzeug für den **Feinschliff** (kürzen, Notizen, Screenshots einfügen).

Öffnen: Hub → **Player** → **Ordner wählen…** → den Aufnahme-Ordner (`Webinar_…`) wählen.

## Wiedergabe

- **Play/Pause**, **10 s zurück**, **10 s vor**.
- **Tempo:** Wiedergabegeschwindigkeit.
- **Lautstärke** / Stumm.
- **System:** und **Mikro:** zeigen die eingemischten Tonspuren, **Folie:** den Dateinamen
  der aktuell gezeigten Folie.

## Filmstreifen (unten)

Zeigt alle Folien mit **Name und Zeit** (mm:ss). Klick auf eine Folie springt an diese
Stelle.

### Tastatur

- **← / →** – eine Folie zurück/vor.
- **Pos1 / Ende** – zur ersten/letzten Folie.
- **Umschalt + ← / →** (bzw. Pos1/Ende) – Auswahl-Bereich aufziehen/erweitern.
- **Strg-Klick / Umschalt-Klick** – mehrere Folien markieren.
- **Esc** – Mehrfachauswahl wieder aufheben.
- **Entf** – markierte (bzw. aktuelle) Folie **aussortieren** (nach `_aussortiert`
  verschieben).
- **Umschalt + Entf** – endgültig **löschen**.

## Rechtsklick auf eine Folie

- **Bearbeiten** – öffnet die Folie im Editor (siehe unten).
- **Aufnahme ab hier verwerfen** – schneidet das **Ende** ab dieser Stelle weg (Folien, Ton
  und Mikro-Segmente danach). Mit Sicherheitsabfrage.
- **Anfang bis hier verwerfen** – schneidet den **Anfang** bis zu dieser Stelle weg; die
  restlichen Folien und Mikro-Segmente werden auf den neuen Nullpunkt umnummeriert, der Ton
  vorne gekürzt. Mit Sicherheitsabfrage.
- **Aussortieren / Löschen** – einzelne Folie entfernen.

Der **Notiz**-Button macht dasselbe wie „Bearbeiten" für die gerade gezeigte Folie.

## Editor (Arbeitsbereich)

Werkzeugleiste: **Textmarker**, **Stift**, **Text**, **Radierer**, **Einfügen**,
**Speichern**. Jedes Zeichenwerkzeug hat ein Aufklappmenü für Dicke/Größe und Farbe.

- **Screenshot einfügen** – Bild in die Zwischenablage kopieren (z. B. Snipping Tool), dann
  im Editor **Strg + V** drücken oder **Einfügen** klicken. Verhalten:
  - Ist der Screenshot **größer** als die Folie, wird er automatisch verkleinert, bis er
    vollständig sichtbar ist (Seitenverhältnis bleibt erhalten).
  - Ist er **kleiner**, wird er in Originalgröße eingefügt.
  - Am Anfasser unten rechts **proportional vergrößern/verkleinern**, an der Fläche
    **verschieben**, mit dem **×** oben rechts wieder entfernen.
- **Speichern** brennt alle Objekte (Striche, Text, eingefügte Bilder) fest ins PNG ein und
  aktualisiert den Filmstreifen.

Siehe auch: [Zusammenspiel der Tools](Workflow.md).

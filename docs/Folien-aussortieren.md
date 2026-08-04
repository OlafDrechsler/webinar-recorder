# Anleitung: Tool „Folien aussortieren"

Dieses Tool entfernt **nachträglich Duplikate und Fast-Duplikate** aus großen Bildmengen.
Das passiert typischerweise, wenn beim Aufnehmen ein bewegter Bereich mit im Bild war –
z. B. ein **Chat**, eine **Uhr** oder das **Sprecher-Video** – sodass sich die Folie
scheinbar ständig „geändert" hat und viel zu viele Bilder gespeichert wurden.

Die Idee: Man markiert den ständig wechselnden Bereich als **Ignorierbereich**. Danach
werden nur noch Folien als verschieden gewertet, die sich **außerhalb** dieses Bereichs
unterscheiden.

Öffnen: Hub → **Folien aussortieren** → **Folienordner wählen** (der `folien`-Ordner der
Aufnahme).

## 1. Ignorierbereich markieren

- Blättere mit **‹ vorheriges** / **nächstes ›** durch die Referenzbilder.
- Ziehe über den bewegten Bereich einen **Rechteck**- oder **Ellipse**-Bereich auf.
- **Modus: Ignorierbereich** – dieser Bereich wird beim Vergleich ausgeblendet
  (Normalfall). Alternativ **Vergleichsbereich**, wenn du umgekehrt nur einen kleinen
  Ausschnitt vergleichen willst.
- **Letzten Bereich entfernen** / **Alle löschen** korrigieren die Markierung.
- **Empfindlichkeit** stellt ein, wie stark sich zwei Bilder unterscheiden müssen, um als
  verschieden zu gelten.
- **Maske speichern… / laden…** – die Bereiche als Vorlage sichern und bei ähnlichen
  Aufnahmen wiederverwenden.

## 2. Probelauf

- **Behalten** / **Verwerfen**, Geschwindigkeit **langsam ↔ schnell**, **Pause** – lässt den
  Vergleich durchlaufen und **markiert** die gefundenen Doubletten, ohne schon etwas zu
  verändern. Verglichen wird immer gegen das zuletzt *behaltene* Bild; das erste Bild einer
  Serie bleibt immer.

## 3. Aktion ausführen

- **Aktion: Aussortieren (verschieben)** – die markierten Bilder wandern in den Unterordner
  `_aussortiert` (umkehrbar).
- **Aktion: Endgültig löschen** – unwiderruflich (mit Abfrage).
- **Aktion ausführen (n)** startet die gewählte Aktion für *n* markierte Bilder.

## Filmstreifen, Rechtsklick & Tastatur

Der Filmstreifen zeigt **Name und Zeit** (mm:ss) jeder Folie.

- **Rechtsklick** auf eine Folie: **Markierung umdrehen** (Baseline ↔ Doublette), einzeln
  **Aussortieren/Löschen**, **Zeit anpassen**, sowie **Bereich ab/vor hier verwerfen**.
- **Strg-Klick / Umschalt-Klick** – mehrere Folien markieren; **Esc** hebt die Auswahl auf.
- **← / →**, **Pos1 / Ende** blättern; **Entf** = aussortieren, **Umschalt + Entf** =
  löschen.

Danach die bereinigten Folien im **Player** ansehen.

Siehe auch: [Zusammenspiel der Tools](Workflow.md).

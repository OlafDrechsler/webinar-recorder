# Anleitung: Tool „Aufnahme"

Das Aufnahme-Tool schneidet ein laufendes Webinar mit: **Ton durchgehend**, den
**Folienbereich einmal pro Sekunde** – aber ein Bild wird nur gespeichert, wenn sich die
Folie tatsächlich geändert hat.

Öffnen: Hub → **Aufnahme**.

## Vor dem Start

1. **Ordner wählen…** – legt fest, wohin die Aufnahme gespeichert wird. Der aktuell gewählte
   Ort steht unter **Speicherort:** (voller Pfad als Mouse-over). Beim Start entsteht darin
   ein Ordner `Webinar_<Datum>_<Zeit>`.
2. **Aufnahmebereich wählen** – ziehe ein Rechteck über den Folienbereich. Nimm nur die
   Folien, **nicht** den Chat oder das Sprecher-Video, wenn du dir das spätere Aussortieren
   sparen willst.
3. Fenster zur Seite schieben, damit es nicht mit aufgenommen wird.

## Während der Aufnahme

- **Aufnahme starten** / **Aufnahme beenden** – Start und sauberer Abschluss (siehe unten).
- **Aufnahme abbrechen** (rot) – bricht komplett ab: **keine** Ton-Verarbeitung, **nichts**
  wird gespeichert, der Ordner `Webinar_<Datum>_<Zeit>` wird gelöscht. Es kommt eine
  Sicherheitsabfrage. Nützlich, wenn die ersten Minuten unwichtig waren und du nicht auf die
  MP3-Umwandlung warten willst.
- **Bereich neu wählen** – Aufnahmebereich mitten in der Aufnahme umstellen (z. B. wenn der
  Vortragende das Fenster verschiebt).
- **Foto-Aufnahme** (AN/AUS) – schaltet das Fotografieren der Folien ab bzw. an. Bei
  Gruppendiskussion oder Vollbild-Video der Vortragenden **AUS** schalten, dann entstehen
  keine überflüssigen Bilder; der Ton läuft weiter.
- **Bild bearbeiten** – friert die aktuelle Folie ein und öffnet den Editor (Textmarker,
  Stift, Text, Screenshot einfügen), unabhängig von der weiterlaufenden Aufnahme.

## Mikrofon

- **Mikro: an / aus / auto**
  - *an* – nimmt durchgehend auf.
  - *aus* – nimmt nichts auf (nur System-Ton).
  - *auto* – sprachgesteuert: zeichnet nur auf, wenn du redest (kein riesiger Stille-Track).
- **Mikro-Pegel-Test** – prüft vor dem Start, ob das richtige Gerät reagiert; hier kannst du
  auch **Mikrofon** (Gerät) und **Schwelle** einstellen.

Die Statuszeilen unten zeigen laufend: Aufnahmezustand, gewählter Bereich, Anzahl Folien und
Mikro-Status.

## Beenden

- **Aufnahme beenden** – schließt die Aufnahme ab: der System-Ton (WAV) wird zu **MP3**
  umgewandelt und in der **Lautstärke angeglichen** (EBU R128), Mikro-Segmente werden
  eingebettet. Das kann etwas dauern.
- **Fenster schließen (X) während der Aufnahme** – es erscheint eine Abfrage:
  - **Beenden & speichern** – wie „Aufnahme beenden".
  - **Verwerfen** – wie „Aufnahme abbrechen" (Ordner wird gelöscht).
  - **Weiter aufnehmen** – Abbruch der Abfrage, Aufnahme läuft weiter.

Das Ergebnis (Ordner `Webinar_<Datum>_<Zeit>`) öffnest du danach im **Player**, oder du
bereinigst es zuerst mit **Folien zuschneiden** / **Folien aussortieren**.

Siehe auch: [Zusammenspiel der Tools](Workflow.md).

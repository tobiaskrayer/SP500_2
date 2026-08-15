"""
Gemeinsame Datei-Schreib-Helfer.

Alle JSON-Dateien des Projekts (Tages-Cache, Empfehlungs-Log, Fundamentals-Cache,
Universum-Fallback, Portfolio) werden atomar geschrieben: erst in eine temporäre
Datei im ZIELVERZEICHNIS, dann os.replace(). Bricht der Prozess mitten im Schreiben
ab (Strom weg, Actions-Timeout, Ctrl-C), bleibt die alte Datei unversehrt statt als
halbe JSON-Datei liegenzubleiben.

Wichtig: Die temporäre Datei muss im selben Verzeichnis liegen wie die Zieldatei —
os.replace ist nur innerhalb eines Dateisystems atomar und scheitert unter Windows
über Verzeichnisgrenzen hinweg.
"""

import json
import os
import tempfile


def write_json_atomic(path, data, *, indent=None, default=None) -> None:
    """
    Schreibt `data` als JSON atomar nach `path`.

    indent:  None (Default) = kompakt mit ","/":"-Trennern. Diese Dateien werden
             von Maschinen gelesen und täglich committet — Einrückung kostet nur
             Bytes in der Git-Historie.
    default: Fallback-Serialisierer (z. B. für numpy-Typen), wie bei json.dump.
    """
    path = str(path)
    dir_ = os.path.dirname(path) or "."
    os.makedirs(dir_, exist_ok=True)

    separators = None if indent is not None else (",", ":")
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=dir_, suffix=".tmp",
                                         delete=False, encoding="utf-8") as tmp:
            # Namen VOR dem Schreiben merken: scheitert json.dump (Platte voll,
            # nicht serialisierbarer Typ), muss der except-Zweig die tmp-Datei
            # noch aufräumen können.
            tmp_path = tmp.name
            json.dump(data, tmp, ensure_ascii=False, indent=indent,
                      separators=separators, default=default)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise

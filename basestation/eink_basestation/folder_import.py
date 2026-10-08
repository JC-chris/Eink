"""Importmap: prijslijst-exports van weegschaal- of kassasoftware automatisch doorsturen.

De weegschaal- of kassasoftware (of een medewerker) zet een CSV/Excel-export in de importmap,
bijvoorbeeld via een netwerkshare op het basisstation. Elke 15 seconden kijkt het basisstation of
er een nieuw bestand staat dat niet meer groeit, en stuurt het naar de cloud. De cloud gebruikt de
kolomindeling die bij de eerste (handmatige) import is bevestigd.

Na verwerking gaat het bestand naar `verwerkt/` of, bij fouten, naar `fout/`, met een
`.resultaat.txt` ernaast. Zo is in de map zelf te zien wat er gebeurd is.
"""

import logging
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .cloud import ClientFactory, Cloud, CloudError
from .config import Config

log = logging.getLogger("eink_basestation.import")

EXTENSIONS = {".csv", ".txt", ".xlsx"}
STABLE_S = 5  # bestand moet zo lang onveranderd zijn (niet halverwege het schrijven inlezen)


@dataclass
class ImportStatus:
    at: datetime
    filename: str
    ok: bool
    message: str


class FolderImporter:
    def __init__(self, config: Config, client_factory: ClientFactory, clock=time.time):
        self.config, self.client_factory, self.clock = config, client_factory, clock
        self.last: ImportStatus | None = None
        self._sizes: dict[Path, tuple[int, float]] = {}

    @property
    def directory(self) -> Path:
        return Path(self.config.import_dir)

    def ensure_dirs(self) -> None:
        for sub in ("", "verwerkt", "fout"):
            (self.directory / sub).mkdir(parents=True, exist_ok=True)

    def _ready_files(self) -> list[Path]:
        now = self.clock()
        ready = []
        for path in sorted(self.directory.iterdir()):
            if not path.is_file() or path.name.startswith((".", "~$")) or path.suffix.lower() not in EXTENSIONS:
                continue
            stat = path.stat()
            previous = self._sizes.get(path)
            self._sizes[path] = (stat.st_size, previous[1] if previous and previous[0] == stat.st_size else now)
            if previous and previous[0] == stat.st_size and now - self._sizes[path][1] >= STABLE_S:
                ready.append(path)
        return ready

    def _finish(self, path: Path, ok: bool, message: str) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.directory / ("verwerkt" if ok else "fout") / f"{stamp}_{path.name}"
        shutil.move(str(path), target)
        target.with_name(target.name + ".resultaat.txt").write_text(message + "\n", encoding="utf-8")
        self._sizes.pop(path, None)
        self.last = ImportStatus(datetime.now(), path.name, ok, message)
        (log.info if ok else log.warning)("import %s: %s", path.name, message)

    def tick(self) -> int:
        """Verwerkt klaarstaande bestanden; geeft het aantal verwerkte bestanden terug."""
        if not self.config.import_enabled or not self.config.token:
            return 0
        self.ensure_dirs()
        done = 0
        for path in self._ready_files():
            try:
                result = Cloud(self.client_factory(self.config)).import_prices(
                    path.name, path.read_bytes(), None, dry_run=False, source="folder")
            except CloudError as exc:
                if "niet bereikbaar" in str(exc):
                    log.warning("import %s uitgesteld: %s", path.name, exc)
                    continue  # later opnieuw proberen, bestand blijft staan
                self._finish(path, False, f"Geweigerd: {exc}")
                done += 1
                continue
            if result["imported"]:
                self._finish(path, True, f"{result['imported']} producten bijgewerkt, "
                                         f"{result['labels_scheduled']} labels krijgen een nieuwe prijs")
            else:
                lines = [f"regel {e['row']}: {e['message']}" if e["row"] else e["message"] for e in result["errors"][:50]]
                self._finish(path, False, "Niets geïmporteerd. " + ("; ".join(lines) or "geen geldige regels"))
            done += 1
        return done

    def run_forever(self, interval_s: float = 15) -> None:
        while True:
            try:
                self.tick()
            except OSError as exc:
                log.warning("importmap: %s", exc)
            time.sleep(interval_s)


def start_folder_importer(importer: FolderImporter) -> threading.Thread:
    t = threading.Thread(target=importer.run_forever, name="folder-import", daemon=True)
    t.start()
    return t

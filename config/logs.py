"""Generador de logs del compilador (``./log``).

Módulo del paquete ``config/``. suriaX no es solo educativo: los logs son
la base de un segundo objetivo (WIP), así que se emiten en DOS formatos a
la vez:

 - **legible por humanos, UN LOG POR ARCHIVO**: ``log/<fuente>.log``. La
   unidad de compilación es el archivo que se compila, y su log lleva TODO
   lo que produjo esa compilación — incluidos los errores de las ``.libsrx``
   que importe, cada uno con la ruta del archivo que lo contiene. Se
   **sobrescribe en cada ejecución**: el log refleja la compilación actual y
   nada más. (Antes había un único ``suriax.log`` en modo *append*, con los
   eventos de todos los archivos y de todas las corridas mezclados: ilegible
   en cuanto el proyecto tenía más de un fuente.)
 - **JSONL estructurado** (una línea JSON por evento, consumible por
   tooling): ``log/notes.jsonl`` y ``log/errors.jsonl``, globales y en
   *append* — ahí sí interesa el histórico completo. Cada evento lleva su
   ``unit`` (el fuente que se estaba compilando) para poder filtrarlo.

Categorías:

 - **NOTA** (``note``): avisos no-error con recomendación, p. ej.
   *"se está usando un .srcx como librería, se recomienda usar .libsrx"*.
 - **ERROR** (``error``): cualquier ``CompilerError`` de cualquier fase
   (léxico/sintaxis/semántica), con su código estable, ubicación y fase.

Diseño de rendimiento: los eventos se ACUMULAN en memoria y se escriben en
UN solo flush por compilación (``flush()``) — cero I/O por evento. El
frontend no conoce este módulo (se mantiene independiente de ``config/``):
``V0/main.py`` es quien puentea errores/notas hacia aquí.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, List, Optional

from .yaml_config import resolve_path

NOTES_FILE = "notes.jsonl"
ERRORS_FILE = "errors.jsonl"

#: Sufijo del log legible por unidad de compilación (``test.srcx`` ->
#: ``test.srcx.log``). Se conserva la extensión del fuente, igual que en
#: ``dumps.py`` (``<fuente>.ast.json``): así ``a.srcx`` y ``a.libsrx`` no
#: compiten por el mismo log.
HUMAN_SUFFIX = ".log"


def human_log_path(config: Optional[dict], source_path: str) -> str:
    """Ruta del log legible de ``source_path``: ``<log_dir>/<fuente>.log``."""
    logging_cfg = (config or {}).get("logging") or {}
    log_dir = resolve_path(config, logging_cfg.get("dir", "./log"))
    return os.path.join(log_dir, os.path.basename(source_path) + HUMAN_SUFFIX)


class CompilerLog:
    """Acumulador de eventos de UNA compilación; un flush al final.

    ``source_path`` es la **unidad de compilación**: da nombre al log legible
    y etiqueta los eventos del JSONL global. Sin él solo se emite el JSONL
    (no hay a qué archivo llamar al log).
    """

    __slots__ = ("log_dir", "enabled", "unit", "_notes", "_errors", "_human")

    def __init__(self, config: Optional[dict] = None, *,
                 source_path: Optional[str] = None) -> None:
        logging_cfg = (config or {}).get("logging") or {}
        self.enabled = bool(logging_cfg.get("enabled", True))
        self.log_dir = resolve_path(config, logging_cfg.get("dir", "./log"))
        self.unit = os.path.basename(source_path) if source_path else None
        self._notes: List[dict] = []
        self._errors: List[dict] = []
        self._human: List[str] = []

    # ------------------------------------------------------------------ #
    # registro de eventos
    # ------------------------------------------------------------------ #
    def note(self, code: str, message: str, *, file: Optional[str] = None,
             line: Optional[int] = None, column: Optional[int] = None,
             **extra: Any) -> None:
        """Registra una NOTA (aviso no-error con recomendación)."""
        event = self._event("note", code, message, file, line, column, extra)
        self._notes.append(event)
        self._human.append(self._human_line("NOTA", event))

    def error(self, err: Any, *, source_file: Optional[str] = None) -> None:
        """Registra un ``CompilerError`` (usa ``to_dict()`` si lo expone)."""
        if hasattr(err, "to_dict"):
            payload = err.to_dict()
        else:  # pragma: no cover - error ajeno a la jerarquía propia
            payload = {"code": "ERR???", "message": str(err)}
        event = self._event(
            "error", payload.get("code", "ERR???"), payload.get("message", ""),
            payload.get("file") or source_file,
            payload.get("line"), payload.get("column"),
            {"phase": payload.get("phase")},
        )
        self._errors.append(event)
        self._human.append(self._human_line("ERROR", event))

    def error_batch(self, errors, *, source_file: Optional[str] = None) -> None:
        for err in errors:
            self.error(err, source_file=source_file)

    # ------------------------------------------------------------------ #
    # volcado (un solo flush por compilación)
    # ------------------------------------------------------------------ #
    def flush(self) -> Optional[str]:
        """Escribe lo acumulado. Devuelve la ruta del log legible de esta
        unidad (o el directorio, si no hay unidad), o ``None`` si el logging
        está deshabilitado o no hay nada que escribir.

        El log legible se **sobrescribe**; los JSONL globales se *appendean*.
        """
        if not self.enabled or not (self._notes or self._errors):
            return None
        os.makedirs(self.log_dir, exist_ok=True)

        if self._notes:
            self._append_jsonl(os.path.join(self.log_dir, NOTES_FILE), self._notes)
        if self._errors:
            self._append_jsonl(os.path.join(self.log_dir, ERRORS_FILE), self._errors)

        written = self.log_dir
        if self.unit is not None:
            written = os.path.join(self.log_dir, self.unit + HUMAN_SUFFIX)
            # 'w': este log es el de ESTA compilacion de ESTE archivo. En
            # append acababa mezclando corridas viejas y era ilegible.
            with open(written, "w", encoding="utf-8") as fh:
                fh.write(self._header())
                fh.write("\n".join(self._human))
                fh.write("\n")

        self._notes.clear()
        self._errors.clear()
        self._human.clear()
        return written

    def _header(self) -> str:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return (f"=== suriaX — {self.unit} — {ts} "
                f"({len(self._errors)} errores, {len(self._notes)} notas) ===\n")

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _event(self, kind: str, code: str, message: str, file, line, column,
               extra) -> dict:
        event = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            # unidad de compilacion: los JSONL son globales, asi que sin esto
            # no se puede saber que compilacion produjo cada evento (el campo
            # 'file' es el del archivo con el error, que puede ser una lib).
            "unit": self.unit,
            "kind": kind,
            "code": code,
            "message": message,
            "file": file,
            "line": line,
            "column": column,
        }
        if extra:
            event.update({k: v for k, v in extra.items() if v is not None})
        return event

    @staticmethod
    def _human_line(tag: str, event: dict) -> str:
        loc = ""
        if event.get("file"):
            loc = f"  ({event['file']}"
            if event.get("line") is not None:
                loc += f":{event['line']}:{event.get('column') or 0}"
            loc += ")"
        return f"[{event['ts']}] {tag} {event['code']}: {event['message']}{loc}"

    @staticmethod
    def _append_jsonl(path: str, events: List[dict]) -> None:
        with open(path, "a", encoding="utf-8") as fh:
            for event in events:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")


__all__ = [
    "CompilerLog", "human_log_path", "NOTES_FILE", "ERRORS_FILE", "HUMAN_SUFFIX",
]

"""Reporte unificado de depuración (``--debug`` -> ``dumps/<fuente>.debug.txt``).

Módulo del paquete ``config/``: reúne EN UN SOLO archivo todo lo que las
fases ya produjeron —config y dependencias, métricas por fase, tokens,
AST-tipado, tabla de símbolos, HIR en texto y diagnósticos— para poder
adjuntarlo a un reporte de bug sin reproducir la corrida.

Diseño (mismo criterio que ``dumps.py``):

 - **cero cómputo propio**: recibe los objetos que el pipeline YA construyó
   y solo los formatea. Activar ``--debug`` no añade pasadas ni recorridos
   extra al compilador; el costo es la serialización de lo ya calculado.
 - **secciones independientes**: cada bloque se escribe si su insumo está
   disponible (``None`` = la fase no corrió). Un fallo temprano igual
   produce un reporte útil con lo que sí alcanzó a existir.
 - **texto plano estable**: pensado para `diff` entre dos corridas (misma
   razón por la que los golden de ``test/snapshot`` son texto).
"""

from __future__ import annotations

import os
import platform
import sys
from typing import Any, Dict, List, Optional

from .dumps import _target_path

_SEP = "=" * 78


class DebugReport:
    """Acumulador de secciones. El llamador (``V0/main.py``) va añadiendo lo
    que cada fase produce y al final llama :meth:`write`."""

    __slots__ = ("source_path", "config", "_sections")

    def __init__(self, source_path: str, config: Optional[dict] = None) -> None:
        self.source_path = source_path
        self.config = config
        self._sections: List[tuple] = []

    # ------------------------------------------------------------------ #
    # composición
    # ------------------------------------------------------------------ #
    def section(self, title: str, body: Any) -> "DebugReport":
        """Añade una sección con cuerpo libre (se convierte a ``str``)."""
        self._sections.append((title, body))
        return self

    def environment(self) -> "DebugReport":
        """Entorno de la corrida: intérprete, plataforma, rutas del proyecto."""
        cfg = self.config or {}
        lines = [
            f"python        : {sys.version.split()[0]} ({sys.executable})",
            f"plataforma    : {platform.system()} {platform.release()} ({platform.machine()})",
            f"fuente        : {os.path.abspath(self.source_path)}",
            f"raiz proyecto : {cfg.get('_root', '(no resuelta)')}",
            f"target        : {(cfg.get('compilation') or {}).get('target', cfg.get('target', '(defecto)'))}",
        ]
        return self.section("ENTORNO", "\n".join(lines))

    def dependencies(self, report: Optional[dict]) -> "DebugReport":
        """Estado de las dependencias externas (``check_dependencies``)."""
        if not report:
            return self
        lines = [
            f"{name:<10} {'OK ' if info['ok'] else 'FALTA'}  {info['detail']}"
            for name, info in sorted(report.items())
        ]
        return self.section("DEPENDENCIAS", "\n".join(lines))

    def metrics(self, **counts: Any) -> "DebugReport":
        """Métricas del pipeline (tokens, items, símbolos, hooks...)."""
        lines = [f"{k:<22} {v}" for k, v in counts.items() if v is not None]
        return self.section("METRICAS", "\n".join(lines))

    def timings(self, times: Optional[Dict[str, float]]) -> "DebugReport":
        """Tiempos por fase (los mismos que imprime ``--time``)."""
        if not times:
            return self
        total = sum(times.values())
        lines = [f"{name:<16} {secs * 1000:9.3f} ms" for name, secs in times.items()]
        lines.append(f"{'TOTAL':<16} {total * 1000:9.3f} ms")
        return self.section("TIEMPOS POR FASE", "\n".join(lines))

    def tokens(self, tokens: Optional[List]) -> "DebugReport":
        if not tokens:
            return self
        body = "\n".join(f"[{i:>4}] {tok!r}" for i, tok in enumerate(tokens))
        return self.section(f"TOKENS ({len(tokens)})", body)

    def ast(self, program: Optional[Any]) -> "DebugReport":
        if program is None:
            return self
        from include.ast_json import to_json  # el frontend ya esta en sys.path
        return self.section(
            f"AST-TIPADO ({len(program.items)} items)", to_json(program),
        )

    def symbols(self, table: Optional[Any]) -> "DebugReport":
        if table is None:
            return self
        from include.ast_json import to_json
        from src.frontend.semantic.symbol_table import to_debug_dict
        return self.section("TABLA DE SIMBOLOS", to_json(to_debug_dict(table)))

    def hir_text(self, text: Optional[str]) -> "DebugReport":
        if not text:
            return self
        return self.section("HIR (texto protobuf)", text)

    def diagnostics(self, title: str, errors: Optional[List]) -> "DebugReport":
        if not errors:
            return self
        body = "\n".join(f"{e.code}: {e.message}  ({e.loc})" for e in errors)
        return self.section(f"{title} ({len(errors)})", body)

    def trace(self, lines: Optional[List[str]]) -> "DebugReport":
        """Traza de ejecución del intérprete (``--trace-exec``)."""
        if not lines:
            return self
        return self.section(f"TRAZA DE EJECUCION ({len(lines)} eventos)",
                            "\n".join(lines))

    # ------------------------------------------------------------------ #
    # salida
    # ------------------------------------------------------------------ #
    def render(self) -> str:
        parts: List[str] = [
            _SEP,
            f" REPORTE DE DEPURACION — {os.path.basename(self.source_path)}",
            _SEP,
        ]
        for title, body in self._sections:
            parts.append(f"\n{_SEP}\n {title}\n{_SEP}")
            parts.append(str(body))
        return "\n".join(parts) + "\n"

    def write(self, *, out_path: Optional[str] = None) -> str:
        """Escribe el reporte y devuelve la ruta. Una sola llamada de I/O."""
        target = _target_path(self.config, self.source_path, ".debug.txt",
                              out_path)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(self.render())
        return target


__all__ = ["DebugReport"]

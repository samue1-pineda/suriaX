"""API general para cargar y llamar módulos C++ generados con pybind11.

Punto de entrada ÚNICO del runtime hacia cualquier módulo nativo. No está
acoplada a ningún módulo concreto: descubre las bibliotecas compiladas bajo
``runtime/<modulo>/build`` (p. ej. ``logic_mem/build/memory_c*.so``), las
carga y las cachea.

El primer consumidor es el backend de memoria real (`memory_c`), pero la VM
de bytecode/JIT y el backend LLVM IR/WASM usarán exactamente la misma API::

    from runtime.cxx_api import api

    mem = api.load("memory_c")     # módulo envuelto y cacheado
    print(mem.banner())            # acceso por atributo
    api.call("memory_c", "banner") # o llamada explícita
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType
from typing import Any


class CxxModule:
    """Envoltura ligera sobre un módulo nativo (pybind11) ya cargado.

    Permite invocar sus funciones por nombre (`call`) o por acceso a atributo
    (`mod.func(...)`), delegando siempre en el módulo real subyacente.
    """

    def __init__(self, name: str, module: ModuleType) -> None:
        self.name = name
        self._module = module

    @property
    def raw(self) -> ModuleType:
        """El objeto módulo nativo sin envolver."""
        return self._module

    def has(self, symbol: str) -> bool:
        return hasattr(self._module, symbol)

    def call(self, function_name: str, *args: Any, **kwargs: Any) -> Any:
        fn = getattr(self._module, function_name, None)
        if fn is None:
            raise AttributeError(
                f"El módulo nativo '{self.name}' no expone '{function_name}'"
            )
        if not callable(fn):
            raise TypeError(f"'{self.name}.{function_name}' no es invocable")
        return fn(*args, **kwargs)

    def __getattr__(self, item: str) -> Any:
        # Sólo se invoca si `item` no está en el __dict__ de la instancia.
        try:
            return getattr(self._module, item)
        except AttributeError as exc:
            raise AttributeError(
                f"El módulo nativo '{self.name}' no expone '{item}'"
            ) from exc

    def __repr__(self) -> str:
        return f"<CxxModule {self.name!r}>"


class CxxAPI:
    """Cargador/registro de módulos C++ compilados con pybind11.

    Busca las bibliotecas nativas en un conjunto de directorios candidatos
    (por defecto, cada ``runtime/<modulo>/build``) y cachea los módulos ya
    cargados para no repetir el trabajo de importación.
    """

    def __init__(self, search_dirs: Iterable[Path | str] | None = None) -> None:
        self._cache: dict[str, CxxModule] = {}
        self._extra_dirs: list[Path] = [Path(d) for d in (search_dirs or ())]

    # -- resolución de rutas -------------------------------------------------
    def add_search_dir(self, directory: Path | str) -> None:
        """Registra un directorio extra donde buscar módulos nativos."""
        self._extra_dirs.insert(0, Path(directory))

    def _candidate_dirs(self) -> list[Path]:
        base = Path(__file__).resolve().parent  # .../runtime
        dirs = [
            *self._extra_dirs,
            *sorted(base.glob("*/build")),  # runtime/<modulo>/build
            base / "build",
            base,
            Path(sys.prefix) / "lib",
        ]
        seen: set[Path] = set()
        ordered: list[Path] = []
        for directory in dirs:
            resolved = directory.resolve()
            if resolved not in seen:
                seen.add(resolved)
                ordered.append(directory)
        return ordered

    # -- carga ---------------------------------------------------------------
    def load(self, module_name: str) -> CxxModule:
        """Carga (o recupera de caché) un módulo nativo por nombre."""
        cached = self._cache.get(module_name)
        if cached is not None:
            return cached

        wrapped = CxxModule(module_name, self._import(module_name))
        self._cache[module_name] = wrapped
        return wrapped

    def _import(self, module_name: str) -> ModuleType:
        if importlib.util.find_spec(module_name) is not None:
            return importlib.import_module(module_name)

        for directory in self._candidate_dirs():
            if not directory.exists():
                continue
            path_str = str(directory)
            if path_str not in sys.path:
                sys.path.insert(0, path_str)
            if importlib.util.find_spec(module_name) is not None:
                return importlib.import_module(module_name)

        raise ImportError(
            f"No se pudo cargar el módulo nativo '{module_name}'. "
            "Comprueba que el .so/.pyd exista y que se haya compilado con el "
            "mismo intérprete de Python que estás usando para importarlo."
        )

    # -- invocación ----------------------------------------------------------
    def call(
        self, module_name: str, function_name: str, *args: Any, **kwargs: Any
    ) -> Any:
        """Atajo: carga el módulo y llama a una de sus funciones."""
        return self.load(module_name).call(function_name, *args, **kwargs)

    def __getitem__(self, module_name: str) -> CxxModule:
        return self.load(module_name)


# Instancia global compartida por todo el runtime.
api = CxxAPI()


if __name__ == "__main__":
    # Smoke-test: importa la API, carga el backend de memoria y muestra su
    # mensaje de confirmación. Prueba de vida del puente pybind11.
    memory = api.load("memory_c")
    print(memory.banner())

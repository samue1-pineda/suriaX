"""El ÍNDICE de un archivo: lo que un editor necesita para hover, ir a la
definición y completar.

Es un volcado de lo que la Semántica ya sabe, sin volver a calcular nada:

- ``table.scopes`` guarda TODOS los scopes (con su padre y de quién son),
  así que cada local sigue ahí después del análisis;
- ``table.uses`` guarda, de cada símbolo, dónde se USA — lo anota quien
  resuelve el nombre, que es el único que sabe a cuál de dos ``x`` apunta;
- los miembros de un struct, las variantes de un enum y los métodos
  (``table.dunders``) dicen qué va después de un ``.``.

Un símbolo de una LIBRERÍA lleva su archivo: ir a la definición de
``vec.make`` abre ``lib/array/vector.libsrx``.

Límite conocido: un local se ubica por su FUNCIÓN, no por su bloque (los
nodos del árbol no guardan dónde terminan). Completar ofrece lo declarado
antes del cursor en la misma función; un nombre de un bloque ya cerrado
también aparece.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from include import ast_nodes as ast
from include.ast_walk import walk

from .symbol_table import ScopeKind, Symbol, SymbolKind, SymbolTable

#: versión de la FORMA de este JSON (súbela si cambia)
INDEX_VERSION = 1


def build_index(program: ast.Program, table: SymbolTable, *, path: str,
                source: str, libraries: Optional[dict] = None) -> dict:
    """``{symbols, references, members}`` del archivo ``path``."""
    builder = _Builder(table, path, source, libraries or {})
    builder.run(program)
    return {
        "index_version": INDEX_VERSION,
        "symbols": builder.symbols,
        "references": builder.references,
        "members": builder.members,
    }


class _Builder:
    def __init__(self, table: SymbolTable, path: str, source: str,
                 libraries: dict) -> None:
        self.table = table
        self.path = path
        # las lineas de cada archivo, para el comentario de una declaracion (el
        # de este archivo es el buffer del editor; los de las librerias se leen
        # una vez)
        self._lines: Dict[str, List[str]] = {path: source.splitlines()}
        # alias del '#export' ('vector') -> ruta del archivo de la libreria
        self.library_files: Dict[str, str] = {}
        # (sin distinguir mayusculas: la unidad canonica puede ser 'IO' y el
        # fuente escribir 'io')
        for unit, lib_path in libraries.items():
            self.library_files.setdefault(unit.rsplit(".", 1)[-1].lower(), lib_path)
            self.library_files.setdefault(unit.lower(), lib_path)
        self.symbols: List[dict] = []
        self.references: List[dict] = []
        self.members: Dict[str, List[int]] = {}
        self._ids: Dict[int, int] = {}          # id(Symbol) -> indice
        self._seen_refs: set = set()            # (ln, col, indice) ya anotados
        self._signatures: Dict[tuple, str] = {}  # (ln, col) -> firma con nombres

    # ------------------------------------------------------------------ #
    def run(self, program: ast.Program) -> None:
        self._collect_signatures(program)
        # '#from lib #import f': el Symbol de 'f' es el DE LA LIBRERIA (su
        # posicion es alla), aunque viva en el scope de este archivo. Va
        # primero, con su archivo: el recorrido de los scopes ya no lo repite.
        # Si 'f' es un submodulo ('#from io #import stdp'), su archivo es el
        # suyo ('io/stdp.libsrx'), no la carpeta de la unidad.
        for node in program.items:
            if isinstance(node, ast.FromDirective) and node.unit:
                symbol = self.table.global_scope.values.get(node.alias or node.name)
                if symbol is not None:
                    file = (self._library_file(f"{node.unit}.{node.name}") or
                            self._library_file(node.unit))
                    self._add(symbol, file, node.lib)
        # lo declarado en este archivo: el scope global y los de cada funcion
        for scope in self.table.scopes:
            container = self._container_of(scope)
            for symbol in scope.values.values():
                self._add(symbol, self.path, container)
            for symbol in scope.types.values():
                self._add(symbol, self.path, container)
        # lo que traen los imports, con el archivo de su libreria
        for symbol in list(self.table.global_scope.values.values()):
            if symbol.kind is SymbolKind.IMPORT and symbol.members:
                self._add_library(symbol, symbol.name)
        # metodos ('x.m()'): locales y de las librerias
        for (owner, name), symbol in self.table.dunders.items():
            file = self._file_of_owner(owner)
            index = self._add(symbol, file, owner, kind="method")
            if index is not None:
                self.members.setdefault(owner, []).append(index)
        for symbol_id, uses in self.table.uses.items():
            index = self._ids.get(symbol_id)
            if index is None:
                continue
            for ln, col in uses:
                # 'a += 1' es 'a = a + 1': las dos 'a' del arbol salen del
                # mismo sitio del fuente, y el editor ve una sola
                if (ln, col, index) in self._seen_refs:
                    continue
                self._seen_refs.add((ln, col, index))
                self.references.append({"line": ln, "column": col, "symbol": index})

    # ------------------------------------------------------------------ #
    def _add(self, symbol: Symbol, file: str, container: str, *,
             kind: Optional[str] = None, with_doc: bool = True) -> Optional[int]:
        if id(symbol) in self._ids:
            return self._ids[id(symbol)]
        # un parametro de tipo ('T') se registra como un tipo opaco: no es algo
        # que se declare ni se use como un nombre corriente
        if symbol.kind is SymbolKind.TYPE and symbol.visibility == "internal" \
                and symbol.type is not None and symbol.type.name == symbol.name:
            return None
        index = len(self.symbols)
        self._ids[id(symbol)] = index
        entry = {
            "name": symbol.name,
            "kind": kind or symbol.kind.name.lower(),
            "type": _texto(symbol.type),
            "line": symbol.ln,
            "column": symbol.col,
            "file": file,
            "container": container,
        }
        detail = self._detail(symbol, file)
        if detail:
            entry["detail"] = detail
        # un parametro, o un campo escrito en la misma linea que su struct, no
        # tiene comentario propio: el de arriba es el de quien lo declara
        if with_doc and file and symbol.kind is not SymbolKind.PARAM:
            doc = self._doc_above(self._lines_of(file), symbol.ln)
            if doc:
                entry["doc"] = doc
        self.symbols.append(entry)
        # lo que va despues de un '.': los campos de un struct, las variantes
        # de un enum y los exports de un import
        if symbol.members and symbol.kind in (SymbolKind.STRUCT, SymbolKind.ENUM):
            owner = symbol.type_name or symbol.name
            for member in symbol.members.values():
                sub = self._add(member, file, owner,
                                with_doc=member.ln != symbol.ln)
                if sub is not None:
                    self.members.setdefault(owner, []).append(sub)
        return index

    def _add_library(self, import_symbol: Symbol, prefix: str) -> None:
        """Los exports de un import, con el archivo de su libreria: se busca
        por la UNIDAD (el tipo del import: 'array.vector') y, si no, por el
        nombre ('stdp', un submodulo). Si no se sabe, sin archivo: mejor que
        uno equivocado."""
        unidad = import_symbol.type.name if import_symbol.type is not None else None
        file = self._library_file(unidad or "") or self._library_file(prefix)
        for name, member in (import_symbol.members or {}).items():
            if member.kind is SymbolKind.IMPORT:
                self._add_library(member, name)
                continue
            index = self._add(member, file, prefix)
            if index is not None:
                self.members.setdefault(prefix, []).append(index)

    def _file_of_owner(self, owner: str) -> str:
        """El archivo donde se declara un tipo CANONICO: 'vector.Vector' es
        de la libreria 'vector'; 'Punto', sin unidad, de este archivo."""
        if "." not in owner:
            return self._library_file(owner) or self.path
        return self._library_file(owner.rsplit(".", 1)[0]) or self.path

    def _library_file(self, unit: str) -> str:
        return self.library_files.get(unit.lower(), "")

    def _container_of(self, scope) -> str:
        """La funcion (o el test) a la que pertenece un scope, o ''."""
        while scope is not None and scope.kind is not ScopeKind.FUNCTION:
            scope = scope.parent
        if scope is None:
            return ""
        return scope.label.split(" ", 1)[-1] if scope.label else ""

    # ------------------------------------------------------------------ #
    def _collect_signatures(self, program: ast.Program) -> None:
        """La firma de cada funcion, con los NOMBRES de sus parametros (el
        Symbol solo guarda los tipos)."""
        for node in walk(program):
            if isinstance(node, ast.FunctionDecl):
                params = ", ".join(f"{_texto(p.restype) or '?'} {p.name}"
                                   for p in node.params)
                generics = f"<{', '.join(node.type_params)}>" if node.type_params else ""
                retorno = _texto(node.return_restype) or "void"
                self._signatures[(node.ln, node.col)] = \
                    f"fn {node.name}{generics}({params}) -> {retorno}"

    def _detail(self, symbol: Symbol, file: str) -> str:
        if symbol.kind not in (SymbolKind.FUNCTION, SymbolKind.HOOK,
                               SymbolKind.DUNDER):
            return ""
        if file == self.path and (symbol.ln, symbol.col) in self._signatures:
            return self._signatures[(symbol.ln, symbol.col)]
        params = ", ".join(_texto(t) for t in (symbol.param_types or ()))
        generics = f"<{', '.join(symbol.type_params)}>" if symbol.type_params else ""
        return f"fn {symbol.name}{generics}({params}) -> {_texto(symbol.type) or 'void'}"

    def _lines_of(self, file: str) -> List[str]:
        if file not in self._lines:
            try:
                with open(file, encoding="utf-8") as fh:
                    self._lines[file] = fh.read().splitlines()
            except OSError:        # una carpeta (un paquete), o ya no esta
                self._lines[file] = []
        return self._lines[file]

    @staticmethod
    def _doc_above(lines: List[str], ln: int) -> str:
        """El comentario pegado ENCIMA de la declaracion: lineas '//' seguidas
        o un bloque '/- ... -/' que termina justo arriba."""
        i = ln - 2                       # la linea anterior, en base 0
        if i < 0 or i >= len(lines):
            return ""
        anterior = lines[i].strip()
        if anterior.endswith("-/"):
            partes = []
            while i >= 0:
                texto = lines[i].strip()
                partes.append(texto)
                if texto.startswith("/-"):
                    break
                i -= 1
            cuerpo = "\n".join(reversed(partes))
            return cuerpo[2:-2].strip() if cuerpo.startswith("/-") else ""
        partes = []
        while i >= 0 and lines[i].strip().startswith("//"):
            partes.append(lines[i].strip()[2:].strip())
            i -= 1
        return "\n".join(reversed(partes))


def _texto(t) -> str:
    return "" if t is None else f"{t!r}"


__all__ = ["INDEX_VERSION", "build_index"]

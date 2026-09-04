"""Tabla de símbolos -> diagrama de clases **Mermaid** (``--dump-symbols-table``).

Proyecta la ``SymbolTable`` (post-Semántica) a un ``classDiagram`` de Mermaid,
el formato que la web de ``/documentation`` renderiza. La correspondencia:

  * ``struct``  -> una clase con sus CAMPOS (atributos) y sus MÉTODOS
    (los ``dunder``/``@impl`` y los ``hook`` cuyo dueño es ese tipo);
  * ``enum``    -> una clase ``<<enumeration>>`` con sus items;
  * ``const type`` opaco -> una clase ``<<type>>`` sin miembros;
  * un campo cuyo tipo es OTRO tipo nominal conocido -> una asociación
    ``Dueño --> TipoCampo : campo``.

La tabla, sin embargo, **no es solo tipos**. Dibujar únicamente esos dejaba
un diagrama que para un programa de funciones libres se reducía a una caja
``<<module>>``, y eso se lee mal: parece decir que la tabla de símbolos no
guarda nada más. Así que el resto de lo que la tabla sí conoce también sale:

  * las funciones libres -> ``<<module>>``;
  * las variables y constantes del ámbito global -> ``<<scope global>>``;
  * cada ``#import`` -> una caja ``<<import>>`` con **lo que esa unidad
    expone** (funciones, tipos), que es lo que explica de dónde sale
    ``println``;
  * la tabla de conversiones -> ``<<__cast__>>``, un par ``origen -> destino``
    por cada ``__cast__`` alcanzable; sin ella no se ve por qué
    ``cast<int8>(x)`` encuentra a quién llamar.

Cada caja se dibuja **solo si tiene contenido**: un programa sin importaciones
no gana una caja vacía de importaciones.

No participa de ningún camino caliente: se materializa solo cuando se pide el
volcado. No compara ``Type`` a mano ni depende del HIR (solo de la tabla).
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

try:
    from include.types_ast import Type, TypeKind
    from src.frontend.semantic.symbol_table import (Symbol, SymbolKind,
                                                    SymbolTable)
except ImportError:  # pragma: no cover - ejecucion directa
    from types_ast import Type, TypeKind  # type: ignore
    from frontend.semantic.symbol_table import (Symbol, SymbolKind,  # type: ignore
                                                SymbolTable)

# caracteres que rompen el cuerpo de una clase Mermaid; se neutralizan.
# El '~' NO entra aquí: es como Mermaid escribe un genérico ('Caja~int~'), y
# neutralizarlo era lo que impedía dibujarlos.
_UNSAFE = str.maketrans({"\n": " ", "\r": " "})
# prefijo de módulo de un nominal cualificado ('vec.Vector' -> 'Vector'): más
# legible en el diagrama y evita que el '.' confunda al parser de Mermaid.
_QUALIFIER = re.compile(r"[A-Za-z_]\w*\.")


def _fmt_type(t: Optional[Type]) -> str:
    """``Type`` -> texto seguro para Mermaid, en la notación DEL LENGUAJE.

    Postfija (``Punto ptr mutable``), como se escribe en suriaX y como la
    imprime el resto del proyecto. Antes usaba ``repr(Type)``, que es prefija
    (``ptr Punto``) "por historia del frontend": el diagrama era el único
    sitio donde un tipo se leía al revés que en el código.

    Los genéricos van con la sintaxis de Mermaid (``Caja~int~``); los
    nominales, por su nombre-HOJA, sin el módulo que los califica.
    """
    if t is None:
        return "?"
    return _QUALIFIER.sub("", _postfijo(t)).translate(_UNSAFE)


def _postfijo(t: Optional[Type]) -> str:
    """La notación postfija del lenguaje, con genéricos al estilo Mermaid."""
    if t is None:
        return "?"
    if t.kind is TypeKind.POINTER:
        return _postfijo(t.inner) + (" ptr mutable" if t.mut else " ptr")
    if t.kind is TypeKind.NULLABLE:
        return _postfijo(t.inner) + "?"
    if t.kind is TypeKind.ERROR:
        return f"error {_postfijo(t.inner)}" if t.inner is not None else "error"
    if t.kind is TypeKind.NOMINAL:
        nombre = t.name or "?"
        if not t.args:
            return nombre
        return nombre + "~" + ", ".join(_postfijo(a) for a in t.args) + "~"
    return t.kind.name.lower()


def _type_params(table: SymbolTable) -> set:
    """Los nombres que son PARÁMETROS de tipo de algún genérico.

    ``T`` en ``Caja<T>`` se registra en el scope como un tipo opaco (es lo que
    permite escribir ``T valor;`` en el cuerpo), pero **no es un tipo**: es un
    hueco. Dibujarlo como una clase inventaba una caja por cada genérico del
    programa y una flecha ``Caja --> T`` que no significa nada.
    """
    nombres = set()
    for sym in table.global_scope.types.values():
        nombres.update(getattr(sym, "type_params", ()) or ())
    return nombres


def _leaf_nominal(t: Optional[Type]) -> Optional[str]:
    """El nombre-hoja si ``t`` (o su interior de ptr/nullable) es nominal."""
    seen = 0
    while t is not None and t.kind in (TypeKind.POINTER, TypeKind.NULLABLE) \
            and seen < 8:
        t = t.inner
        seen += 1
    if t is not None and t.kind is TypeKind.NOMINAL and t.name:
        return t.name.rsplit(".", 1)[-1]
    return None


def _method_line(sym: Symbol) -> str:
    """Firma de un método para el cuerpo de la clase: ``+name(t1, t2) ret``.

    Salta el RECEPTOR (primer parámetro, el ``T ptr self``): en un diagrama de
    clases el receptor es implícito."""
    params = sym.param_types or ()
    shown = params[1:] if params else ()
    args = ", ".join(_fmt_type(p) for p in shown)
    ret = _fmt_type(sym.type)
    return f"+{sym.name}({args}) {ret}"


def _methods_by_owner(table: SymbolTable) -> Dict[str, List[str]]:
    """``owner_type (hoja) -> [líneas de método]`` desde dunders y hooks."""
    out: Dict[str, List[str]] = {}
    for (owner, _name), sym in table.dunders.items():
        out.setdefault(owner.rsplit(".", 1)[-1], []).append(_method_line(sym))
    for (owner, _kind, _name), sym in table.hooks.items():
        out.setdefault(owner.rsplit(".", 1)[-1], []).append(_method_line(sym))
    return out


def symbol_table_to_mermaid(table: SymbolTable) -> str:
    """La tabla de símbolos como un ``classDiagram`` de Mermaid (texto)."""
    types = table.global_scope.types
    methods = _methods_by_owner(table)
    parametros = _type_params(table)
    lines: List[str] = ["classDiagram"]
    relations: List[str] = []
    free_fns: List[str] = []

    for name in sorted(types):
        if name in parametros:
            continue          # es un hueco de un genérico, no un tipo
        sym = types[name]
        body: List[str] = []
        stereotype: Optional[str] = None

        if sym.kind is SymbolKind.ENUM:
            stereotype = "enumeration"
            for item in (sym.members or {}):
                body.append(item)
        elif sym.kind is SymbolKind.STRUCT:
            for fname, fsym in (sym.members or {}).items():
                body.append(f"+{_fmt_type(fsym.type)} {fname}")
                target = _leaf_nominal(fsym.type)
                if target is not None and target != name \
                        and target not in parametros:
                    relations.append(f"  {name} --> {target} : {fname}")
        elif sym.kind is SymbolKind.TYPE:
            stereotype = "type"

        body.extend(methods.get(name, ()))

        propios = getattr(sym, "type_params", ()) or ()
        titulo = f"{name}~{', '.join(propios)}~" if propios else name
        lines.append(f"  class {titulo} {{")
        if stereotype is not None:
            lines.append(f"    <<{stereotype}>>")
        for entry in body:
            lines.append(f"    {entry}")
        lines.append("  }")

    # El namespace de VALORES no es solo funciones: también trae las globales
    # y los módulos importados. Dibujar únicamente las funciones dejaba un
    # diagrama que parecía decir "la tabla de símbolos son estas dos
    # funciones", cuando la mitad de lo que hay estaba fuera del papel.
    globales: List[str] = []
    importados: List[tuple] = []
    for vname in sorted(table.global_scope.values):
        vsym = table.global_scope.values[vname]
        if vsym.kind is SymbolKind.FUNCTION:
            args = ", ".join(_fmt_type(p) for p in (vsym.param_types or ()))
            free_fns.append(f"+{vname}({args}) {_fmt_type(vsym.type)}")
        elif vsym.kind is SymbolKind.IMPORT:
            importados.append((vname, vsym))
        elif vsym.kind is SymbolKind.VAR:
            marca = "" if vsym.mutable else "const "
            globales.append(f"+{marca}{_fmt_type(vsym.type)} {vname}")

    if free_fns:
        lines.append("  class funciones {")
        lines.append("    <<module>>")
        for entry in free_fns:
            lines.append(f"    {entry}")
        lines.append("  }")

    if globales:
        lines.append("  class globales {")
        lines.append("    <<scope global>>")
        for entry in globales:
            lines.append(f"    {entry}")
        lines.append("  }")

    # Un IMPORT viaja OPACO en el HIR (sus exports viven en el .phir de su
    # propia unidad), pero la Semántica SÍ los conoce: enseñar qué trajo cada
    # uno es lo que explica de dónde salió 'println'.
    for nombre, sym in importados:
        lines.append(f"  class {nombre} {{")
        lines.append("    <<import>>")
        for miembro in sorted(sym.members or {}):
            msym = sym.members[miembro]
            if msym.kind is SymbolKind.FUNCTION:
                args = ", ".join(_fmt_type(p) for p in (msym.param_types or ()))
                lines.append(f"    +{miembro}({args}) {_fmt_type(msym.type)}")
            elif msym.kind is SymbolKind.TYPE:
                # una unidad puede exportar TIPOS (dt_variables exporta int8);
                # decir '+meta int8' no diria que 'int8' es el tipo mismo.
                lines.append(f"    +type {miembro}")
            else:
                lines.append(f"    +{_fmt_type(msym.type)} {miembro}")
        if not (sym.members or {}):
            lines.append("    (opaco: sus exports viven en su unidad)")
        lines.append("  }")

    # La tabla de CONVERSIONES: un tipo puede declarar varias, y sin ellas el
    # diagrama no explica por qué 'cast<int8>(1)' encuentra a quién llamar.
    # Van en una caja y no como flechas entre primitivos para no inventar una
    # clase por cada 'int' que aparezca en una firma.
    conversiones = []
    for origen, destino in table.casts:
        conversiones.append(f"    +cast({_fmt_type(origen)}) {_fmt_type(destino)}")
    if conversiones:
        lines.append("  class conversiones {")
        lines.append("    <<__cast__>>")
        lines.extend(sorted(set(conversiones)))
        lines.append("  }")

    lines.extend(relations)
    # Un 'classDiagram' SIN una sola clase no es un diagrama vacío para
    # Mermaid: es un error de sintaxis, y el panel se quedaba en blanco sin
    # decir por qué. Un programa que solo tiene 'fn main' es perfectamente
    # normal y merece un diagrama que se pueda mirar.
    if len(lines) == 1:
        lines.append('  class vacio["la tabla de símbolos está vacía"]')
    return "\n".join(lines) + "\n"


__all__ = ["symbol_table_to_mermaid"]

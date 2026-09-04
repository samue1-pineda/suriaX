"""Los artefactos de CADA fase, como datos, para un visualizador.

Es el cuarto canal de consulta del driver, junto a los de ``inspect.py``:
``emit_stage`` enseña UNA fase por el volcador del parser (texto, a stdout),
y esto entrega **todas** las fases a la vez y como estructuras, que es lo que
necesita una página que las muestra una al lado de otra.

Vive en el driver por el mismo motivo que las otras tres: la pregunta es del
compilador. Quién la dibuja —una página web, un editor, una terminal— es
decisión de quien llama, y por eso aquí no se genera ni una etiqueta HTML.

Cada fase se entrega **aunque las anteriores hayan fallado**, hasta donde se
pueda llegar: un programa con un error de sintaxis igual tiene tokens, y
verlos es justo lo que explica el error. Lo que no se pudo producir viaja
como ``None`` con su motivo, nunca como un artefacto vacío que parezca válido.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

from include.t_types import StringValue
from src.frontend.lexer import source_reader
from src.frontend.lexer.lexer import Lexer
from src.frontend.parser.parser import Parser


def _diag(error: Any, phase: str) -> Dict[str, Any]:
    """Un diagnóstico como dato plano, con la misma forma que el del LSP."""
    return {
        "code": getattr(error, "code", ""),
        "message": str(getattr(error, "message", error)),
        "line": getattr(error, "line", None) or getattr(error, "ln", 0) or 0,
        "column": getattr(error, "column", None) or getattr(error, "col", 0) or 0,
        "severity": getattr(error, "severity", "critical"),
        "phase": phase,
    }


def _valor(value: Any) -> str:
    """El valor de un token, en texto y **sin repr de Python**.

    Importa para las cadenas: su valor no es texto plano sino los segmentos que
    el lexer separó, y ``repr`` los enseñaba como ``Str(['x ', Interp('a')])``
    —la estructura interna del compilador— en una página que mira alguien que
    no la conoce. Aquí salen como lo que significan: ``"x " + {a}``, que es
    exactamente lo que el análisis léxico decidió partir.
    """
    if isinstance(value, StringValue):
        piezas = [json.dumps(p, ensure_ascii=False) if isinstance(p, str)
                  else "{" + p.expr + "}" for p in value.parts]
        return " + ".join(piezas) if piezas else '""'
    return str(value)


def _scopes(table) -> List[Dict[str, Any]]:
    """El ÁRBOL de scopes, tal como el resolver los abrió y cerró.

    Una tabla de símbolos no es una lista: es un árbol, y enseñar solo su
    nivel global sugiere que el compilador no sabe nada de las variables de
    dentro de una función. Sabe: las declara, las tipa y las destruye.
    """
    return [
        {
            "id": scope.sid,
            "parent": None if scope.parent is None else scope.parent.sid,
            "kind": scope.kind.name.lower(),
            "label": scope.label or "global",
        }
        for scope in table.scopes
    ]


def _simbolos(table) -> List[Dict[str, Any]]:
    """Cada símbolo de cada scope, con lo que el compilador averiguó de él.

    Incluye los MIEMBROS (campos de un struct, items de un enum, exports de
    un import) como filas con su dueño: son símbolos de pleno derecho —tienen
    tipo y posición— y viven en un sub-namespace, no en la cadena de scopes.
    """
    filas: List[Dict[str, Any]] = []

    def fila(sym, namespace: str, owner: str = "") -> Dict[str, Any]:
        # ordenados por POSICIÓN, no por el orden en que el resolver visitó
        # el árbol: en 'x = x + y' la escritura se anota después de la
        # lectura, y la lista salía saltando hacia atrás.
        usos = sorted(table.uses.get(id(sym), []))
        return {
            "name": sym.name,
            "owner": owner,
            "kind": sym.kind.name.lower(),
            "namespace": namespace,
            "type": None if sym.type is None else _postfijo_de(sym.type),
            "ln": sym.ln,
            "col": sym.col,
            "scope": sym.scope_id,
            "mutable": bool(sym.mutable),
            "uses": [{"ln": ln, "col": col} for ln, col in usos],
            # lo que solo este lenguaje sabe de un símbolo: si su valor se
            # transfirió (y dónde), qué hook es y de quién, el rango que
            # declara un tipo de librería, y sus parámetros de tipo.
            "moved_at": sym.moved_at,
            "visibility": sym.visibility,
            "hook": sym.hook_name or (
                sym.hook_kind.name.lower() if sym.hook_kind else None),
            "hook_owner": sym.hook_owner,
            "const_value": sym.const_value,
            "type_params": list(sym.type_params),
            "params": None if sym.param_types is None else
                      [_postfijo_de(t) for t in sym.param_types],
        }

    # UNA fila por símbolo, no por forma de nombrarlo: los items de un enum
    # están a la vez en el namespace global (se pueden escribir pelados) y
    # como miembros de su enum ('Color.ROJO'), y son el MISMO Symbol. Dos
    # filas idénticas sugerían dos entradas en la tabla, que es justo lo que
    # esta vista tiene que dejar claro que no pasa.
    vistos = set()
    for scope in table.scopes:
        for namespace, tabla in (("valor", scope.values), ("tipo", scope.types)):
            for nombre in sorted(tabla):
                sym = tabla[nombre]
                if id(sym) not in vistos:
                    vistos.add(id(sym))
                    filas.append(fila(sym, namespace))
                for miembro in sorted(sym.members or {}):
                    hijo = sym.members[miembro]
                    if id(hijo) in vistos:
                        continue
                    vistos.add(id(hijo))
                    filas.append(fila(hijo, namespace, owner=nombre))
    return filas


def _postfijo_de(t) -> str:
    """El tipo en la notación DEL LENGUAJE (``Punto ptr mutable``).

    Reutiliza la del generador de UML en vez de escribir una segunda: el
    diagrama y la tabla enseñan el mismo tipo, y dos formateadores acabarían
    contestando distinto (ya pasó: uno prefijo y otro postfijo).
    """
    from include.symbols_uml import _postfijo
    return _postfijo(t)


def _tokens(tokens) -> List[Dict[str, Any]]:
    """Los tokens con su posición y su lexema.

    La posición es lo que permite que pasar el ratón por un token subraye su
    línea en el fuente: sin ``ln``/``col`` el visualizador tendría que volver
    a buscar el texto, y volvería a equivocarse donde el lexema aparece dos
    veces.
    """
    salida = []
    for token in tokens:
        value = getattr(token, "value", None)
        salida.append({
            "type": token.type.name,
            "lexeme": token.lexeme,
            "ln": token.ln,
            "col": token.col,
            # los literales llevan su valor ya interpretado; el resto no
            # tiene nada que añadir al lexema.
            "value": None if value is None else _valor(value),
        })
    return salida


def lex_only(source: str, *, path: str = "<buffer>") -> Dict[str, Any]:
    """Solo el análisis LÉXICO. Para colorear mientras se escribe.

    Un editor necesita los tokens en cada pulsación y el resto del pipeline
    no: correr la semántica para pintar una palabra sería pagar cien veces lo
    que cuesta la respuesta. El lexer es una sola pasada.

    Que sea el lexer DE VERDAD y no una aproximación es el punto entero: un
    resaltador propio vuelve a decidir qué es cada palabra, y entonces hay dos
    respuestas para la misma pregunta — el editor pinta ``move`` como un
    identificador y el compilador lo lee como una transferencia.
    """
    lexer = Lexer(source_reader.from_text(source), file=path)
    tokens = lexer.tokenize()
    return {"tokens": _tokens(tokens),
            "diagnostics": [_diag(e, "lexer") for e in lexer.errors]}


def collect(source: str, *, path: str = "<buffer>") -> Dict[str, Any]:
    """Todas las fases de ``source``, hasta donde el programa deje llegar.

    ``path`` ancla la resolución de librerías; no hace falta que exista en
    disco (un buffer sin guardar es el caso normal de un visualizador).
    """
    payload: Dict[str, Any] = {
        "source": source,
        "path": path,
        "diagnostics": [],
        "phases": {},
    }
    fases = payload["phases"]

    def fallo(nombre: str, motivo: str) -> None:
        fases[nombre] = {"ok": False, "reason": motivo}

    # --- léxico ---------------------------------------------------------- #
    text = source_reader.from_text(source)
    lexer = Lexer(text, file=path)
    tokens = lexer.tokenize()
    payload["diagnostics"] += [_diag(e, "lexer") for e in lexer.errors]
    fases["tokens"] = {"ok": True, "tokens": _tokens(tokens)}

    # --- parser / AST ---------------------------------------------------- #
    from include.ast_json import to_dict

    parser = Parser(tokens)
    program = parser.parse()
    payload["diagnostics"] += [_diag(e, "parser") for e in parser.ctx.errors]
    fases["ast"] = {"ok": True, "tree": to_dict(program)}

    # --- AST-tipado ------------------------------------------------------ #
    from src.frontend.parser.typed_ast import resolve_types

    resolve_types(program)

    # --- semántica ------------------------------------------------------- #
    from src.frontend.semantic import analyze

    # 'libraries' lo RELLENA la semántica con las unidades que resolvió: es
    # lo que el HIR referencia y lo que el consumidor tendrá que ligar. Sin
    # pedirlo, el módulo salía sin sus librerías y la fase de enlace no tenía
    # nada que enseñar.
    libraries: Dict[str, Any] = {}
    table, sem_errors = analyze(program, source_path=path, libraries=libraries)
    payload["diagnostics"] += [_diag(e, "semantic") for e in sem_errors]
    # el AST-tipado se vuelca DESPUÉS de la semántica: es ella quien anota el
    # 'restype' de cada expresión, que es lo único que lo distingue del AST.
    fases["typed_ast"] = {"ok": True, "tree": to_dict(program)}

    from include.symbols_uml import symbol_table_to_mermaid
    fases["symbols"] = {
        "ok": True,
        "mermaid": symbol_table_to_mermaid(table),
        "scopes": _scopes(table),
        "symbols": _simbolos(table),
    }

    # --- HIR ------------------------------------------------------------- #
    # La frontera NO se cruza con un programa inválido: si la semántica o el
    # parser acumularon algo que detiene la compilación, no hay HIR que
    # enseñar y decirlo es más útil que enseñar uno a medias.
    from error_handler.error import blocks

    if blocks(parser.ctx.errors) or blocks(sem_errors) or blocks(lexer.errors):
        motivo = ("el HIR solo se emite con el programa libre de errores: la "
                  "frontera hacia los backends no se cruza con un programa "
                  "inválido")
        fallo("hir", motivo)
        fallo("link", motivo)
        return payload

    try:
        from src.HIR.emmit_IR import build_module, module_to_text, serialize
        from src.HIR.pretty import format_type, pretty
        from src.HIR.stubs import load_hir_pb2
    except Exception as exc:  # protobuf no instalado
        fallo("hir", f"la fase HIR necesita protobuf: {exc}")
        fallo("link", "sin HIR no hay unidades que ligar")
        return payload

    pb = load_hir_pb2()
    module, hir_errors = build_module(program, table, source_file=path,
                                      libraries=libraries)
    payload["diagnostics"] += [_diag(e, "hir") for e in hir_errors]
    if hir_errors:
        fallo("hir", "el emisor rechazó el programa")
        fallo("link", "sin HIR no hay unidades que ligar")
        return payload

    # DOS vistas: la legible (para leer el programa) y el texto del protobuf
    # (para depurar el FORMATO: qué tag lleva qué). Son preguntas distintas.
    fases["hir"] = {"ok": True, "pretty": pretty(module),
                    "text": module_to_text(module)}

    payload["phir"] = serialize(module)
    # Las unidades importadas viajan JUNTO al módulo principal: cada una emite
    # su propio '.phir' y el consumidor las liga por ruta relativa. Sin ellas,
    # el target web no puede enlazar y ninguna de sus fases tiene nada que
    # decir — el mismo requisito que al distribuir un programa compilado.
    from .pipeline import build_library_units
    unidades, _ = build_library_units(libraries, {})
    payload["units"] = {alias: datos[0] for alias, datos in unidades.items()}

    # --- enlace ---------------------------------------------------------- #
    fases["link"] = _enlace(pb, module, unidades)
    return payload


def _enlace(pb, module, unidades: Dict[str, Any]) -> Dict[str, Any]:
    """Qué trajo el compilador de cada librería, no solo QUE la resolvió.

    ``print`` no está en el lenguaje. Decir "se resolvió el import de IO" no
    explica nada; lo que explica es **ver lo que llegó**: que ``IO.stdp``
    aporta ``println``, que su implementación real es el prototipo
    ``__write__`` que pone el host, y que un hook como ``__print__`` viaja
    con su dueño para que ``print(x)`` sepa a quién llamar.

    Cada unidad se lee de SU propio ``.phir`` —el mismo que viajará junto al
    programa— así que lo que se enseña es exactamente lo que el consumidor va
    a ligar, no un resumen aparte que pudiera divergir.
    """
    from src.HIR.pretty import format_type

    def firma(sym) -> str:
        params = ", ".join(format_type(t, pb) for t in sym.param_types)
        return f"fn {sym.name}({params}) -> {format_type(sym.type, pb)}"

    aportes = []
    for ref in module.libraries:
        datos = unidades.get(ref.alias)
        if datos is None:
            aportes.append({"alias": ref.alias, "phir": ref.phir,
                            "error": "su unidad no se pudo compilar"})
            continue
        unidad = pb.Module()
        unidad.ParseFromString(datos[0])

        # los PROTOTIPOS son la parte que sorprende: la unidad declara la
        # firma y quien ejecuta pone el cuerpo. Es de donde sale el 'host'.
        prototipos = {d.function.name for d in unidad.items
                      if d.WhichOneof("node") == "function"
                      and not d.function.HasField("body")}
        funciones = [
            {"signature": firma(sym), "prototype": nombre in prototipos}
            for nombre, sym in sorted(unidad.symbols.values.items())
            if sym.kind == pb.SymbolKind.Value("FUNCTION")
        ]
        aportes.append({
            "alias": ref.alias,
            "phir": ref.phir,
            "bytes": len(datos[0]),
            "source": unidad.source_file,
            "functions": funciones,
            "types": sorted(unidad.symbols.types),
            "hooks": [{"owner": h.owner_type,
                       "name": h.hook_name or _nombre_hook(pb, h.kind)}
                      for h in unidad.symbols.hooks],
        })

    return {
        "ok": True,
        "libraries": aportes,
        # los hooks y las conversiones que el programa ve YA ligados: la
        # tabla con la que 'print(x)' encuentra a quién llamar.
        "hooks": [{"owner": h.owner_type,
                   "name": h.hook_name or _nombre_hook(pb, h.kind),
                   "extension": h.extension}
                  for h in module.symbols.hooks],
        "casts": [{"from": format_type(c.param_types[0], pb)
                            if c.param_types else "<?>",
                   "to": format_type(c.type, pb)}
                  for c in module.symbols.casts],
    }


def _nombre_hook(pb, kind: int) -> str:
    """``__print__`` a partir de su ``HookKind`` (los del vocabulario fijo)."""
    return "__" + pb.HookKind.Name(kind).lower() + "__"


__all__ = ["collect", "lex_only"]

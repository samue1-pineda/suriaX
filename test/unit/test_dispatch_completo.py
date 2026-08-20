"""Las tablas de despacho de la Semántica cubren TODO el AST.

Existe por un bug real: ``ast.TypeDecl`` no estaba en el despacho de
``scope_resolver`` y ``visit_stmt`` se saltaba en silencio lo que no
encontraba, así que el inicializador de ``const type T = f();`` cruzaba el
frontend entero sin que ninguna pasada lo mirara — un nombre inexistente solo
aparecía al ejecutar, como ``RT006``.

El despacho ahora reporta lo que no sabe recorrer, pero eso es la red de
seguridad, no la solución: un nodo sin handler sigue siendo un fallo. Este
test lo detecta cuando se añade la clase, no cuando alguien compila un
programa que la usa.
"""

from __future__ import annotations

import inspect
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _p in (_REPO_ROOT, os.path.join(_REPO_ROOT, "V0")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _subclases(base) -> set:
    from include import ast_nodes as ast
    return {
        cls for _, cls in inspect.getmembers(ast, inspect.isclass)
        if issubclass(cls, base) and cls is not base
    }


def _resolver():
    """Un ``_ScopeResolver`` con sus tablas ya construidas."""
    from src.frontend.semantic.context import SemanticContext
    from src.frontend.semantic.scope_resolver import _ScopeResolver
    from src.frontend.semantic.symbol_table import SymbolTable
    return _ScopeResolver(SemanticContext(SymbolTable()))


def test_toda_sentencia_tiene_handler_en_la_resolucion_de_scopes():
    from include import ast_nodes as ast
    faltan = sorted(c.__name__ for c in _subclases(ast.Statement)
                    if c not in _resolver()._stmt_dispatch)
    assert not faltan, (
        f"sentencias sin handler en 'scope_resolver': {faltan}. Un nodo que "
        "no se recorre no resuelve sus nombres ni anota su tipo, y el HIR "
        "promete lo contrario a todos los backends")


def test_toda_expresion_tiene_handler_en_la_resolucion_de_scopes():
    from include import ast_nodes as ast
    faltan = sorted(c.__name__ for c in _subclases(ast.Expression)
                    if c not in _resolver()._expr_dispatch)
    assert not faltan, (
        f"expresiones sin handler en 'scope_resolver': {faltan}. Sin handler "
        "la expresión viaja al HIR sin 'restype'")


#: Declaraciones que ``collect`` NO registra, y por qué. La lista es explícita
#: a propósito: el despacho de la pasada 1 se salta en silencio lo que no
#: conoce —el mismo patrón que escondió el bug de ``TypeDecl``— así que la
#: exención tiene que estar escrita y comprobada, no asumida.
_SIN_RECOLECTAR = {
    "DecoratorDecl":   "se desenvuelve antes del despacho ('item = item.target')",
    "TraitDecl":       "tiene su propia rama antes del despacho",
    "ImplDecl":        "el parser lo APLANA: las fases posteriores solo ven FunctionDecl",
    "TestDecl":        "no declara símbolos; su cuerpo lo resuelve la pasada de scopes",
    "ExportDirective": "cierra la unidad; no declara nada",
    "ExternBlock":     "bloque C++ crudo; su contenido es del backend",
}


def test_toda_declaracion_se_recolecta_o_esta_exenta_por_escrito():
    """Pasada 1: lo que no está en el despacho tiene que estar en la lista de
    exenciones, con su motivo. Una clase nueva que no esté en ninguna de las
    dos se registraría en ningún sitio y el fallo saldría lejos."""
    import re

    from include import ast_nodes as ast

    fuente = open(os.path.join(_REPO_ROOT, "V0", "src", "frontend", "semantic",
                               "collect.py"), encoding="utf-8").read()
    en_tabla = set(re.findall(r"ast\.(\w+): _collect", fuente))
    huerfanas = sorted(
        c.__name__ for c in _subclases(ast.Declaration)
        if c.__name__ not in en_tabla and c.__name__ not in _SIN_RECOLECTAR)
    assert not huerfanas, (
        f"declaraciones que 'collect' ignora sin motivo declarado: "
        f"{huerfanas}. Añádelas al despacho o a '_SIN_RECOLECTAR' con su razón")


def test_las_exenciones_de_collect_siguen_existiendo():
    """El otro lado: una exención de un nodo que ya no existe es basura que
    haría pasar el test de arriba por el motivo equivocado."""
    from include import ast_nodes as ast

    nombres = {c.__name__ for c in _subclases(ast.Declaration)}
    fantasmas = sorted(n for n in _SIN_RECOLECTAR if n not in nombres)
    assert not fantasmas, (
        f"'_SIN_RECOLECTAR' nombra clases que ya no existen: {fantasmas}")


def test_un_nodo_sin_handler_se_reporta_en_vez_de_ignorarse():
    """La red de seguridad: si aun así llega uno, tiene que decirlo."""
    from include import ast_nodes as ast

    class SentenciaDesconocida(ast.Statement):
        pass

    resolver = _resolver()
    resolver.visit_stmt(SentenciaDesconocida(ln=1, col=1))
    codigos = [e.code for e in resolver.ctx.errors]
    assert "SEM000" in codigos, (
        f"un nodo sin handler debe reportarse, no ignorarse; se obtuvo: "
        f"{codigos or '(ningún diagnóstico)'}")

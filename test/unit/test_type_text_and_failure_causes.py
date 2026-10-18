"""El texto de los tipos en los diagnósticos y las causas que no se tiran.

Dos defectos de la misma familia —el diagnóstico no dice la verdad— que se
corrigieron juntos:

1. Los tipos salían en dos notaciones según quién escribiera el mensaje:
   ``'ptr C'`` (``Type.__repr__``, prefija) y ``'C ptr'``
   (``extensions.format_type``, la del lenguaje). Ahora hay un solo
   formateador, el ``repr``, y habla como se escribe el código.
2. ``semantic/hooks.py`` convertía cualquier excepción al leer la firma de un
   hook en un tipo ``<?>`` dentro de un ``SEM006`` que culpaba al programa, y
   ``semantic/extensions.py`` devolvía ``None`` ("no es un tipo") ante
   cualquier excepción, sin decir cuál. Ahora solo se atrapa lo esperado (un
   diagnóstico del lexer o del parser, y se cita), y un defecto del
   compilador sube.
"""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_V0 = os.path.join(_REPO_ROOT, "V0")
for _p in (_REPO_ROOT, _V0):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.path.insert(0, os.path.join(_REPO_ROOT, "test"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import analyze  # noqa: E402


# --------------------------------------------------------------------------- #
# 1. una sola notación: la del lenguaje
# --------------------------------------------------------------------------- #

def test_type_text_is_postfix_like_the_source():
    from include.types_ast import (PRIMITIVE_TYPES, function_of, nominal,
                                   nullable_of, pointer_of)
    c = nominal("C")
    assert repr(pointer_of(c)) == "C ptr"
    assert repr(pointer_of(c, mut=True)) == "C ptr mutable"
    assert repr(pointer_of(nullable_of(c))) == "C? ptr"
    assert repr(nominal("Vector", (pointer_of(PRIMITIVE_TYPES["int"]),))) \
        == "Vector<int ptr>"
    fn = function_of((PRIMITIVE_TYPES["int"],), PRIMITIVE_TYPES["int"])
    # el sufijo tras 'fn(...) -> R' se pegaria al retorno: van parentesis
    assert repr(pointer_of(fn)) == "(fn(int) -> int) ptr"


def test_format_type_is_the_same_formatter():
    """``format_type`` delega en el ``repr``: antes además perdía los
    argumentos de tipo (``Vector<int>`` salía ``Vector``)."""
    from include.types_ast import PRIMITIVE_TYPES, nominal, pointer_of
    from src.frontend.semantic.extensions import format_type
    t = pointer_of(nominal("Vector", (PRIMITIVE_TYPES["int"],)), mut=True)
    assert format_type(t) == repr(t) == "Vector<int> ptr mutable"
    assert format_type(None) == "?"


def test_a_diagnostic_names_the_pointer_as_it_is_written():
    """El caso que se veía: SEM015 decía ``'ptr C'`` y aconsejaba ``'ptr
    mutable C'``, una forma que el parser rechaza."""
    _, _, errors = analyze("struct { int n; } C;\n"
                           "fn f(C ptr p) -> void { p.n = 7; }\n")
    assert [e.code for e in errors] == ["SEM015"], [e.code for e in errors]
    message = errors[0].message
    assert "'C ptr'" in message and "'C ptr mutable'" in message, message
    assert "ptr C" not in message and "ptr mutable C" not in message, message


# --------------------------------------------------------------------------- #
# 2. las causas no se tiran
# --------------------------------------------------------------------------- #

def test_a_declared_type_that_does_not_parse_says_why():
    """EXT030 cita el diagnóstico del parser, no solo el texto."""
    from src.frontend.semantic.extensions import (build_vocabulary,
                                                  parse_declared_type_reason)
    from test_extension_vocabulary import _declaracion, _extension_set

    tipo, motivo = parse_declared_type_reason("fn(int ->")
    assert tipo is None and motivo and "PAR" in motivo, motivo
    _, problemas = build_vocabulary(
        _extension_set(_declaracion(params=("Body ptr mutable", "fn(int ->"))))
    assert [p["code"] for p in problemas] == ["EXT030"]
    assert "PAR" in problemas[0]["message"], problemas[0]["message"]


def test_an_internal_failure_while_parsing_a_declared_type_is_not_hidden():
    """Un defecto del compilador no puede salir como "no es un tipo"."""
    from src.frontend.parser import typed_ast
    from src.frontend.semantic.extensions import parse_declared_type

    original = typed_ast.resolve_type_expr

    def broken(_type_expr):
        raise RuntimeError("defecto interno simulado")

    typed_ast.resolve_type_expr = broken
    try:
        try:
            parse_declared_type("int")
        except RuntimeError as exc:
            assert "simulado" in str(exc)
        else:
            raise AssertionError("la excepcion interna se trago")
    finally:
        typed_ast.resolve_type_expr = original


def test_an_internal_failure_while_checking_a_hook_is_not_hidden():
    """``hooks._validate_declared`` dejaba un ``<?>`` y culpaba al programa
    con un SEM006. El fallo simulado solo ocurre cuando quien llama es
    ``hooks`` (el vocabulario se construye antes con el original)."""
    from src.frontend.parser import typed_ast
    from test_extension_vocabulary import _compilar, _declaracion, _extension_set

    original = typed_ast.resolve_type_expr
    calls = {"n": 0}

    def broken_for_hooks(type_expr):
        if sys._getframe(1).f_globals.get("__name__", "").endswith("semantic.hooks"):
            calls["n"] += 1
            raise RuntimeError("defecto interno simulado")
        return original(type_expr)

    typed_ast.resolve_type_expr = broken_for_hooks
    try:
        try:
            _compilar(extensions=_extension_set(_declaracion()))
        except RuntimeError as exc:
            assert "simulado" in str(exc)
        else:
            raise AssertionError("la excepcion interna se trago")
    finally:
        typed_ast.resolve_type_expr = original
    assert calls["n"] == 1, calls

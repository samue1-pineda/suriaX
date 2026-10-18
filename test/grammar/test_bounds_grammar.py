"""grammar/bounds — la forma de las cotas ``<T: A + B>`` y de los parámetros
con nombre de un prototipo de trait (paso 4).

Va por ``parse`` (el parser solo), nunca por ``error_codes``: lo que pasa
por ``error_codes`` entra en el corpus del diferencial V0/V1 y la V1 todavía
no conoce esta sintaxis.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import parse  # noqa: E402
from include import ast_nodes as ast  # noqa: E402


def _items(source: str):
    program, errors, lex_errors = parse(source)
    assert not lex_errors, [e.message for e in lex_errors]
    assert not errors, [e.message for e in errors]
    return program.items


def _bounds(decl) -> dict:
    return {p: [b.name for b in bs] for p, bs in decl.type_bounds.items()}


def test_function_bounds_keep_the_parameter_names():
    fn = _items("fn f<T: Ord + Hash, U>(T a, U b) -> T { return a; }")[0]
    assert fn.type_params == ["T", "U"]
    assert _bounds(fn) == {"T": ["Ord", "Hash"]}
    assert (fn.type_bounds["T"][1].ln, fn.type_bounds["T"][1].col) == (1, 15)


def test_struct_enum_and_opaque_type_bounds():
    struct, enum, opaque = _items("struct { K k; } Pair<K: Ord, V>;\n"
                                  "enum Res<T: geom.Shape, E> { Ok(T), Err(E) };\n"
                                  "const type Handle<T: Hash>;\n")
    assert _bounds(struct) == {"K": ["Ord"]} and struct.type_params == ["K", "V"]
    assert _bounds(enum) == {"T": ["geom.Shape"]}
    assert _bounds(opaque) == {"T": ["Hash"]}


def test_impl_bounds_travel_with_each_method():
    m, = _items("struct { T v; } Box<T>;\n"
                "@impl Box<T: Print> { fn show<U: Eq>(Box<T> ptr self, U u) -> void { } }")[1:]
    assert isinstance(m, ast.FunctionDecl)
    assert m.impl_type_params == ["T"] and _bounds(m) == {"U": ["Eq"]}
    assert {p: [b.name for b in bs] for p, bs in m.impl_type_bounds.items()} == {"T": ["Print"]}


def test_a_generic_without_bounds_has_none():
    assert _items("fn f<T>(T a) -> T { return a; }")[0].type_bounds == {}


def test_a_bound_is_a_name_not_a_type():
    _, errors, _ = parse("fn f<T: int>(T a) -> T { return a; }")
    assert [e.code for e in errors] == ["PAR023"]


def test_trait_prototype_parameters_may_have_names():
    t = _items("@trait struct { fn area(self ptr s, int k) -> int; "
               "dunder fn __n__(self ptr) -> str; } Shape;")[0]
    area = t.methods[0]
    assert area.name == "area" and len(area.params) == 2
    assert isinstance(area.params[0], ast.PointerTypeExpr)
    assert isinstance(area.params[0].inner, ast.SelfTypeExpr)

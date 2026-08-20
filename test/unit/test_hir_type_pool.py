"""El POOL de tipos del HIR v2 (``Module.types``).

Los nodos referencian su tipo por índice en vez de re-serializarlo: en un
programa de 47 k tokens había 21 065 mensajes ``Type`` de 43 formas distintas
(490x de repetición, el 20 % del artefacto). Este archivo fija las tres
propiedades de las que depende que eso sea correcto y no solo pequeño:

  1. **integridad referencial**: todo ``type_id`` cae dentro del pool;
  2. **deduplicación por VALOR**: dos tipos estructuralmente iguales comparten
     entrada aunque el frontend los haya construido por separado;
  3. **el 0 significa "sin tipo"**, sin necesidad de un campo de presencia.
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

from helpers import lex  # noqa: E402

_PROGRAMA = """
struct { int x; int y; } Punto;

fn suma(int a, int b) -> int { return a + b; }

fn distancia(Punto ptr p) -> int { return p.x + p.y; }

fn main() -> int {
    var Punto p = Punto{ x: 1, y: 2 };
    var int a = suma(p.x, p.y);
    var int b = suma(a, a);
    var int c = suma(b, b);
    var bool grande = c > 100;
    return 0;
}
"""


def _module(source: str = _PROGRAMA):
    from src.frontend.parser.parser import Parser
    from src.frontend.parser.typed_ast import resolve_types
    from src.frontend.semantic import analyze
    from src.HIR.emmit_IR import build_module

    tokens, lex_errors = lex(source)
    assert not lex_errors, [e.code for e in lex_errors]
    parser = Parser(tokens)
    program = parser.parse()
    assert not parser.ctx.errors, [e.code for e in parser.ctx.errors]
    resolve_types(program)
    table, sem_errors = analyze(program, source_path="<test>")
    assert not sem_errors, [e.code for e in sem_errors]
    module, hir_errors = build_module(program, table, source_file="<test>")
    assert not hir_errors, [e.code for e in hir_errors]
    return module


def _walk_type_ids(module):
    """Todos los ``type_id`` que aparecen en los NODOS del módulo."""
    ids: list[int] = []

    def expr(e) -> None:
        ids.append(e.type_id)
        which = e.WhichOneof("node")
        if which == "binary":
            expr(e.binary.left)
            expr(e.binary.right)
        elif which == "call":
            expr(e.call.callee)
            for arg in e.call.args:
                expr(arg)
        elif which == "member":
            expr(e.member.obj)
        elif which == "struct_literal":
            for value in e.struct_literal.values:
                expr(value)
        elif which == "assignment":
            expr(e.assignment.target)
            expr(e.assignment.value)

    def block(b) -> None:
        for stmt in b.statements:
            which = stmt.WhichOneof("node")
            if which == "var_decl":
                ids.append(stmt.var_decl.type_id)
                if stmt.var_decl.HasField("value"):
                    expr(stmt.var_decl.value)
            elif which == "return_stmt" and stmt.return_stmt.HasField("value"):
                expr(stmt.return_stmt.value)
            elif which == "expr_stmt":
                expr(stmt.expr_stmt.expr)
            elif which == "block":
                block(stmt.block)

    for decl in module.items:
        which = decl.WhichOneof("node")
        if which == "function":
            fn = decl.function
            ids.append(fn.return_type_id)
            for param in fn.params:
                ids.append(param.type_id)
            if fn.HasField("body"):
                block(fn.body)
        elif which == "struct_decl":
            for field in decl.struct_decl.fields:
                ids.append(field.type_id)
    return ids


def test_todo_id_cae_dentro_del_pool():
    """Integridad referencial: un id fuera de rango sería un nodo con un tipo
    inventado, y el lector no tiene forma de detectarlo por su cuenta."""
    module = _module()
    ids = _walk_type_ids(module)
    assert ids, "el recorrido no encontró ningún type_id"
    for type_id in ids:
        assert 0 <= type_id < len(module.types), (
            f"type_id {type_id} fuera del pool de {len(module.types)} entradas")


def test_la_entrada_cero_es_el_tipo_vacio():
    module = _module()
    assert len(module.types) >= 1
    assert module.types[0].kind == 0        # TYPE_UNSPECIFIED
    assert module.types[0].name == ""
    assert not module.types[0].HasField("inner")


def test_el_pool_no_repite_formas():
    """La propiedad que hace que el pool valga la pena: el programa usa 'int'
    en docenas de sitios y el artefacto lo lleva UNA vez."""
    module = _module()
    formas = [t.SerializeToString() for t in module.types]
    assert len(formas) == len(set(formas)), "hay tipos duplicados en el pool"
    # muchos más usos que formas distintas
    assert len(_walk_type_ids(module)) > 3 * len(module.types)


def test_el_mismo_tipo_en_sitios_distintos_comparte_entrada():
    """Dedupe por VALOR, no por identidad: el 'int' del retorno de una función
    y el de una variable son objetos distintos en el frontend."""
    module = _module()
    por_forma: dict[bytes, int] = {}
    for i, t in enumerate(module.types):
        por_forma.setdefault(t.SerializeToString(), i)
    # el id de 'int' que usa 'suma' como retorno...
    suma = next(d.function for d in module.items
                if d.WhichOneof("node") == "function" and d.function.name == "suma")
    id_retorno = suma.return_type_id
    # ...es el MISMO que el de sus parámetros y el de las variables 'var int'
    assert suma.params[0].type_id == id_retorno
    assert suma.params[1].type_id == id_retorno
    main = next(d.function for d in module.items
                if d.WhichOneof("node") == "function" and d.function.name == "main")
    var_ints = [s.var_decl.type_id for s in main.body.statements
                if s.WhichOneof("node") == "var_decl"
                and module.types[s.var_decl.type_id].kind == module.types[id_retorno].kind
                and module.types[s.var_decl.type_id].name == ""]
    assert var_ints, "no se encontraron variables 'int' en main"
    assert set(var_ints) == {id_retorno}


def test_un_tipo_compuesto_conserva_su_forma_completa():
    """'Punto ptr' viaja en el pool con su 'inner', no aplanado."""
    module = _module()
    distancia = next(d.function for d in module.items
                     if d.WhichOneof("node") == "function"
                     and d.function.name == "distancia")
    tipo = module.types[distancia.params[0].type_id]
    assert tipo.kind == 7          # POINTER
    assert tipo.inner.kind == 9    # NOMINAL
    assert tipo.inner.name == "Punto"


def test_la_tabla_de_simbolos_conserva_sus_tipos_inline():
    """Decisión explícita: la SymbolTable NO participa del pool (es el 4 % de
    los bytes y la parte legible de un .phir). Si alguien la pliega, que sea
    a propósito y no de rebote."""
    module = _module()
    suma = module.symbols.values["suma"]
    assert suma.HasField("type"), "el símbolo perdió su tipo inline"
    assert suma.type.kind != 0
    assert len(suma.param_types) == 2

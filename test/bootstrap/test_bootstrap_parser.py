"""bootstrap/bootstrap_parser — el parser escrito en suriaX contra el de la V0.

``src/frontend/`` (tokens, lexer, arbol, cursor, tipos, expresiones,
directivas, sentencias, declaraciones, parser) es el frontend del bootstrap:
el análisis sintáctico de suriaX escrito en suriaX. La prueba es
DIFERENCIAL: el mismo fuente pasa por los dos parsers y se compara el árbol
entero, nodo por nodo, en un volcado CANÓNICO que los dos saben escribir:

    campo: Clase linea:col escalar=valor ...

(una línea por nodo, sangrada por profundidad; los campos que llena la
Semántica, como ``restype``, no cuentan). Para un programa inválido se
comparan los errores léxicos y el PRIMER error de sintaxis: la recuperación
posterior no es parte del contrato.

Fuera de la prueba, por diseño: ``#extern cpp { ... }`` (el bloque crudo de
C++) y el anidamiento extremo (en la V0 es PAR025; en suriaX agota la pila,
RT019).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import fields

_AQUI = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_AQUI))
sys.path.insert(0, os.path.dirname(_AQUI))
sys.path.insert(0, os.path.join(_REPO, "V0"))

from include import ast_nodes as ast  # noqa: E402
from src.frontend.lexer.lexer import Lexer  # noqa: E402
from src.frontend.parser.parser import Parser  # noqa: E402

_FRONTEND = os.path.join(_REPO, "src", "frontend")
_MAIN = os.path.join(_REPO, "main.py")

#: campos que llena la Semántica (o nadie en el parser): no son del árbol
#: sintáctico y no se comparan.
_SEMANTICOS = {"restype", "hook", "temp_drop", "drops", "transfers",
               "valor_constante", "medido", "nombre_de_item",
               "return_restype", "payload_restypes", "param_restypes",
               "unit", "binding", "temp_by_type", "drops_old", "azucar"}


def _cita(s: str) -> str:
    return '"' + (s.replace("\\", "\\\\").replace('"', '\\"')
                  .replace("\n", "\\n").replace("\t", "\\t")
                  .replace("\r", "\\r").replace("\0", "\\0")) + '"'


def _valor(v) -> str:
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return "null"
    if isinstance(v, str):
        return _cita(v)
    return repr(v)


def _vuelca(nodo, campo: str, nivel: int, salida: list) -> None:
    cabeza = "  " * nivel + (f"{campo}: " if campo else "")
    if isinstance(nodo, str):              # un trozo de texto de una f-string
        salida.append(cabeza + _cita(nodo))
        return
    cabeza += f"{type(nodo).__name__} {nodo.ln}:{nodo.col}"
    hijos = []
    for f in fields(nodo):
        if f.name in ("ln", "col") or f.name in _SEMANTICOS:
            continue
        v = getattr(nodo, f.name)
        if isinstance(v, ast.ASTNode):
            hijos.append((f.name, v))
        elif isinstance(v, list):
            if not v:
                continue
            if f.name != "parts" and all(isinstance(x, str) for x in v):
                cabeza += f" {f.name}=[{','.join(v)}]"
            else:
                hijos.extend((f.name, x) for x in v)
        elif f.name == "value" and isinstance(nodo, ast.Literal):
            cabeza += f" value={_valor(v)}"      # el valor de un literal, siempre
        elif v is None or v is False or v == "":
            continue
        else:
            cabeza += f" {f.name}={_valor(v)}"
    salida.append(cabeza)
    for c, h in hijos:
        _vuelca(h, c, nivel + 1, salida)


_NUMERO = re.compile(r"value=(-?\d[\d.]*)(?= |$)")


def _normaliza(linea: str) -> str:
    """Los números por su VALOR: la V0 guarda el número ('3.25', '7') y
    suriaX el texto que se escribió ('3.250', '007')."""
    def _uno(m):
        t = m.group(1)
        return "value=" + (repr(float(t)) if "." in t else str(int(t)))
    return _NUMERO.sub(_uno, linea)


def _v0(fuente: str):
    lexer = Lexer(fuente)
    tokens = lexer.tokenize()
    parser = Parser(tokens)
    programa = parser.parse()
    salida: list = []
    _vuelca(programa, "", 0, salida)
    return ([_normaliza(l) for l in salida], [e.code for e in lexer.errors],
            [e.code for e in parser.ctx.errors])


def _como_literal(texto: str) -> str:
    escapado = (texto.replace("\\", "\\\\").replace('"', '\\"')
                .replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r"))
    return f'"{escapado}"'


def _suriax(fuente: str):
    with tempfile.TemporaryDirectory(prefix="suriax-parser-") as tmp:
        destino = os.path.join(tmp, "lib", "frontend")
        os.makedirs(destino)
        for nombre in os.listdir(_FRONTEND):
            if nombre.endswith(".libsrx"):
                shutil.copy(os.path.join(_FRONTEND, nombre), destino)
        programa = os.path.join(tmp, "driver.srcx")
        with open(programa, "w", encoding="utf-8") as fh:
            fh.write("#import frontend.parser as ps\n"
                     f"fn main() -> int {{ ps.analiza({_como_literal(fuente)}); "
                     "return 0; }\n")
        proc = subprocess.run(
            [sys.executable, _MAIN, programa], cwd=tmp, capture_output=True,
            encoding="utf-8", errors="replace", timeout=900,
            env={**os.environ, "PYTHONUTF8": "1"})
    assert proc.returncode == 0, (proc.returncode, proc.stderr[-3000:])
    arbol, lexicos, sintaxis = [], [], []
    for linea in proc.stdout.splitlines():
        if linea.startswith(("frontend OK", "HIR ")) or \
                (linea.lstrip().startswith("unidad '") and " -> " in linea):
            continue
        if linea.startswith("error "):
            codigo = linea.split()[2 if linea.split()[1][0].isdigit() else 1]
            codigo = codigo.rstrip(":")
            (lexicos if codigo.startswith("LEX") else sintaxis).append(codigo)
        else:
            arbol.append(_normaliza(linea))
    return arbol, lexicos, sintaxis


def _compara(fuente: str) -> None:
    """Un programa VÁLIDO: el árbol entero, y ningún error en ninguno."""
    esperado, lex_v0, par_v0 = _v0(fuente)
    assert not lex_v0 and not par_v0, ("la muestra no es valida", lex_v0, par_v0)
    obtenido, lex_srx, par_srx = _suriax(fuente)
    assert not lex_srx and not par_srx, (lex_srx, par_srx)
    for i, (a, b) in enumerate(zip(esperado, obtenido)):
        assert a == b, (f"linea {i} del volcado:\n  V0     {a}\n  suriaX {b}\n"
                        "contexto V0:\n  " + "\n  ".join(esperado[max(0, i - 4):i + 2]))
    assert len(esperado) == len(obtenido), (
        f"V0 {len(esperado)} lineas, suriaX {len(obtenido)}:\n"
        + "\n".join((esperado[len(obtenido):] or obtenido[len(esperado):])[:10]))


def _primer_error(fuente: str) -> None:
    """Un programa INVÁLIDO: los errores léxicos y el primer error de sintaxis."""
    _, lex_v0, par_v0 = _v0(fuente)
    assert par_v0, "la muestra no tiene errores de sintaxis en la V0"
    _, lex_srx, par_srx = _suriax(fuente)
    assert lex_srx == lex_v0 and par_srx[:1] == par_v0[:1], (
        fuente, (lex_v0, par_v0[:1]), (lex_srx, par_srx[:1]))


# --------------------------------------------------------------------------- #
# muestras válidas
# --------------------------------------------------------------------------- #

def test_expresiones():
    _compara(
        "fn f() -> void {\n"
        "    x = a + b * c - d / e % g;\n"
        "    x = -a + - -3 - -2.5 + not b;\n"
        "    y = a == b and c != d or e < f and g >= h;\n"
        "    a = b = c;\n"
        "    p.x.y = q[i + 1].z(1, 2)[0];\n"
        "    v = vec.make<int>(4) + Caja<str>{ v: \"x\", n: 1, } + pt.Punto{ x: 1 };\n"
        "    b = a < c;\n"
        "    m = cast<float>(n) + sizeof(Caja) + (a + b) * c;\n"
        "    r = move otro;\n"
        "    q = &x;\n"
        "    s = f\"a{x}b{{c}}{f(y, g{k: 1})}\" \"z\";\n"
        "    t = \"uno\" \"dos\\n\" + cast<str>('\\t');\n"
        "    u = true and false or null == nada;\n"
        "    w = 0xFF + 0b1010 + 0o17 + 1_000 + 0xFFFF_FFFF_FFFF_FFFF + 2.5_0;\n"
        "    byte k = cast<byte>(w) & 0x0F;\n"
        "    var byte ptr mutable bs = mem.reserve<byte>(4);\n"
        "    s = f\"{x!r} {n:08b} {f(a, g{k: 1}):5} {a != b} {q!r:12} {h:.3f}\";\n"
        "}\n")


def test_sentencias():
    _compara(
        "fn f(int n) -> int {\n"
        "    int a;\n"
        "    const int b = 2;\n"
        "    var str ptr? c = null;\n"
        "    pt.Punto ptr mutable p = &q;\n"
        "    error int r = g();\n"
        "    type Blk;\n"
        "    const type Par<A, B> = h();\n"
        "    IO = #import IO;\n"
        "    const S = #from io #import stdp as salida;\n"
        "    int vec.Vector v[8];\n"
        "    int vec.Vector w = otro;\n"
        "    a += 1; a -= 2; a *= 3; a /= 4; a %= 5; a++; v[0]--; p.x++;\n"
        "    a &= 1; a |= 2; a ^= 3; a <<= 1; a >>= 2; a = ~a | b ^ c & d << 1 >> 2;\n"
        "    b = a & b == c; var vec.Vector<vec.Vector<int>> w = vec.dynamic<vec.Vector<int>>(1);\n"
        "    if (a > 0) { return 1; } else if (a < 0) { return -1; } else { a = 0; };\n"
        "    while (true) { if (a) { break; }; continue; };\n"
        "    match (c) {\n"
        "        case Color.Rojo: { a = 1; }\n"
        "        case Color.Hoja(n, t) { a = 2; }\n"
        "        case 3: return 3;\n"
        "    };\n"
        "    try { throw Fallo{ m: 1 }; } catch (Fallo e) { } catch (e) { };\n"
        "    try { a = 1; } finally { while (a) { break; }; };\n"
        "    with (var R a = abre(1), var R b = abre(2)) { usa(a, b); };\n"
        "    with abre_en(var R f, \"x\", 1) { usa(f); };\n"
        "    with sis.archivos.open(var File g, \"y\") { };\n"
        "    with (guardia(\"en\")) { .nombre = 1; };\n"
        "    with (v) { .ancho = 900; .show(); s = f\"{.titulo}\"; };\n"
        "    with (a.b, guardia(2)) { with (c[0]) { .d = 1; }; };\n"
        "    try { } catch (e) { } finally { try { } finally { }; };\n"
        "    move a;\n"
        "    free p;\n"
        "    return;\n"
        "}\n")


def test_declaraciones():
    _compara(
        "#import IO\n#import io.stdp as sp;\n#from io #import stdp\n"
        "#export as lib\n"
        "fn proto(int a, char c) -> int;\n"
        "fn sin_flecha() { }\n"
        "public fn make<T>(int cap) -> vec.Vector<T> ptr { return null; }\n"
        "hook fn __free__(Caja ptr c) -> void { }\n"
        "private dunder fn __suma__(Caja ptr a, Caja ptr b) -> Caja { }\n"
        "internal fn __libre__() { }\n"
        "struct { int n; T ptr dato; } Caja<T>;\n"
        "public struct { } Vacia;\n"
        "enum Color { Rojo = 1, Verde, Azul = 3, };\n"
        "internal enum Nodo { Num(int), Suma(Nodo ptr, Nodo ptr), Nada };\n"
        "public const int MAX = 10;\n"
        "@inline hook fn __print__(Caja ptr c) -> void { }\n"
        "@impl(iterable, ordenable) public struct { int x; } Lista;\n"
        "@deprecated enum Viejo { A };\n"
        "@impl Caja<T> { fn tam(Caja<T> ptr self) -> int { return 0; } "
        "fn pon(Caja ptr mutable self, T x) { } }\n"
        "@trait public struct { fn __len__(self ptr) -> int; hook fn __print__(self ptr); } Medible;\n"
        "@trait fn __hash__(self ptr) -> int;\n"
        "test \"una prueba\" { }\n"
        "#export package as pk\n")


def test_un_programa_real():
    with open(os.path.join(_REPO, "test", "e2e", "fuego", "inventario.srcx"), encoding="utf-8") as fh:
        _compara(fh.read())


def test_la_libreria_del_vector():
    with open(os.path.join(_REPO, "lib", "array", "vector.libsrx"), encoding="utf-8") as fh:
        _compara(fh.read())


def test_el_parser_se_lee_a_si_mismo():
    """El parser en suriaX leyendo su propio fuente: la primera vez que el
    compilador en suriaX entiende la ESTRUCTURA de código del compilador en
    suriaX."""
    with open(os.path.join(_FRONTEND, "expresiones.libsrx"), encoding="utf-8") as fh:
        _compara(fh.read())


# --------------------------------------------------------------------------- #
# muestras inválidas: el primer error coincide
# --------------------------------------------------------------------------- #

def test_los_errores_de_sintaxis_coinciden():
    for fuente in (
        "fn f() -> void { x = 1 }",
        "fn f() -> void { public int x; }",
        "fn f() -> void { break; }",
        "fn f() -> void { mutable int x; }",
        "fn f() -> void { ptr int x; }",
        "fn f() -> void { const a = 1; }",
        "fn f() -> void { int val[8]; }",
        "fn f() -> void { int vec.Vector v; }",
        "fn f() -> void { x = cast<int, str>(y); }",
        "fn f() -> void { f()[0] += 1; }",
        "fn f() -> void { 3 = x; }",
        "fn f() -> void { s = f\"{a b}\"; }",
        "fn f() -> void { s = f\"{)}\"; }",
        "fn f() -> void { s = f\"{x:zz}\"; }",
        "fn f() -> void { s = f\"{x!r:08q}x\"; }",
        "fn f() -> void { x = ; }",
        "hook fn normal() { }",
        "hook struct { } S;",
        "@impl Caja { fn __m__(Caja ptr self) { } }",
        "@impl Caja { fn m(Otra ptr self) { } }",
        "@impl Caja { fn m(Caja ptr self); }",
        "@impl public Caja { }",
        "@trait(x) fn __h__();",
        "@deco int x;",
        "enum E { A(int) = 1 };",
        "enum E { A }",
        "struct { int<T> x; } S;",
        "struct { } S<int>;",
        "#bogus",
        "#test ast",
        "#from io #import stdp.println",
        "#import str",
        "#export package pk",
        "public fn f() { } public if (x) { }",
        "fn f() -> void { match (x) { case 1 { } case 2 x = 1; } }",
        "fn f() -> int { try { } finally { return 1; }; }",
        "fn f() -> void { while (x) { try { } finally { continue; }; }; }",
        "fn f() -> void { try { } finally { break; }; }",
        "fn f() -> void { try { }; }",
        "fn f() -> void { c = a > > b; }",
        "fn f() -> void { .x = 1; }",
        "fn f() -> void { with (a, b) { .x = 1; }; }",
        "fn f() -> void { with abre(1) { }; }",
        "fn f() -> void { s = f\"{.x}\"; }",
    ):
        _primer_error(fuente)

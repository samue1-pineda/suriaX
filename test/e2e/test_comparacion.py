"""e2e/comparacion — que significan ``==`` y ``<`` sobre los tipos del usuario.

Tres reglas, y las tres se fijan aqui ejecutando programas:

 - ``==`` sin ``__eq__`` es igualdad de VALOR, campo a campo (y variante mas
   payload en un enum suma). Antes caia a la identidad del objeto del
   interprete: ``b = a; a == b`` daba ``false`` aunque ``b`` fuera una copia
   exacta, y ``f == Forma.Circulo(3)`` tambien. Un ``__eq__`` declarado sigue
   mandando. Los PUNTEROS se comparan por la direccion, no por lo apuntado.
 - ``<``/``<=``/``>``/``>=`` sobre un tipo nominal los da su ``__cmp__``
   (negativo, cero o positivo). Un enum sin datos es un entero y se ordena
   por su valor, como los primitivos.
 - un generico puede ordenar su ``T``; lo que se comprueba es cada instancia
   (``SEM039`` en ``test_diagnostics_comparacion.py``). ``Vector.sort`` es el
   primer consumidor: mezcla ESTABLE.

El target web y la VM no conocen todavia ``__cmp__`` ni la igualdad de valor:
estas pruebas son del interprete.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import run_source  # noqa: E402

W = "fn __write__(str s) -> void;\n"

P = "struct { int x; int y; } P;\n"

FORMA = ("enum Forma {\n"
         "    Circulo(int),\n"
         "    Rect(int, int),\n"
         "    Nada,\n"
         "};\n")

#: un tipo con orden propio: por 'clave', y 'nombre' no participa (asi se ve
#: la estabilidad: dos claves iguales conservan su orden de llegada).
ITEM = ("struct { int clave; str nombre; } Item;\n"
        "hook fn __cmp__(Item ptr a, Item ptr b) -> int {\n"
        "    return a.clave - b.clave;\n"
        "}\n")


def _ejecuta(fuente: str):
    """En el INTERPRETE, explicito: la VM y el target web todavia no conocen
    '__cmp__' ni la igualdad de valor, y con la VM construida '--run' a secas
    correria alli."""
    return run_source(fuente, args=["--run", "interpreter"])


def _run(body: str, expected: str, extra: str = "") -> None:
    code, out, err = _ejecuta(W + extra + "\nfn main() -> int {\n" + body
                              + "\n    return 0;\n};\n")
    assert code == 0 and expected in out, (
        f"salida esperada no encontrada (salida {code}).\n"
        f"  esperado: {expected!r}\n  stdout:   {out!r}\n  stderr:   {err!r}")


# --------------------------------------------------------------------------- #
# '==' es igualdad de valor
# --------------------------------------------------------------------------- #

def test_una_copia_de_un_struct_es_igual_al_original():
    """El caso que motivo el cambio: 'b = a' COPIA (semantica de valor), y
    compararlos daba 'false' porque se comparaban dos objetos de Python."""
    _run('    var P a = P{ x: 1, y: 2 };\n'
         '    var P b = a;\n'
         '    __write__(f"{a == b} {a != b}\\n");',
         "true false\n", extra=P)


def test_dos_literales_con_los_mismos_campos_son_iguales():
    _run('    var P a = P{ x: 1, y: 2 };\n'
         '    __write__(f"{a == P{ x: 1, y: 2 }} {a == P{ x: 1, y: 3 }}\\n");\n'
         '    __write__(f"{a != P{ x: 9, y: 2 }}\\n");',
         "true false\ntrue\n", extra=P)


def test_la_igualdad_baja_por_los_campos_anidados():
    """Recursiva: un struct dentro de otro se compara por sus campos, y una
    cadena por su texto."""
    _run('    var L a = L{ desde: P{ x: 1, y: 2 }, nombre: "uno" };\n'
         '    var L b = L{ desde: P{ x: 1, y: 2 }, nombre: "uno" };\n'
         '    var L c = L{ desde: P{ x: 1, y: 5 }, nombre: "uno" };\n'
         '    __write__(f"{a == b} {a == c}\\n");',
         "true false\n",
         extra=P + "struct { P desde; str nombre; } L;\n")


def test_un_enum_suma_se_compara_por_variante_y_payload():
    _run('    var Forma f = Forma.Circulo(3);\n'
         '    __write__(f"{f == Forma.Circulo(3)} {f == Forma.Circulo(4)}\\n");\n'
         '    __write__(f"{f == Forma.Rect(3, 3)} {f != Forma.Nada}\\n");\n'
         '    __write__(f"{Forma.Rect(1, 2) == Forma.Rect(1, 2)} '
         '{Forma.Nada == Forma.Nada}\\n");',
         "true false\nfalse true\ntrue true\n", extra=FORMA)


def test_dos_variantes_con_el_mismo_payload_son_distintas():
    """La variante es parte del valor: 'Entrada(3)' no es 'Salida(3)', aunque
    lleven lo mismo."""
    _run('    __write__(f"{Mov.Entrada(3) == Mov.Salida(3)} '
         '{Mov.Entrada(3) == Mov.Entrada(3)}\\n");',
         "false true\n",
         extra="enum Mov { Entrada(int), Salida(int), };\n")


def test_un_eq_declarado_sigue_mandando():
    """'__eq__' gana sobre la igualdad de valor: aqui solo mira 'x'. Y '!='
    es su negacion, no otra comparacion."""
    _run('    var P a = P{ x: 1, y: 2 };\n'
         '    var P b = P{ x: 1, y: 99 };\n'
         '    __write__(f"{a == b} {a != b}\\n");',
         "true false\n",
         extra=P + "hook fn __eq__(P ptr a, P ptr b) -> bool { return a.x == b.x; }\n")


def test_un_campo_con_eq_propio_lo_usa_dentro_de_la_igualdad_de_valor():
    """La igualdad campo a campo respeta el '__eq__' de cada campo: el
    contenedor no sabe mas que su campo de lo que significa 'igual'."""
    _run('    var L a = L{ desde: P{ x: 1, y: 2 }, n: 7 };\n'
         '    var L b = L{ desde: P{ x: 1, y: 50 }, n: 7 };\n'
         '    __write__(f"{a == b}\\n");',
         "true\n",
         extra=P + "hook fn __eq__(P ptr a, P ptr b) -> bool { return a.x == b.x; }\n"
                   "struct { P desde; int n; } L;\n")


def test_un_campo_puntero_se_compara_por_la_direccion():
    """Decision: un puntero dentro de un campo compara la DIRECCION, no lo
    apuntado. Dos structs que apuntan a la misma variable son iguales; si
    apuntan a dos variables que valen lo mismo, no."""
    _run('    var int n = 5;\n'
         '    var int m = 5;\n'
         '    var R a = R{ p: &n };\n'
         '    var R b = R{ p: &n };\n'
         '    var R c = R{ p: &m };\n'
         '    __write__(f"{a == b} {a == c}\\n");',
         "true false\n",
         extra="struct { int ptr p; } R;\n")


def test_dos_punteros_a_la_misma_variable_son_iguales():
    """'&n == &n' daba false: cada '&' creaba un envoltorio nuevo y se
    comparaban los envoltorios, no la celda."""
    _run('    var int n = 1;\n'
         '    var int m = 1;\n'
         '    int ptr p = &n;\n'
         '    __write__(f"{p == &n} {p == &m} {p != &m}\\n");',
         "true false true\n")


def test_un_generico_compara_su_T_por_valor():
    _run('    __write__(f"{igual<P>(P{ x: 1, y: 2 }, P{ x: 1, y: 2 })}\\n");\n'
         '    __write__(f"{igual<Forma>(Forma.Rect(1, 2), Forma.Rect(2, 1))}\\n");',
         "true\nfalse\n",
         extra=P + FORMA + "fn igual<T>(T a, T b) -> bool { return a == b; }\n")


# --------------------------------------------------------------------------- #
# '__cmp__' ordena un tipo nominal
# --------------------------------------------------------------------------- #

def test_cmp_da_los_cuatro_operadores_de_orden():
    _run('    var Item a = Item{ clave: 1, nombre: "a" };\n'
         '    var Item b = Item{ clave: 2, nombre: "b" };\n'
         '    var Item c = Item{ clave: 1, nombre: "c" };\n'
         '    __write__(f"{a < b} {a <= b} {a > b} {a >= b}\\n");\n'
         '    __write__(f"{a < c} {a <= c} {a > c} {a >= c}\\n");\n'
         '    __write__(f"{b < a} {b > a}\\n");',
         "true true false false\nfalse true false true\nfalse true\n",
         extra=ITEM)


def test_cmp_sobre_un_enum_suma():
    _run('    __write__(f"{Forma.Circulo(1) < Forma.Rect(2, 2)} '
         '{Forma.Rect(2, 2) < Forma.Rect(1, 1)}\\n");',
         "true false\n",
         extra=FORMA + (
             "fn area(Forma ptr f) -> int {\n"
             "    match (f) {\n"
             "        case Forma.Circulo(r) { return 3 * r * r; };\n"
             "        case Forma.Rect(a, b) { return a * b; };\n"
             "        case Forma.Nada { return 0; };\n"
             "    };\n"
             "    return 0;\n"
             "}\n"
             "hook fn __cmp__(Forma ptr a, Forma ptr b) -> int {\n"
             "    return area(a) - area(b);\n"
             "}\n"))


def test_un_enum_sin_datos_se_ordena_por_su_valor():
    """Es un entero (sin payload no hay otra cosa que comparar): se ordena
    como uno, por el valor de su variante."""
    _run('    __write__(f"{Color.ROJO < Color.AZUL} {Color.AZUL <= Color.VERDE}\\n");',
         "true false\n",
         extra="enum Color { ROJO, VERDE, AZUL, };\n")


def test_un_generico_ordena_su_T_con_el_tipo_concreto():
    """El mismo cuerpo ordena enteros, cadenas y un tipo con '__cmp__': lo
    que hace '<' lo decide el valor que llega."""
    _run('    var str s = menor<str>("pera", "higo");\n'
         '    __write__(f"{menor<int>(4, 2)} {s}\\n");\n'
         '    var Item m = menor<Item>(Item{ clave: 7, nombre: "x" },\n'
         '                             Item{ clave: 3, nombre: "y" });\n'
         '    __write__(f"{m.nombre}\\n");',
         "2 higo\ny\n",
         extra=ITEM + "fn menor<T>(T a, T b) -> T { if (b < a) { return b; } return a; }\n")


# --------------------------------------------------------------------------- #
# Vector.sort
# --------------------------------------------------------------------------- #

VEC = "#import array.vector as vec\n"


def _vec_texto() -> str:
    """Un helper del programa: imprime un Vector<int> como '[a b c]'."""
    return ("fn ver(vec.Vector<int> ptr v) -> void {\n"
            "    var str s = \"[\";\n"
            "    var int i = 0;\n"
            "    while (i < v.len()) {\n"
            "        if (i > 0) { s = s + \" \"; }\n"
            "        s = s + cast<str>(v.get(i));\n"
            "        i = i + 1;\n"
            "    }\n"
            "    __write__(s + \"]\\n\");\n"
            "}\n")


def test_sort_ordena_enteros():
    _run('    var vec.Vector<int> v = vec.dynamic<int>(2);\n'
         '    v.push(5); v.push(3); v.push(9); v.push(1); v.push(3); v.push(-2);\n'
         '    v.push(8);\n'
         '    v.sort();\n'
         '    ver(&v);',
         "[-2 1 3 3 5 8 9]\n", extra=VEC + _vec_texto())


def test_sort_de_casos_borde():
    """Vacio, uno, ya ordenado y al reves: la mezcla de abajo hacia arriba
    tiene que cerrar bien los tramos impares del final."""
    _run('    var vec.Vector<int> a = vec.make<int>(1);\n'
         '    a.sort(); ver(&a);\n'
         '    var vec.Vector<int> b = vec.make<int>(1);\n'
         '    b.push(7); b.sort(); ver(&b);\n'
         '    var vec.Vector<int> c = vec.dynamic<int>(1);\n'
         '    var int i = 0;\n'
         '    while (i < 5) { c.push(i); i = i + 1; }\n'
         '    c.sort(); ver(&c);\n'
         '    var vec.Vector<int> d = vec.dynamic<int>(1);\n'
         '    i = 6;\n'
         '    while (i > 0) { d.push(i); i = i - 1; }\n'
         '    d.sort(); ver(&d);',
         "[]\n[7]\n[0 1 2 3 4]\n[1 2 3 4 5 6]\n", extra=VEC + _vec_texto())


def test_sort_de_muchos_elementos_deja_cada_par_en_orden():
    """97 enteros pseudoaleatorios (un generador lineal, determinista): con
    tantos tramos de anchos distintos se ejercitan todas las mezclas, y el
    total de antes y de despues dice que no se perdio ni duplico nada."""
    _run('    var vec.Vector<int> v = vec.dynamic<int>(4);\n'
         '    var int x = 7;\n'
         '    var int suma = 0;\n'
         '    var int i = 0;\n'
         '    while (i < 97) {\n'
         '        x = (x * 1103515245 + 12345) % 1000;\n'
         '        if (x < 0) { x = -x; }\n'
         '        v.push(x); suma = suma + x;\n'
         '        i = i + 1;\n'
         '    }\n'
         '    v.sort();\n'
         '    var bool bien = v.len() == 97;\n'
         '    var int otra = v.get(0);\n'
         '    i = 1;\n'
         '    while (i < v.len()) {\n'
         '        if (v.get(i) < v.get(i - 1)) { bien = false; }\n'
         '        otra = otra + v.get(i);\n'
         '        i = i + 1;\n'
         '    }\n'
         '    __write__(f"{bien} {otra == suma}\\n");',
         "true true\n", extra=VEC)


def test_sort_ordena_cadenas():
    _run('    var vec.Vector<str> v = vec.dynamic<str>(1);\n'
         '    v.push("pera"); v.push("higo"); v.push("uva"); v.push("caqui");\n'
         '    v.sort();\n'
         '    __write__(f"{v.get(0)} {v.get(1)} {v.get(2)} {v.get(3)}\\n");',
         "caqui higo pera uva\n", extra=VEC)


def test_sort_es_estable():
    """Dos 'Item' con la misma clave conservan su orden de llegada: la
    mezcla toma de la izquierda ante un empate."""
    _run('    var vec.Vector<Item> v = vec.dynamic<Item>(1);\n'
         '    v.push(Item{ clave: 2, nombre: "b1" });\n'
         '    v.push(Item{ clave: 1, nombre: "a1" });\n'
         '    v.push(Item{ clave: 2, nombre: "b2" });\n'
         '    v.push(Item{ clave: 1, nombre: "a2" });\n'
         '    v.push(Item{ clave: 0, nombre: "z" });\n'
         '    v.push(Item{ clave: 2, nombre: "b3" });\n'
         '    v.sort();\n'
         '    var int i = 0;\n'
         '    while (i < v.len()) { __write__(v.get(i).nombre + " "); i = i + 1; }\n'
         '    __write__("\\n");',
         "z a1 a2 b1 b2 b3 \n", extra=VEC + ITEM)


def test_sort_mueve_elementos_con_destructor_sin_copiarlos():
    """'sort' no copia: mueve cada elemento con 'mem.take'. Con un 'R' que
    tiene destructor no es SEM038, y cada 'R' se destruye UNA vez, ya en su
    sitio ordenado, al morir el vector."""
    _run('    if (true) {\n'
         '        var vec.Vector<R> v = vec.dynamic<R>(1);\n'
         '        v.push(R{ n: 3 }); v.push(R{ n: 1 }); v.push(R{ n: 2 });\n'
         '        v.sort();\n'
         '        __write__("ordenado\\n");\n'
         '    };\n'
         '    __write__("fin\\n");',
         "ordenado\nlibera 3\nlibera 2\nlibera 1\nfin\n",
         extra=VEC + ("struct { int n; } R;\n"
                      "hook fn __free__(R ptr r) -> void { __write__(f\"libera {r.n}\\n\"); }\n"
                      "hook fn __cmp__(R ptr a, R ptr b) -> int { return a.n - b.n; }\n"))


def test_un_generico_del_usuario_puede_ordenar_un_vector_de_su_T():
    """El requisito 'T se ordena' viaja de 'Vector.sort' a 'ordenar': lo
    comprueba la instancia de 'ordenar', no su cuerpo."""
    _run('    var vec.Vector<int> v = vec.dynamic<int>(1);\n'
         '    v.push(2); v.push(1);\n'
         '    ordenar<int>(&v);\n'
         '    ver(&v);',
         "[1 2]\n",
         extra=VEC + _vec_texto()
         + "fn ordenar<T>(vec.Vector<T> ptr mutable v) -> void { v.sort(); }\n")


def test_dos_vectores_con_los_mismos_elementos_son_iguales():
    """'Vector' declara '__eq__': compara 'len' y elemento a elemento. Sin
    el, la igualdad de valor compararia la DIRECCION de su bloque, y una
    copia nunca seria igual a su original."""
    _run('    var vec.Vector<int> a = vec.dynamic<int>(4);\n'
         '    a.push(1); a.push(2);\n'
         '    var vec.Vector<int> b = vec.make<int>(9);\n'
         '    b.push(1); b.push(2);\n'
         '    var vec.Vector<int> c = a;\n'
         '    __write__(f"{a == b} {a == c}\\n");\n'
         '    b.push(3);\n'
         '    __write__(f"{a == b} {a != b}\\n");',
         "true true\nfalse true\n", extra=VEC)


# --------------------------------------------------------------------------- #
# un tipo sin orden no llega a ejecutarse
# --------------------------------------------------------------------------- #

def test_ordenar_un_vector_de_un_tipo_sin_cmp_no_compila():
    """El error es de compilacion (SEM039), en la llamada: nunca llega a
    ejecutarse una comparacion que no sabe hacer."""
    code, out, err = _ejecuta(
        W + VEC + P + "fn main() -> int {\n"
        "    var vec.Vector<P> v = vec.dynamic<P>(1);\n"
        "    v.sort();\n"
        "    return 0;\n};\n")
    assert code != 0
    assert "SEM039" in out + err, out + err

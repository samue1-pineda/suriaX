"""Drop automático: el valor se destruye al cerrar el ámbito que lo posee.

De punta a punta, porque eso es lo que demuestra que el modelo funciona: la
Semántica decide QUÉ hay que destruir (por el tipo), el HIR lo transporta, y
el intérprete lo ejecuta. Si cualquiera de los tres se lo salta, estos tests
no imprimen lo que esperan.

La decisión de diseño que más se prueba aquí es la repartición: la lista de
destrucciones es ESTÁTICA (la calcula el compilador) pero el drop NO es
incondicional — el runtime destruye solo lo que siga vivo, consultando el
estado de la celda, que es la misma que ya hace cumplir el use-after-move.
Gracias a eso un ``move`` dentro de un ``if`` sale correcto sin que el
frontend haga análisis de flujo: ``test_un_move_en_una_rama_...`` es el par de
casos que lo demuestra.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import assert_output, run_program, run_source  # noqa: E402

W = "fn __write__(str s) -> void;\n"
#: un tipo con destructor: imprime al morir, que es como se observa el drop.
R = ('struct { int id; } R;\n'
     'hook fn __free__(R ptr r) -> void { __write__(f"drop {r.id}\\n"); };\n')


def _run(body: str, expected: str, extra: str = "") -> None:
    assert_output(W + R + extra + "\nfn main() -> int {\n" + body + "\n};\n",
                  expected)


#: un contenedor que POSEE otro con destructor. La regla (ver
#: ``scope_resolver._aplanar_drops``) es que quien declara ``__free__`` se
#: hace cargo también de sus campos — y por eso hace falta un aviso cuando se
#: olvida de uno.
_CONTENEDOR = (
    'struct {{ str n; R r; }} C;\n'
    'hook fn __free__(C ptr mutable c) -> void {{ __write__("cierro\\n"); {} }};\n'
)


# --------------------------------------------------------------------------- #
# lo básico
# --------------------------------------------------------------------------- #

def test_un_destructor_que_olvida_un_campo_lo_dice():
    """La regla "quien declara ``__free__`` se hace cargo de sus campos" es
    razonable pero SILENCIOSA: olvidar uno era una fuga que nada reportaba.

    Se avisa (``NOTE002``), no se rechaza: el campo podría soltarse por una
    vía que esta comprobación no ve."""
    code, _out, err = run_source(
        W + R + _CONTENEDOR.format("") +
        'fn main() -> int { var C c = C{ n: "x", r: R{ id: 1 } }; return 0; };\n')
    assert code == 0, err          # es un aviso, no un error
    assert "NOTE002" in err, err
    assert "'r'" in err, err


def test_un_destructor_que_si_lo_suelta_no_avisa():
    """Sin esto el aviso no valdría nada: uno que se disparara siempre
    tendría razón siempre y acabaría ignorándose."""
    code, out, err = run_program(
        W + R + _CONTENEDOR.format("free &c.r;") +
        'fn main() -> int { var C c = C{ n: "x", r: R{ id: 1 } }; return 0; };\n')
    assert code == 0, err
    assert "NOTE002" not in err, err
    # y el campo se destruye de verdad, que es lo que el aviso protege
    assert "drop 1" in out, (out, err)


def test_free_sobre_un_campo_dice_como_escribirlo():
    """``free c.r`` no compila (``free`` quiere un puntero) y la salida es
    ``&``. Sin decirlo, el caso más común del destructor de un contenedor
    parecía imposible."""
    code, _out, err = run_source(
        W + R + _CONTENEDOR.format("free c.r;") +
        'fn main() -> int { return 0; };\n')
    assert code != 0 and "SEM014" in err, err
    assert "free &c.r;" in err, err


def test_un_valor_con_dueno_se_destruye_al_cerrar_el_ambito():
    """Nadie escribe la destrucción: la inserta el compilador."""
    _run('var R a = R{ id: 1 };\n    __write__("fin\\n");',
         "fin\ndrop 1\n")


def test_un_tipo_sin_destructor_no_se_toca():
    _run('var P p = P{ v: 1 };\n    __write__("fin\\n");',
         "fin\n", extra="struct { int v; } P;\n")


def test_se_destruyen_en_orden_inverso_al_de_declaracion():
    """Lo último que nace es lo primero que muere: un valor puede depender de
    otro declarado antes que él."""
    _run('var R a = R{ id: 1 };\n    var R b = R{ id: 2 };\n'
         '    var R c = R{ id: 3 };',
         "drop 3\ndrop 2\ndrop 1\n")


def test_cada_bloque_destruye_lo_suyo():
    _run('var R fuera = R{ id: 1 };\n'
         '    if (true) { var R dentro = R{ id: 2 }; };\n'
         '    __write__("tras el if\\n");',
         "drop 2\ntras el if\ndrop 1\n")


# --------------------------------------------------------------------------- #
# la propiedad ya terminada: no se destruye dos veces
# --------------------------------------------------------------------------- #

def test_un_valor_movido_no_se_destruye():
    _run('var R m = R{ id: 1 };\n    move m;\n    __write__("fin\\n");',
         "fin\n")


def test_un_valor_liberado_no_se_destruye_otra_vez():
    """``free`` ya invocó al destructor; el cierre del ámbito no lo repite."""
    _run('var R f = R{ id: 1 };\n    var R ptr p = &f;\n    free p;\n'
         '    __write__("fin\\n");',
         "drop 1\nfin\n")


def test_un_move_en_una_rama_no_deja_fuga_ni_doble_destruccion():
    """El MISMO código, dos comportamientos, sin análisis de flujo en el
    frontend: la lista de drops es idéntica en los dos casos y quien decide es
    el estado de la celda en ejecución."""
    fuente = ('var R m = R{ id: 1 };\n'
              '    if (k) { move m; };\n'
              '    __write__("fin\\n");')
    # movido: no se destruye
    assert_output(W + R + "\nfn main() -> int {\n    var bool k = true;\n"
                  + fuente + "\n};\n", "fin\n")
    # no movido: se destruye
    assert_output(W + R + "\nfn main() -> int {\n    var bool k = false;\n"
                  + fuente + "\n};\n", "fin\ndrop 1\n")


# --------------------------------------------------------------------------- #
# salidas del bloque que no son la normal
# --------------------------------------------------------------------------- #

def test_un_return_temprano_tambien_destruye():
    """Si el drop solo corriera al final del bloque, cualquier ``return``
    anticipado sería una fuga."""
    assert_output(
        W + R + "\nfn f(bool k) -> void {\n"
        "    var R e = R{ id: 1 };\n"
        "    if (k) { return; };\n"
        '    __write__("siguio\\n");\n};\n'
        "fn main() -> int { f(true); f(false); return 0; };\n",
        "drop 1\nsiguio\ndrop 1\n")


def test_un_break_tambien_destruye():
    assert_output(
        W + R + "\nfn main() -> int {\n"
        "    var bool sigue = true;\n"
        "    while (sigue) { var R e = R{ id: 1 }; sigue = false; break; };\n"
        '    __write__("fin\\n");\n    return 0;\n};\n',
        "drop 1\nfin\n")


# --------------------------------------------------------------------------- #
# devolver transfiere la propiedad
# --------------------------------------------------------------------------- #

def test_devolver_un_valor_transfiere_su_propiedad():
    """Sin esta regla, el drop del bloque destruiría lo que el llamador acaba
    de recibir: se destruye una vez, y al morir el receptor."""
    assert_output(
        W + R + "\nfn crear() -> R {\n"
        "    var R d = R{ id: 1 };\n"
        "    return d;\n};\n"
        "fn main() -> int {\n"
        "    var R recibido = crear();\n"
        '    __write__("recibido\\n");\n    return 0;\n};\n',
        "recibido\ndrop 1\n")


# --------------------------------------------------------------------------- #
# campos: contener un dueño es ser dueño
# --------------------------------------------------------------------------- #

def test_un_struct_sin_destructor_propio_destruye_sus_campos():
    """'Caja' no declara ``__free__``: el compilador baja a los campos que sí
    poseen. Antes esto era un diagnóstico que rechazaba el programa."""
    _run('var Caja k = Caja{ b: R{ id: 1 }, n: 0 };',
         "drop 1\n", extra="struct { R b; int n; } Caja;\n")


def test_el_drop_de_campos_es_recursivo_y_en_orden_inverso():
    _run('var E e = E{ c: Caja{ b: R{ id: 1 }, n: 0 }, suelto: R{ id: 2 } };',
         "drop 2\ndrop 1\n",
         extra=("struct { R b; int n; } Caja;\n"
                "struct { Caja c; R suelto; } E;\n"))


def test_un_literal_anidado_no_es_un_temporal():
    """El valor pasa a ser el CAMPO del literal que lo envuelve: su dueño es
    ese struct, no la sentencia. Destruirlo ahí lo mataría recién nacido."""
    _run('var Caja k = Caja{ b: R{ id: 1 }, n: 0 };\n'
         '    __write__("vivo\\n");',
         "vivo\ndrop 1\n", extra="struct { R b; int n; } Caja;\n")


def test_un_campo_movido_no_se_destruye_con_su_contenedor():
    """'move p.a' invalida la celda de ESE campo; el hermano muere normal."""
    _run('var Par p = Par{ a: R{ id: 1 }, b: R{ id: 2 } };\n    move p.a;',
         "drop 2\n", extra="struct { R a; R b; } Par;\n")


def test_devolver_un_campo_transfiere_solo_ese_campo():
    assert_output(
        W + R + "struct { R a; R b; } Par;\n"
        "fn extrae() -> R {\n"
        "    var Par p = Par{ a: R{ id: 1 }, b: R{ id: 2 } };\n"
        "    return p.a;\n};\n"
        "fn main() -> int {\n"
        "    var R r = extrae();\n"
        '    __write__("recibido\\n");\n    return 0;\n};\n',
        "drop 2\nrecibido\ndrop 1\n")


# --------------------------------------------------------------------------- #
# temporales: un valor que nadie recibe muere al cerrar la sentencia
# --------------------------------------------------------------------------- #

def test_un_literal_pasado_como_argumento_se_destruye():
    assert_output(
        W + R + "fn recibe(R x) -> void { __write__(\"dentro\\n\"); };\n"
        "fn main() -> int { recibe(R{ id: 1 }); "
        '__write__("despues\\n"); return 0; };\n',
        "dentro\ndrop 1\ndespues\n")


def test_un_resultado_de_llamada_descartado_se_destruye():
    assert_output(
        W + R + "fn crear() -> R { var R t = R{ id: 1 }; return t; };\n"
        'fn main() -> int { crear(); __write__("despues\\n"); return 0; };\n',
        "drop 1\ndespues\n")


def test_un_resultado_ligado_no_es_un_temporal():
    """Si lo recibe un binding, su dueño es ese binding: muere con él, no al
    cerrar la sentencia."""
    assert_output(
        W + R + "fn crear() -> R { var R t = R{ id: 1 }; return t; };\n"
        "fn main() -> int { var R x = crear(); "
        '__write__("vivo\\n"); return 0; };\n',
        "vivo\ndrop 1\n")


def test_un_valor_pasado_por_nombre_no_se_destruye_dos_veces():
    """Pasar un local por valor NO transfiere: lo destruye su dueño, una vez."""
    assert_output(
        W + R + "fn recibe(R x) -> void { };\n"
        "fn main() -> int { var R a = R{ id: 1 }; recibe(a); "
        '__write__("vivo\\n"); return 0; };\n',
        "vivo\ndrop 1\n")


# --------------------------------------------------------------------------- #
# regresión: el cuerpo vacío no es un prototipo
# --------------------------------------------------------------------------- #

def test_una_funcion_de_cuerpo_vacio_no_es_un_prototipo():
    """Un ``Block`` sin sentencias es indistinguible del valor por defecto en
    protobuf, así que ``fn f() { }`` viajaba SIN cuerpo y el intérprete la
    tomaba por un prototipo: fallaba con 'no tiene intrínseco registrado'."""
    assert_output(
        W + "fn vacia() -> void { };\n"
        'fn main() -> int { vacia(); __write__("ok\\n"); return 0; };\n',
        "ok\n")


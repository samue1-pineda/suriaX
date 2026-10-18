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


def test_un_destructor_que_lo_suelta_en_un_else_no_avisa():
    """Regresión (H9): la búsqueda de los 'free' miraba un campo inexistente
    ('else_block') y un 'free' en el 'else' —o al final de una cadena de
    'else if'— no contaba: salía un NOTE002 falso."""
    for cuerpo in ('if (c.n == "y") { } else { free &c.r; };',
                   'if (c.n == "y") { } else if (c.n == "z") { } else { free &c.r; };'):
        code, _out, err = run_source(
            W + R + _CONTENEDOR.format(cuerpo) +
            'fn main() -> int { var C c = C{ n: "x", r: R{ id: 1 } }; return 0; };\n')
        assert code == 0, err
        assert "NOTE002" not in err, (cuerpo, err)


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


def test_pasar_por_valor_algo_con_destructor_exige_move():
    """Pasar por nombre dejaba al llamador como dueño y ``move`` no dejaba a
    NADIE: el recurso se perdía en silencio. Ahora el parámetro por valor es
    el dueño, y cederlo se escribe (SEM032, la misma regla que un ``var``)."""
    code, _out, err = run_source(
        W + R + "fn recibe(R x) -> void { };\n"
        "fn main() -> int { var R a = R{ id: 1 }; recibe(a); return 0; };\n")
    assert code == 1, (code, err)
    assert "SEM032" in err, err
    assert "move a" in err and "R ptr" in err, err


def test_el_parametro_movido_se_destruye_al_salir_de_la_funcion():
    """El caso del bug: ``recibe(move a)`` no destruía nunca el valor."""
    assert_output(
        W + R + 'fn recibe(R x) -> void { __write__("dentro\\n"); };\n'
        "fn main() -> int { var R a = R{ id: 1 }; recibe(move a); "
        '__write__("vuelta\\n"); return 0; };\n',
        "dentro\ndrop 1\nvuelta\n")


def test_un_temporal_pasado_por_valor_se_destruye_una_vez():
    """El parámetro es su dueño: el llamador ya no lo suelta al terminar la
    sentencia (antes de la corrección salía 'drop 2' dos veces)."""
    assert_output(
        W + R + "fn recibe(R x) -> void { };\n"
        'fn main() -> int { recibe(R{ id: 2 }); __write__("fin\\n"); return 0; };\n',
        "drop 2\nfin\n")


def test_un_parametro_devuelto_cede_la_propiedad_al_llamador():
    assert_output(
        W + R + "fn pasa(R x) -> R { return move x; };\n"
        "fn main() -> int { var R a = R{ id: 3 }; var R b = pasa(move a); "
        '__write__("fin\\n"); return 0; };\n',
        "fin\ndrop 3\n")


def test_un_parametro_reenviado_se_destruye_donde_termina():
    assert_output(
        W + R + "fn final(R x) -> void { };\n"
        'fn reenvia(R x) -> void { final(move x); __write__("reenvia\\n"); };\n'
        "fn main() -> int { var R a = R{ id: 4 }; reenvia(move a); return 0; };\n",
        "drop 4\nreenvia\n")


def test_un_argumento_de_metodo_por_valor_tambien_se_transfiere():
    """``k.guarda(move r)``: la regla vale para los argumentos explícitos de
    un método; el receptor (implícito) no cambia."""
    assert_output(
        W + R + "struct { int n; } Caja;\n"
        "@impl Caja {\n"
        "    fn guarda(Caja ptr mutable self, R r) -> void { self.n = r.id; }\n"
        "}\n"
        "fn main() -> int { var Caja k = Caja{ n: 0 }; var R r = R{ id: 6 }; "
        'k.guarda(move r); __write__(f"caja {k.n}\\n"); return 0; };\n',
        "drop 6\ncaja 6\n")


def test_un_prestamo_no_transfiere_nada():
    """Para solo leer, el parámetro es ``ptr``: el llamador sigue siendo el
    dueño y lo destruye él, una vez."""
    assert_output(
        W + R + "fn lee(R ptr x) -> int { return x.id; };\n"
        'fn main() -> int { var R a = R{ id: 5 }; __write__(f"lee {lee(&a)}\\n"); '
        "return 0; };\n",
        "lee 5\ndrop 5\n")


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


# --------------------------------------------------------------------------- #
# no se cede lo que es de otro (SEM036)
# --------------------------------------------------------------------------- #

_CAJA = "struct { R dentro; } Caja;\n"


def test_ceder_algo_a_traves_de_un_puntero_es_sem036():
    """Un puntero es un PRESTAMO: lo que hay detras es de otro. Antes
    'move c.dentro' (y 'return'/'throw' de lo mismo) compilaba y el valor se
    destruia DOS veces: con el nuevo dueño y con la Caja."""
    for cuerpo in ("var R x = move c.dentro;",
                   "return c.dentro;",
                   "throw c.dentro;"):
        retorno = "R" if cuerpo.startswith("return") else "void"
        code, _out, err = run_program(
            W + R + _CAJA
            + f"fn f(Caja ptr mutable c) -> {retorno} {{ {cuerpo} }}\n"
            + "fn main() -> int { return 0; };")
        assert code != 0 and "SEM036" in err, (cuerpo, err)


def test_ceder_un_campo_PROPIO_sigue_valiendo():
    """Lo que no pasa por un puntero es propio y se puede ceder: el campo se
    destruye una vez, con su nuevo dueño."""
    _run("    if (true) {\n"
         "        var Caja c = Caja{ dentro: R{ id: 7 } };\n"
         "        var R x = move c.dentro;\n"
         '        __write__("movido\\n");\n'
         "    };\n"
         "    return 0;",
         "movido\ndrop 7\n", extra=_CAJA)


# --------------------------------------------------------------------------- #
# destruir POR TIPO: lo que el frontend no puede aplanar
# --------------------------------------------------------------------------- #

def test_un_parametro_generico_es_dueno_de_lo_que_recibe():
    """``toma<R>(R{...})``: con ``T = R`` la llamada exige ``move`` (SEM032),
    asi que el parametro es el dueño y lo destruye al salir. Antes ``T`` no
    se destruia nunca."""
    _run('    toma<R>(R{ id: 1 });\n    __write__("fin\\n");\n    return 0;',
         "drop 1\nfin\n", extra="fn toma<T>(T x) -> int { return 0; };\n")


def test_un_generico_que_devuelve_su_T_lo_cede():
    """Devolver un ``T`` local lo CEDE: si no, se destruiria lo que el
    llamador acaba de recibir."""
    _run('    var R d = devuelve<R>(R{ id: 2 });\n    __write__(f"tengo {d.id}\\n");\n'
         '    return 0;',
         "tengo 2\ndrop 2\n",
         extra="fn devuelve<T>(T x) -> T { var T y = move x; return y; };\n")


def test_un_catch_sin_tipo_destruye_lo_que_atrapa():
    """``catch (e)`` sin tipo: de que tipo es lo atrapado se sabe recien al
    ejecutar, y se destruye por ese tipo al cerrar la rama."""
    _run('    try { throw R{ id: 3 }; } catch (e) { __write__("atrapado\\n"); };\n'
         '    return 0;',
         "atrapado\ndrop 3\n")


def test_reasignar_destruye_el_valor_viejo():
    """``a = R{...}`` perdia el destructor del viejo (los dos motores solo
    soltaban su memoria). Vale igual para un campo."""
    _run('    var R a = R{ id: 4 };\n    a = R{ id: 5 };\n    __write__("medio\\n");\n'
         '    var Par p = Par{ x: R{ id: 6 } };\n    p.x = R{ id: 7 };\n'
         '    __write__("fin\\n");\n    return 0;',
         "drop 4\nmedio\ndrop 6\nfin\ndrop 7\ndrop 5\n",
         extra="struct { R x; } Par;\n")


def test_un_argumento_que_nadie_recibio_muere_si_otro_lanza():
    """``usa(move r, falla())``: el ``R`` ya salio de ``r`` pero la llamada
    nunca ocurrio. Muere en el desenrollado, ANTES que los locales (como en
    Rust), y no con el ambito de ``r``."""
    _run('    try {\n        var R a = R{ id: 1 };\n        var R r = R{ id: 2 };\n'
         '        usa(move r, falla());\n    } catch (e) { __write__("atrapado\\n"); };\n'
         '    return 0;',
         "drop 2\ndrop 1\natrapado\n",
         extra=('fn falla() -> int { throw "no"; };\n'
                'fn usa(R r, int x) -> int { return x; };\n'))


def test_soltar_un_bloque_destruye_sus_celdas():
    """Un bloque de ``mem`` POSEE sus celdas no vacias: ``release`` las
    destruye, de la ultima a la primera. ``b[i] = x`` destruye lo que habia."""
    _run('    var R ptr mutable b = mem.reserve<R>(3);\n    b[0] = R{ id: 1 };\n'
         '    b[2] = R{ id: 2 };\n    b[0] = R{ id: 3 };\n    mem.release<R>(b);\n'
         '    __write__("fin\\n");\n    return 0;',
         "drop 1\ndrop 2\ndrop 3\nfin\n", extra="#import mem\n")


_VECTOR = "#import array.vector as vec\n#import collections.dictionary as dic\n"


def test_un_vector_destruye_sus_elementos():
    """``Vector<R>`` es dueño de sus elementos: los destruye al morir, al
    reemplazarlos (``set``) y no los destruye al sacarlos (``pop``,
    ``take``). ``at`` los presta sin copiar."""
    _run('    var vec.Vector<R> v = vec.dynamic<R>(1);\n'
         '    v.push(R{ id: 1 });\n    v.push(R{ id: 2 });\n    v.push(R{ id: 3 });\n'
         '    __write__(f"at {v.at(1).id}\\n");\n'
         '    v.set(0, R{ id: 4 });\n'
         '    var R dos = v.take(1);\n    var R tres = v.pop();\n'
         '    __write__(f"sacados {dos.id} {tres.id}, quedan {v.len()}\\n");\n'
         '    return 0;',
         "at 2\ndrop 1\nsacados 2 3, quedan 1\ndrop 3\ndrop 2\ndrop 4\n",
         extra=_VECTOR)


def test_un_diccionario_destruye_al_reemplazar_y_al_quitar():
    _run('    var dic.Dictionary<str, R> d = dic.make<str, R>(2);\n'
         '    d.put("a", R{ id: 1 });\n    d.put("b", R{ id: 2 });\n'
         '    d.put("a", R{ id: 3 });\n    d.remove("b");\n'
         '    __write__(f"a = {d.at("a").id}\\n");\n    return 0;',
         "drop 1\ndrop 2\na = 3\ndrop 3\n", extra=_VECTOR)


def test_un_free_que_lanza_dentro_de_un_contenedor_es_rt021():
    """La regla de siempre —un destructor nunca lanza— vale tambien cuando
    lo corre el contenedor al morir."""
    code, out, err = run_program(
        W + 'struct { int id; } Q;\n'
        'fn lanza() -> void { throw "no"; };\n'
        'hook fn __free__(Q ptr q) -> void { lanza(); };\n'
        + _VECTOR +
        'fn main() -> int {\n    var vec.Vector<Q> v = vec.dynamic<Q>(1);\n'
        '    v.push(Q{ id: 1 });\n    return 0;\n};\n')
    assert code != 0 and "RT021" in out + err, (code, out, err)

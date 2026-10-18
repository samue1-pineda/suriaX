"""e2e/depurador — parar, mirar y seguir un programa en el intérprete.

El núcleo (``runtime/interpreter/depurador.py``) no sabe de editores: se le
da una función y él la llama cada vez que el programa se detiene. Aquí esa
función es un guion —"en esta parada mira esto y luego haz aquello"—, que es
como se prueba sin editor lo que después verá un editor.

Lo que se fija: dónde para (puntos, los tres pasos, la pausa), qué enseña (la
pila y las variables) y la columna que es de suriaX — el estado de
**propiedad** de cada variable: dueña, prestada, movida o liberada.
"""

from __future__ import annotations

import io
import contextlib
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _p in (_REPO, os.path.join(_REPO, "V0")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_PROGRAMA = """\
#from io #import stdp

struct { int x; int y; } Punto;

fn suma(int a, int b) -> int {
    var int total = a + b;
    return total;
}

fn area(Punto ptr p) -> int {
    return p.x * p.y;
}

fn main() -> int {
    var int n = suma(2, 3);
    var Punto p = Punto{ x: n, y: 4 };
    var int a = area(&p);
    var int i = 0;
    while (i < 3) {
        i = i + 1;
    }
    stdp.println(f"{a} {i}");
    return 0;
}
"""


def _depurar(fuente: str, guion, *, puntos=(), parar_al_entrar=False,
             errores=None, pruebas=False):
    """Corre ``fuente`` bajo el depurador. ``guion(dep, motivo, n)`` se llama
    en cada parada (``n`` desde 0) y dice cómo seguir. Devuelve
    ``(código de salida, lo que escribió el programa, paradas)``; cada parada
    es ``(motivo, función, línea)``."""
    from driver import CompileOptions, compile_source, execute
    from runtime.interpreter.depurador import Depurador

    paradas = []

    def al_parar(dep, motivo):
        marco = dep.marcos()[0]
        paradas.append((motivo, marco.nombre, marco.linea))
        assert len(paradas) < 200, "el guion no deja terminar al programa"
        guion(dep, motivo, len(paradas) - 1)

    with tempfile.TemporaryDirectory(prefix="suriax-dep-") as tmp:
        ruta = os.path.join(tmp, "prog.srcx")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(fuente)
        previo = os.getcwd()
        os.chdir(tmp)                   # los volcados, al temporal
        try:
            resultado = compile_source(ruta, CompileOptions(run="interpreter"))
            assert resultado.should_run, getattr(resultado, "diagnostics", None)
            dep = Depurador(al_parar, parar_al_entrar=parar_al_entrar)
            dep.pon_puntos(ruta, puntos)
            dep.para_en_errores(errores)
            salida = io.StringIO()
            with contextlib.redirect_stdout(salida), \
                    contextlib.redirect_stderr(io.StringIO()):
                codigo = execute(resultado, depurador=dep, pruebas=pruebas)
        finally:
            os.chdir(previo)
    return codigo, salida.getvalue(), paradas


def _seguir(dep, motivo, n):
    dep.sigue()


def _vars(variables) -> dict:
    return {v.nombre: (v.valor, v.propiedad) for v in variables}


# --------------------------------------------------------------------------- #
# dónde para
# --------------------------------------------------------------------------- #

def test_sin_puntos_el_programa_corre_igual():
    codigo, salida, paradas = _depurar(_PROGRAMA, _seguir)
    assert (codigo, salida, paradas) == (0, "20 3\n", [])


def test_para_en_un_punto_de_parada_y_sigue():
    codigo, salida, paradas = _depurar(_PROGRAMA, _seguir, puntos=[6, 22])
    assert paradas == [("breakpoint", "suma", 6), ("breakpoint", "main", 22)]
    assert (codigo, salida) == (0, "20 3\n")


def test_un_punto_dentro_de_un_bucle_para_en_cada_vuelta():
    """Volver a la misma línea ES llegar a ella otra vez."""
    _, _, paradas = _depurar(_PROGRAMA, _seguir, puntos=[20])
    assert paradas == [("breakpoint", "main", 20)] * 3


def test_parar_al_entrar_se_detiene_en_la_primera_sentencia():
    _, _, paradas = _depurar(_PROGRAMA, _seguir, parar_al_entrar=True)
    assert paradas == [("entry", "main", 15)]


def test_pasar_no_entra_en_la_funcion_que_se_llama():
    def guion(dep, motivo, n):
        dep.paso("pasar") if n < 2 else dep.sigue()

    _, _, paradas = _depurar(_PROGRAMA, guion, puntos=[15])
    assert paradas == [("breakpoint", "main", 15), ("step", "main", 16),
                       ("step", "main", 17)]


def test_entrar_si_entra_y_salir_vuelve_a_quien_llamo():
    def guion(dep, motivo, n):
        if n == 0:
            dep.paso("entrar")
        elif n == 1:
            dep.paso("salir")       # desde la PRIMERA línea de 'suma'
        else:
            dep.sigue()

    _, _, paradas = _depurar(_PROGRAMA, guion, puntos=[15])
    # salir no se detiene en lo que queda de 'suma' (la línea 7)
    assert paradas == [("breakpoint", "main", 15), ("step", "suma", 6),
                       ("step", "main", 16)]


def test_entrar_avanza_sentencia_a_sentencia_dentro_de_la_funcion():
    def guion(dep, motivo, n):
        dep.paso("entrar") if n < 3 else dep.sigue()

    _, _, paradas = _depurar(_PROGRAMA, guion, puntos=[15])
    assert paradas == [("breakpoint", "main", 15), ("step", "suma", 6),
                       ("step", "suma", 7), ("step", "main", 16)]


def test_dos_sentencias_en_una_linea_son_una_sola_parada():
    """Un punto de parada es de la LÍNEA: avanzar por ella no es volver a
    llegar. (Volver en un bucle sí lo es: ver la prueba del bucle.)"""
    fuente = ("fn main() -> int {\n"
              "    var int a = 1; var int b = 2; var int c = a + b;\n"
              "    return c;\n"
              "}\n")
    codigo, _, paradas = _depurar(fuente, _seguir, puntos=[2])
    assert paradas == [("breakpoint", "main", 2)] and codigo == 3


def test_un_punto_dentro_de_una_funcion_gana_a_pasar_por_encima():
    """Pasar por encima de una llamada no se salta lo que hay dentro."""
    def guion(dep, motivo, n):
        dep.paso("pasar") if n == 0 else dep.sigue()

    _, _, paradas = _depurar(_PROGRAMA, guion, puntos=[15, 7])
    assert paradas == [("breakpoint", "main", 15), ("breakpoint", "suma", 7)]


def test_la_pausa_detiene_en_la_siguiente_sentencia():
    def guion(dep, motivo, n):
        if n == 0:
            dep.pausa()             # como la pediría el editor, a destiempo
        dep.sigue()

    _, _, paradas = _depurar(_PROGRAMA, guion, puntos=[15])
    assert paradas[0] == ("breakpoint", "main", 15)
    assert paradas[1][0] == "pause" and len(paradas) == 2, paradas


# --------------------------------------------------------------------------- #
# qué enseña
# --------------------------------------------------------------------------- #

def test_la_pila_dice_quien_llamo_a_quien_y_por_donde_va():
    vista = {}

    def guion(dep, motivo, n):
        vista["pila"] = [(m.nombre, m.linea) for m in dep.marcos()]
        dep.sigue()

    _depurar(_PROGRAMA, guion, puntos=[11])
    assert vista["pila"] == [("area", 11), ("main", 17)]


def test_las_variables_a_la_vista_son_las_de_su_bloque_y_sus_padres():
    vistas = []

    def guion(dep, motivo, n):
        vistas.append(_vars(dep.locales(dep.marcos()[0])))
        dep.sigue()

    _depurar(_PROGRAMA, guion, puntos=[6, 7, 20])
    # en la línea 6 'total' todavía no existe; en la 7, sí
    assert vistas[0] == {"a": ("2", "dueña"), "b": ("3", "dueña")}
    assert vistas[1]["total"] == ("5", "dueña")
    # dentro del 'while' se ven las de 'main'
    assert vistas[2]["n"] == ("5", "dueña") and vistas[2]["i"] == ("0", "dueña")
    assert vistas[-1]["i"] == ("2", "dueña")


def test_un_struct_se_despliega_en_sus_campos():
    from runtime.interpreter.depurador import hijos

    vista = {}

    def guion(dep, motivo, n):
        p = dep.busca(dep.marcos()[0], "p")
        vista["p"] = (p.valor, p.propiedad, _vars(hijos(p.contenido)))
        dep.sigue()

    _depurar(_PROGRAMA, guion, puntos=[17])
    valor, propiedad, campos = vista["p"]
    assert propiedad == "dueña" and "Punto" in valor, valor
    assert campos == {"x": ("5", "dueña"), "y": ("4", "dueña")}


def test_un_puntero_es_un_prestamo_y_ensena_a_quien_mira():
    from runtime.interpreter.depurador import hijos

    vista = {}

    def guion(dep, motivo, n):
        p = dep.busca(dep.marcos()[0], "p")
        apuntado, = hijos(p.contenido)
        vista["p"] = (p.propiedad, apuntado.nombre,
                      _vars(hijos(apuntado.contenido)))
        dep.sigue()

    _depurar(_PROGRAMA, guion, puntos=[11])
    assert vista["p"] == ("prestada", "*",
                          {"x": ("5", "dueña"), "y": ("4", "dueña")})


_PROPIEDAD = """\
#from io #import stdp

struct { int v; } Caja;

hook fn __free__(Caja ptr mutable c) -> void {
    stdp.println("libre");
}

fn consume(Caja c) -> int {
    return c.v;
}

fn main() -> int {
    var Caja a = Caja{ v: 1 };
    var Caja b = Caja{ v: 2 };
    var int r = consume(move a);
    free &b;
    stdp.println(f"{r}");
    return 0;
}
"""


def test_la_propiedad_de_cada_variable_se_ve_cambiar():
    """Lo que ningún depurador genérico enseña: de quién es cada valor. El
    intérprete ya lleva esa cuenta —es la que hace cumplir el use-after-move
    y el use-after-free—; el depurador solo la deja ver."""
    vistas = []

    def guion(dep, motivo, n):
        v = _vars(dep.locales(dep.marcos()[0]))
        vistas.append({k: v[k][1] for k in ("a", "b") if k in v})
        dep.sigue()

    codigo, salida, _ = _depurar(_PROPIEDAD, guion, puntos=[16, 17, 18])
    assert vistas == [
        {"a": "dueña", "b": "dueña"},       # antes del 'move'
        {"a": "movida", "b": "dueña"},      # 'a' cedió su valor
        {"a": "movida", "b": "liberada"},   # 'b' se liberó con 'free'
    ], vistas
    assert codigo == 0 and salida.splitlines()[-1] == "1"


def test_mirar_una_variable_movida_no_la_lee():
    """Leerla sería el error que el lenguaje prohíbe (``RT`` de uso tras
    'move'): el depurador dice su estado sin tocarla, y el programa sigue."""
    vista = {}

    def guion(dep, motivo, n):
        a = dep.busca(dep.marcos()[0], "a")
        vista["a"] = (a.valor, a.propiedad, a.contenido)
        dep.sigue()

    codigo, _, _ = _depurar(_PROPIEDAD, guion, puntos=[17])
    assert vista["a"] == ("(movida)", "movida", None)
    assert codigo == 0


def test_los_globales_son_las_variables_no_las_funciones():
    fuente = ("#from io #import stdp\n"
              "var int contador = 7;\n"
              "fn main() -> int {\n"
              "    contador = contador + 1;\n"
              "    return 0;\n"
              "}\n")
    vista = {}

    def guion(dep, motivo, n):
        vista["g"] = _vars(dep.globales(dep.marcos()[0]))
        dep.sigue()

    _depurar(fuente, guion, puntos=[5])
    assert vista["g"] == {"contador": ("8", "dueña")}, vista["g"]


def test_un_punto_en_una_libreria_tambien_para():
    """Las unidades guardan su ruta pública (``<stdlib>/io/stdp.libsrx``)
    para que el ``.phir`` sea reproducible; el depurador la deshace."""
    from src.linker_p.resolver import stdlib_path

    stdp = os.path.join(stdlib_path(), "io", "stdp.libsrx")
    with open(stdp, encoding="utf-8") as fh:
        lineas = fh.read().splitlines()
    dentro = next(i + 2 for i, texto in enumerate(lineas)
                  if texto.startswith("public fn println("))
    vista = {}

    def guion(dep, motivo, n):
        vista.setdefault("pila", [m.nombre for m in dep.marcos()])
        dep.sigue()

    _, _, paradas = _depurar(_PROGRAMA, guion, puntos=[])
    assert paradas == []

    from runtime.interpreter import depurador as modulo
    original = modulo.Depurador.pon_puntos

    def con_libreria(self, ruta, puntos):
        original(self, ruta, puntos)
        original(self, stdp, [dentro])

    modulo.Depurador.pon_puntos = con_libreria
    try:
        _, _, paradas = _depurar(_PROGRAMA, guion)
    finally:
        modulo.Depurador.pon_puntos = original
    assert paradas and paradas[0][1] == "println", (paradas, dentro)
    assert vista["pila"][:2] == ["println", "main"]


# --------------------------------------------------------------------------- #
# parar donde el programa falla
#
# Cuando un error llega arriba del todo ya no queda nada que mirar: la pila
# se deshizo y las variables murieron. El depurador se detiene en la
# sentencia que falló, con todo intacto.
# --------------------------------------------------------------------------- #

_FALLA = """\
#from io #import stdp

fn divide(int a, int b) -> int {
    var int resto = a - b;
    return a / b;
}

fn main() -> int {
    var int cero = 0;
    var int r = divide(8, cero);
    stdp.println(f"{r}");
    return 0;
}
"""


def test_un_error_que_nadie_atrapa_detiene_donde_ocurre():
    vista = {}

    def guion(dep, motivo, n):
        vista["error"] = dep.error
        vista["pila"] = [(m.nombre, m.linea) for m in dep.marcos()]
        vista["locales"] = _vars(dep.locales(dep.marcos()[0]))
        dep.sigue()

    codigo, salida, paradas = _depurar(_FALLA, guion, errores="sin-atrapar")
    assert paradas == [("exception", "divide", 5)]
    assert vista["error"][0] == "EXC001" and "división por cero" in vista["error"][1]
    # la pila entera y las variables del marco que falló, todavía vivas
    assert vista["pila"] == [("divide", 5), ("main", 10)]
    assert vista["locales"] == {"a": ("8", "dueña"), "b": ("0", "dueña"),
                                "resto": ("8", "dueña")}
    # al seguir, el programa termina como habría terminado sin depurador
    assert (codigo, salida) == (70, "")


def test_sin_pedirlo_un_error_no_detiene():
    codigo, _, paradas = _depurar(_FALLA, _seguir)
    assert (codigo, paradas) == (70, [])


_ATRAPA = """\
#from io #import stdp

fn falla(int n) -> int {
    throw n;
}

fn main() -> int {
    var int r = 0;
    try {
        r = falla(7);
    } catch (int e) {
        r = e + 1;
    }
    stdp.println(f"{r}");
    return 0;
}
"""


def test_un_throw_que_un_catch_espera_no_detiene():
    """Aunque el ``try`` esté en QUIEN LLAMA: lo que cuenta es si alguien lo
    va a recibir, no dónde se lanza."""
    codigo, salida, paradas = _depurar(_ATRAPA, _seguir, errores="sin-atrapar")
    assert (codigo, salida, paradas) == (0, "8\n", [])


def test_con_todos_tambien_detiene_lo_que_se_atrapa():
    vista = {}

    def guion(dep, motivo, n):
        vista["error"] = dep.error
        dep.sigue()

    codigo, salida, paradas = _depurar(_ATRAPA, guion, errores="todos")
    assert paradas == [("exception", "falla", 4)]
    assert vista["error"] == ("throw", "throw 7")
    assert (codigo, salida) == (0, "8\n")     # y el 'catch' lo recibe igual


def test_un_throw_dentro_de_un_catch_ya_no_tiene_quien_lo_espere():
    fuente = _ATRAPA.replace("        r = e + 1;", "        throw e + 1;")
    _, _, paradas = _depurar(fuente, _seguir, errores="sin-atrapar")
    assert paradas == [("exception", "main", 12)]


def test_un_error_que_ningun_catch_puede_recibir_detiene_siempre():
    """Un error del runtime que no es una excepción del programa (aquí, una
    función que termina sin devolver) no lo atrapa ningún ``catch``: el
    ``try`` de alrededor no cuenta."""
    fuente = ("fn nada(int n) -> int {\n"
              "    if (n > 0) { return 1; }\n"
              "}\n"
              "fn main() -> int {\n"
              "    var int r = 0;\n"
              "    try {\n"
              "        r = nada(0);\n"
              "    } catch (e) {\n"
              "        r = 2;\n"
              "    }\n"
              "    return r;\n"
              "}\n")
    vista = {}

    def guion(dep, motivo, n):
        vista["error"] = dep.error[0]
        dep.sigue()

    codigo, _, paradas = _depurar(fuente, guion, errores="sin-atrapar")
    assert paradas == [("exception", "main", 7)] and vista["error"] == "RT017"
    assert codigo == 70


def test_un_error_detiene_una_sola_vez_aunque_suba_por_la_pila():
    """El mismo error pasa por cada sentencia de cada llamada mientras sube;
    es UN error."""
    _, _, paradas = _depurar(_FALLA, _seguir, errores="todos")
    assert len(paradas) == 1, paradas


def test_un_expect_que_falla_detiene_la_prueba_donde_fallo():
    fuente = ("fn doble(int n) -> int { return n + n; }\n"
              "fn main() -> int { return 0; }\n"
              'test "doble" {\n'
              "    var int r = doble(2);\n"
              "    expect (r == 5);\n"
              "}\n")
    vista = {}

    def guion(dep, motivo, n):
        vista["error"] = dep.error
        vista["locales"] = _vars(dep.locales(dep.marcos()[0]))
        dep.sigue()

    codigo, _, paradas = _depurar(fuente, guion, errores="sin-atrapar",
                                  pruebas=True)
    assert [(m, linea) for m, _, linea in paradas] == [("exception", 5)]
    assert vista["error"] == ("expect", "expect falló: r == 5")
    assert vista["locales"]["r"] == ("4", "dueña")
    assert codigo == 1


def test_el_nivel_de_modulo_de_una_libreria_se_atribuye_a_la_libreria():
    """Las sentencias de nivel superior de una librería corren antes de
    ``main``. El depurador las enseña en SU archivo."""
    import tempfile as tmpmod
    from driver import CompileOptions, compile_source, execute
    from runtime.interpreter.depurador import Depurador

    vista = {}

    def al_parar(dep, motivo):
        marco = dep.marcos()[0]
        vista.setdefault("donde", (os.path.basename(dep.ruta_de(marco.unidad)),
                                   marco.linea))
        dep.sigue()

    with tmpmod.TemporaryDirectory(prefix="suriax-dep-") as tmp:
        lib = os.path.join(tmp, "cosa.libsrx")
        with open(lib, "w", encoding="utf-8") as fh:
            fh.write("public var int base = 40;\n"
                     "public var int total = base + 2;\n"
                     "#export as cosa\n")
        ruta = os.path.join(tmp, "main.srcx")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write("#import cosa\nfn main() -> int { return cosa.total; }\n")
        previo = os.getcwd()
        os.chdir(tmp)
        try:
            resultado = compile_source(ruta, CompileOptions(run="interpreter"))
            assert resultado.should_run
            dep = Depurador(al_parar)
            dep.pon_puntos(lib, [2])
            with contextlib.redirect_stdout(io.StringIO()):
                codigo = execute(resultado, depurador=dep)
        finally:
            os.chdir(previo)
    assert vista.get("donde") == ("cosa.libsrx", 2), vista
    assert codigo == 42

"""e2e/memory — el modelo de memoria en ejecución, y sus LÍMITES actuales.

Dos mitades, ambas contrato:

1. **Lo que funciona**: ``&x`` produce un puntero a la CELDA de ``x``,
   la desreferencia es implícita en ``.campo``, se escribe a través de un
   ``ptr mutable``, ``move`` invalida el origen y ``free`` marca la celda —
   y los usos posteriores fallan en RUNTIME (``RT001``/``RT003``), que es
   justo la red para lo que el análisis estático lineal deja pasar a
   propósito.

2. **Lo que NO existe todavía** (``test_limite_*``): indexación, aritmética
   de punteros, ``sizeof`` sin hook y reserva dinámica. Se prueban
   como límites CONOCIDOS: cada uno debe fallar con un diagnóstico claro y
   nunca con un traceback. El día que se implemente uno, su test falla y
   señala exactamente qué mover — es un recordatorio ejecutable, no una
   afirmación de que la carencia sea deseable.

Las regiones se retiraron del lenguaje en v0.2.0; el modelo es ahora
ownership + drop + arenas de librería (``documentation/source/memory_model.rst``).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import assert_output, run_program  # noqa: E402

W = "fn __write__(str s) -> void;\n"
B = "struct { int v; } B;\n"


def _run(body: str, expected: str, extra: str = "") -> None:
    assert_output(W + extra + "\nfn main() -> int {\n" + body + "\n};\n", expected)


def _fails(source: str) -> tuple:
    """Ejecuta y exige que falle SIN traceback. Devuelve (code, stderr)."""
    code, _out, err = run_program(W + source)
    assert code != 0, "se esperaba un fallo controlado"
    assert "Traceback" not in err, f"error no controlado:\n{err}"
    return code, err


# --------------------------------------------------------------------------- #
# punteros: '&', deref implícito, escritura a través de 'ptr mutable'
# --------------------------------------------------------------------------- #

def test_direccion_y_desreferencia_implicita():
    _run('var B b = B{ v: 5 };\n    var B ptr p = &b;\n'
         '    __write__(f"{p.v}\\n");', "5\n", extra=B)


def test_escritura_a_traves_de_puntero_mutable():
    _run('var B b = B{ v: 1 };\n    var B ptr mutable p = &b;\n'
         '    p.v = 9;\n    __write__(f"{b.v}\\n");', "9\n", extra=B)


def test_el_puntero_apunta_a_la_celda_no_a_una_copia():
    """Dos punteros a la misma variable ven la MISMA celda."""
    _run('var B b = B{ v: 1 };\n'
         '    var B ptr mutable p = &b;\n    var B ptr q = &b;\n'
         '    p.v = 7;\n    __write__(f"{q.v}\\n");', "7\n", extra=B)


def test_puntero_como_parametro_muta_el_original():
    _run('var B b = B{ v: 1 };\n    bump(&b);\n    bump(&b);\n'
         '    __write__(f"{b.v}\\n");', "3\n",
         extra=B + "fn bump(B ptr mutable p) -> void { p.v = p.v + 1; };\n")


def test_recorrido_de_una_lista_enlazada():
    _run("""    var N c = N{ v: 3, next: null };
    var N b = N{ v: 2, next: &c };
    var N a = N{ v: 1, next: &b };
    var N ptr? cur = &a;
    while (cur != null) {
        __write__(f"{cur.v} ");
        cur = cur.next;
    };
    __write__("\\n");
    return 0;""", "1 2 3 \n",
         extra="struct { int v; N ptr? next; } N;\n")


def test_desreferenciar_null_es_error_de_runtime():
    code, err = _fails(B + "fn main() -> int { var B ptr? p = null; "
                           '__write__(f"{p.v}\\n"); return 0; };')
    assert code == 70, f"exit={code}"


# --------------------------------------------------------------------------- #
# move y free: la celda cambia de ESTADO
# --------------------------------------------------------------------------- #

def test_move_transfiere_y_marca_la_celda():
    _run('var B a = B{ v: 1 };\n    var B c = a;\n    move a;\n'
         '    __write__(f"{c.v}\\n");', "1\n", extra=B)


def test_usar_despues_de_free_falla_en_runtime():
    """RT003: lo que el análisis estático lineal no ve (a través de ramas)."""
    code, err = _fails(B + "fn main() -> int { var B b = B{ v: 1 }; "
                           'var B ptr p = &b; free p; __write__(f"{b.v}\\n"); return 0; };')
    assert code == 70, f"exit={code}"
    assert "RT003" in err, err


def test_free_sobre_algo_que_no_es_puntero_se_diagnostica():
    _fails("fn main() -> int { var int x = 1; free x; return 0; };")


# --------------------------------------------------------------------------- #
# límites CONOCIDOS: lo que falta para escribir 'vector' y 'alloc'
# --------------------------------------------------------------------------- #

def test_indexacion_sobre_bloque_reservado():
    """``buf[i]`` lee/escribe la celda i de un bloque de ``__reserve__``.

    Antes era un límite (RT011: sin tipos indexables); ahora es la base de un
    vector: reservar un bloque contiguo con la primitiva del host y acceder a
    sus elementos por índice, en lectura y en escritura.
    """
    _run('var int ptr mutable buf = __reserve__(3);\n'
         '    buf[0] = 7;\n    buf[1] = 8;\n'
         '    __write__(f"{buf[0] + buf[1]}\\n");', "15\n",
         extra="fn __reserve__(int n) -> int ptr mutable;\n")


def test_indexacion_fuera_de_rango_es_error():
    """EXC002 (antes RT013): acceder fuera de ``[0, tamaño)`` de un bloque reservado."""
    code, err = _fails("fn __reserve__(int n) -> int ptr mutable;\n"
                       "fn main() -> int { var int ptr mutable b = __reserve__(2); "
                       "b[5] = 1; return 0; };")
    assert code == 70, f"exit={code}"
    assert "EXC002" in err, err


def test_limite_no_hay_aritmetica_de_punteros():
    """'p + 1' no está definido: sin ella no se recorre un bloque contiguo."""
    _code, err = _fails("fn main() -> int { var int x = 1; var int ptr p = &x; "
                        "var int ptr q = p + 1; return 0; };")
    assert "AST006" in err, err


def test_limite_sizeof_exige_un_hook():
    """Sin ``__sizeof__`` el layout es cosa del backend: no hay tamaño nativo."""
    _code, err = _fails(B + "fn main() -> int { "
                            '__write__(f"{sizeof(B)}\\n"); return 0; };')
    assert "RT011" in err, err


def test_sizeof_con_hook_si_funciona():
    """La vía que SÍ existe: el tipo declara su propio '__sizeof__'."""
    _run('__write__(f"{sizeof(B)}\\n");', "8\n",
         extra=B + "hook fn __sizeof__(B ptr b) -> int { return 8; };\n")


def test_limite_region_ya_no_es_del_lenguaje():
    """Las regiones se retiraron en v0.2.0: 'region' dejo de ser palabra
    reservada, asi que 'region r { }' ni siquiera parsea. Antes parseaba y se
    rechazaba al emitir (HIR005); ahora el rechazo llega antes y mas barato."""
    _code, err = _fails("fn main() -> int { region r { var int x = 1; }; return 0; };")
    assert "HIR005" not in err, "el HIR ya no deberia ser quien lo rechaza"
    assert "PAR" in err, err


def test_limite_no_hay_reserva_dinamica():
    """'alloc' no es del lenguaje: es un nombre corriente, no una keyword ni
    una primitiva. La reserva cruda YA existe, pero por el hook ``__reserve__``
    (ver ``lib/mem`` y ``test_indexacion_sobre_bloque_reservado``), no por un
    ``alloc(...)`` mágico — que sigue siendo un nombre no definido (SEM001)."""
    _code, err = _fails("fn main() -> int { var int ptr p = alloc(10); return 0; };")
    assert "SEM001" in err, err

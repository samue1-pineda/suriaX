"""e2e/pruebas — ``test``, ``expect``, ``errfinally`` y ``finally``.

    test "nombre" { expect (condicion); } errfinally { ... } finally { ... }

Decisiones del mantenedor: ``expect`` es nativo y solo vale dentro de un
``test``; su bloque es opcional; uno que no se cumple CORTA la prueba y no lo
atrapa ningún ``catch``; ``errfinally`` (solo en un ``test``) corre si la
prueba falló y ``finally`` siempre, después; una prueba sin ``expect`` es un
error. Las pruebas corren con ``--test``, en el intérprete.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import run_source  # noqa: E402

_IO = "#from io #import stdp\n"
_MAIN = 'fn main() -> int { stdp.println("main"); return 0; }\n'


def _pruebas(fuente: str) -> tuple:
    """``(código, salida del programa, resultados)``: corre ``--test``."""
    code, out, err = run_source(_IO + fuente + _MAIN, args=["--test"])
    programa = [l for l in out.splitlines()
                if l and not l.startswith(("frontend OK", "HIR ", "  PASS", "  FAIL",
                                           "tests:"))
                and not (l.lstrip().startswith("unidad '") and " -> " in l)]
    resultados = [l.strip() for l in (out + err).splitlines()
                  if l.lstrip().startswith(("PASS", "FAIL"))]
    return code, programa, sorted(resultados)


def _codigos(fuente: str) -> list:
    _code, out, _err = run_source(fuente, args=["--emit-diagnostics"])
    return [d["code"] for d in json.loads(out)["diagnostics"]]


# --------------------------------------------------------------------------- #
# ejecutar
# --------------------------------------------------------------------------- #

def test_una_prueba_que_pasa():
    code, programa, resultados = _pruebas(
        'fn suma(int a, int b) -> int { return a + b; }\n'
        'test "suma" { expect (suma(2, 2) == 4); expect (true) { stdp.println("bloque"); } }\n')
    assert code == 0
    assert resultados == ["PASS  suma"]
    assert programa == ["bloque"]            # el bloque de un expect cumplido corre; 'main' no


def test_un_expect_que_falla_corta_la_prueba_y_dice_por_que():
    code, programa, resultados = _pruebas(
        'test "falla" { var int total = 7; expect (total == 10); stdp.println("NO"); }\n')
    assert code == 1
    assert programa == []                    # lo que sigue al expect no corre
    assert len(resultados) == 1 and resultados[0].startswith("FAIL  falla"), resultados
    # la condición como se escribió y los dos lados de la comparación
    assert "total == 10" in resultados[0] and "izquierda: 7" in resultados[0] \
        and "derecha: 10" in resultados[0], resultados


def test_errfinally_solo_si_falla_y_finally_siempre_despues():
    code, programa, _r = _pruebas(
        'test "pasa" { expect (true); } errfinally { stdp.println("ef pasa"); }'
        ' finally { stdp.println("f pasa"); }\n'
        'test "falla" { expect (false); } errfinally { stdp.println("ef falla"); }'
        ' finally { stdp.println("f falla"); }\n')
    assert code == 1
    assert programa == ["f pasa", "ef falla", "f falla"]


def test_las_clausulas_son_opcionales_y_van_solas():
    code, programa, resultados = _pruebas(
        'test "solo finally" { expect (true); } finally { stdp.println("f"); }\n'
        'test "solo errfinally" { expect (false); } errfinally { stdp.println("ef"); }\n'
        'test "ninguna" { expect (true); }\n')
    assert code == 1
    assert programa == ["f", "ef"]
    assert [r[:4] for r in resultados] == ["FAIL", "PASS", "PASS"]


def test_un_catch_no_atrapa_un_expect_pero_el_finally_del_try_corre():
    code, programa, resultados = _pruebas(
        'test "no se rescata" {\n'
        '    try { expect (1 > 2); } catch (e) { stdp.println("atrapado"); }'
        ' finally { stdp.println("finally del try"); };\n'
        '    stdp.println("NO");\n}\n')
    assert code == 1
    assert programa == ["finally del try"]
    assert resultados[0].startswith("FAIL")


def test_un_throw_sin_atrapar_y_un_error_de_ejecucion_tambien_fallan():
    code, _programa, resultados = _pruebas(
        'test "throw" { expect (true); throw 7; } errfinally { stdp.println("ef"); }\n'
        'test "division" { var int cero = 0; expect (10 / cero == 1); }\n'
        'test "atrapado pasa" { try { throw 1; } catch (e) { }; expect (true); }\n')
    assert code == 1
    assert [r[:4] for r in resultados] == ["FAIL", "FAIL", "PASS"]


def test_los_locales_con_destructor_mueren_pase_o_falle():
    """Regresión: una prueba no anotaba sus destrucciones (un local con
    ``__free__`` no se destruía nunca). Y un ``expect`` que corta la prueba
    desenrolla los ámbitos: destruye lo vivo, de adentro hacia afuera, antes
    del ``errfinally``."""
    code, programa, _r = _pruebas(
        'struct { int id; } R;\n'
        'hook fn __free__(R ptr r) -> void { stdp.println(f"drop {r.id}"); }\n'
        'test "pasa" { var R a = R{ id: 1 }; expect (a.id == 1); }\n'
        'test "falla" { var R b = R{ id: 2 };\n'
        '    if (true) { var R c = R{ id: 3 }; expect (c.id == 99); } }'
        ' errfinally { stdp.println("ef"); }\n')
    assert code == 1
    assert programa == ["drop 1", "drop 3", "drop 2", "ef"]


def test_sin_el_flag_las_pruebas_no_corren():
    code, out, _err = run_source(
        _IO + 'test "x" { expect (false); } finally { stdp.println("f"); }\n' + _MAIN,
        args=["--run", "interpreter"])
    assert code == 0 and "main" in out and "FAIL" not in out and "\nf\n" not in out


# --------------------------------------------------------------------------- #
# lo que no compila
# --------------------------------------------------------------------------- #

def test_expect_solo_vale_dentro_del_cuerpo_de_un_test():
    assert _codigos('fn main() -> int { expect (1 == 1); return 0; }\n') == ["PAR013"]
    # tampoco en las cláusulas: corren cuando la prueba ya terminó
    assert _codigos('test "x" { expect (true); } finally { expect (true); }\n') == ["PAR013"]
    assert _codigos('test "x" { expect (true); } errfinally { expect (true); }\n') == ["PAR013"]


def test_una_prueba_sin_expect_no_compila():
    assert _codigos('test "vacia" { var int a = 1; }\n') == ["PAR029"]
    # uno dentro de un bloque anidado cuenta
    assert _codigos('test "si" { if (true) { expect (1 == 1); } }\n') == []


def test_la_condicion_de_un_expect_es_bool():
    assert _codigos('test "x" { expect (3); }\n') == ["AST006"]
    assert _codigos('test "x" { expect (nada == 1); }\n') == ["SEM001"]


def test_las_clausulas_van_en_orden_y_no_se_sale_de_ellas():
    assert _codigos('test "x" { expect (true); } finally { } errfinally { }\n') == ["PAR013"]
    assert _codigos('test "x" { expect (true); } errfinally { return; }\n') == ["PAR027"]
    # 'errfinally' no existe fuera de un test
    assert _codigos('fn main() -> int { try { } errfinally { } return 0; }\n')[0].startswith("PAR")


def test_una_prueba_rota_da_un_solo_error():
    """Regresión: la recuperación del parser descartaba la prueba rota hasta
    la llave de su cuerpo y dejaba las cláusulas sueltas: un PAR012 por
    cláusula además del error real."""
    assert _codigos('test "x" { expect (true) } errfinally { } finally { }\n'
                    'fn main() -> int { return 0; }\n') == ["PAR003"]


def test_expect_y_errfinally_son_palabras_reservadas():
    assert _codigos('fn main() -> int { var int expect = 1; return expect; }\n')[0].startswith("PAR")
    assert _codigos('fn main() -> int { var int errfinally = 1; return 0; }\n')[0].startswith("PAR")

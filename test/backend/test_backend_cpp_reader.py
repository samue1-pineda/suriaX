"""backend/backend_cpp: el lector C++ del HIR contra las vistas de Python.

Parte de ``test_backend_cpp.py`` (partido por tema); lo compartido esta en
``backend_cpp_support.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend_cpp_support import (  # noqa: E402
    _cargar,
    _con_referencia,
    _cpp,
    _en_el_path,
)

def test_la_vista_legible_es_identica_a_la_de_python():
    """La garantía central: el mismo .phir significa lo mismo para los dos."""
    def comprobar(binario, phir, _tmp):
        _en_el_path()
        from src.HIR.pretty import pretty
        esperada = pretty(_cargar(phir))
        obtenida = _cpp(binario, phir, "--pretty")
        assert obtenida.returncode == 0, obtenida.stderr
        if obtenida.stdout != esperada:
            esperadas = esperada.splitlines()
            obtenidas = obtenida.stdout.splitlines()
            for i, (want, got) in enumerate(zip(esperadas, obtenidas), 1):
                if want != got:
                    raise AssertionError(
                        "el lector C++ lee el HIR distinto que el de Python, "
                        f"línea {i}:\n  Python: {want!r}\n  C++   : {got!r}")
            raise AssertionError(
                "las dos vistas difieren en longitud "
                f"({len(esperadas)} vs {len(obtenidas)} líneas)")

    _con_referencia(comprobar)


def test_el_resumen_de_simbolos_es_identico_al_de_python():
    """La tabla de símbolos: lo otro que el lector tiene que reconstruir."""
    def comprobar(binario, phir, _tmp):
        _en_el_path()
        from runtime.interpreter.loader import summarize
        esperado = summarize(_cargar(phir)) + "\n"
        obtenido = _cpp(binario, phir, "--summary")
        assert obtenido.returncode == 0, obtenido.stderr
        assert obtenido.stdout == esperado, (
            "el resumen del lector C++ no coincide con el de Python:\n"
            f"--- Python ---\n{esperado}\n--- C++ ---\n{obtenido.stdout}")

    _con_referencia(comprobar)


def test_ningun_nodo_del_programa_de_referencia_queda_sin_handler():
    """El fail-fast del despacho: un nodo sin rama se ANOTA con su posición,
    nunca se salta. Es el equivalente C++ de ``_error_unsupported``."""
    def comprobar(binario, phir, _tmp):
        resultado = _cpp(binario, phir, "--verify")
        assert resultado.returncode == 0, (
            "el lector C++ no entendió algún nodo del programa de "
            f"referencia:\n{resultado.stderr}")

    _con_referencia(comprobar)


def test_liga_las_unidades_referenciadas():
    """El module linker: N unidades ligadas al cargar, transitivamente."""
    def comprobar(binario, phir, _tmp):
        resultado = _cpp(binario, phir, "--link")
        assert resultado.returncode == 0, resultado.stderr
        # el programa importa IO (paquete + stdp + stdpf) y d_types
        for alias in ("IO", "IO.stdp", "IO.stdpf", "d_types.dt_variables"):
            assert alias in resultado.stdout, (
                f"la unidad '{alias}' no se ligó:\n{resultado.stdout}")

    _con_referencia(comprobar)


def test_rechaza_una_schema_version_que_no_conoce():
    """Fail-fast de esquema: un .phir de otra versión no es 'casi correcto',
    es un artefacto cuyo significado cambió. Se rechaza ANTES de leer nada."""
    def comprobar(binario, phir, tmp):
        module = _cargar(phir)
        module.schema_version = 99
        futuro = os.path.join(tmp, "futuro.phir")
        with open(futuro, "wb") as fh:
            fh.write(module.SerializeToString(deterministic=True))

        resultado = _cpp(binario, futuro, "--summary")
        assert resultado.returncode != 0, (
            "el lector aceptó un HIR de una versión que no conoce")
        assert "99" in resultado.stderr and "schema_version" in resultado.stderr, (
            f"el rechazo no dice qué versión llegó:\n{resultado.stderr}")

    _con_referencia(comprobar)


def test_un_archivo_que_no_es_un_phir_no_revienta():
    """Bytes que no parsean: error con instrucción, no un crash."""
    def comprobar(binario, _phir, tmp):
        basura = os.path.join(tmp, "basura.phir")
        with open(basura, "wb") as fh:
            fh.write(b"\xff\xfe esto no es protobuf \x00\x01\x02")

        resultado = _cpp(binario, basura, "--summary")
        assert resultado.returncode != 0
        assert "Module HIR" in resultado.stderr, resultado.stderr

    _con_referencia(comprobar)

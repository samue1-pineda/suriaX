"""e2e/robustez_interprete — programas que el intérprete atendía mal.

Salieron de escribir programas grandes (cachés, colas de prioridad, almacenes
clave-valor) y de mutar programas al azar: un hook que se aceptaba y no se
llamaba, conversiones que acababan en un fallo interno, una reserva
imposible que tardaba minutos en fallar.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import run_source  # noqa: E402


def _corre(fuente: str):
    return run_source(fuente, args=["--run", "interpreter"])


# --------------------------------------------------------------------------- #
# el '__eq__' de un enum
# --------------------------------------------------------------------------- #

_CLAVE = """\
#from io #import stdp
#import collections.dictionary as dic

enum Clave { A(int), B };

hook fn __eq__(Clave ptr x, Clave ptr y) -> bool {
    match (x) {
        case Clave.A(a): { match (y) { case Clave.A(b): { return a == b; } case Clave.B: { return false; } } }
        case Clave.B: { match (y) { case Clave.A(b): { return false; } case Clave.B: { return true; } } }
    }
    return false;
}

hook fn __hash__(Clave ptr x) -> int {
    match (x) {
        case Clave.A(a): { return a; }
        case Clave.B: { return -1; }
    }
    return 0;
}

fn main() -> int {
    var dic.Dictionary<Clave, int> d = dic.make<Clave, int>(4);
    d.put(Clave.A(1), 10);
    d.put(Clave.A(1), 20);
    d.put(Clave.B, 30);
    stdp.println(f"{d.len()} {d.get(Clave.A(1))}");
    stdp.println(f"{Clave.A(3) == Clave.A(3)} {Clave.A(3) == Clave.A(4)}");
    return 0;
}
"""


def test_el_eq_de_un_enum_se_llama():
    """Se aceptaba al compilar y '==' no lo llamaba nunca, mientras 'hash'
    sí despachaba a su '__hash__': un diccionario con un enum de clave
    guardaba la misma clave dos veces y no encontraba ninguna."""
    codigo, salida, error = _corre(_CLAVE)
    assert codigo == 0, error[-500:]
    assert salida.splitlines()[-2:] == ["2 20", "true false"], salida


# --------------------------------------------------------------------------- #
# 'cast<char>' de un entero que no es un carácter
# --------------------------------------------------------------------------- #

def test_un_entero_que_no_es_un_caracter_no_se_convierte_en_char():
    """Fuera de 0..0x10FFFF era un fallo interno; un sustituto UTF-16 se
    convertía y reventaba al imprimirlo. Ahora es la excepción del programa
    ``ConversionInvalida``, que se puede atrapar."""
    for valor in ("1114112", "-1", "55296", "57343"):
        codigo, _, error = _corre(
            "fn main() -> int {\n"
            f"    var char c = cast<char>({valor});\n"
            "    return 0;\n"
            "}\n")
        assert codigo == 70 and "EXC004" in error, (valor, codigo, error[-300:])
        assert "ICE000" not in error, error

    codigo, salida, error = _corre(
        "#from io #import stdp\n"
        "#import excepciones as exc\n"
        "fn main() -> int {\n"
        "    var int n = 1114112;\n"
        "    try { var char c = cast<char>(n); }\n"
        '    catch (exc.ConversionInvalida e) { stdp.println("atrapada"); }\n'
        "    var char z = cast<char>(1114111);\n"
        "    var char a = cast<char>(65);\n"
        '    stdp.println(f"{a}");\n'
        "    return 0;\n"
        "}\n")
    assert codigo == 0, error[-300:]
    assert salida.splitlines()[-2:] == ["atrapada", "A"], salida


# --------------------------------------------------------------------------- #
# una reserva que no cabe
# --------------------------------------------------------------------------- #

def test_una_reserva_imposible_falla_en_el_acto():
    """Creaba las celdas una a una durante minutos (medido: 94 s) y acababa
    en un fallo interno por falta de memoria."""
    inicio = time.monotonic()
    codigo, _, error = _corre(
        "#import mem\n"
        "fn main() -> int {\n"
        "    var int ptr mutable b = mem.reserve<int>(9223372036854775807);\n"
        "    return 0;\n"
        "}\n")
    assert codigo == 70 and "RT023" in error, (codigo, error[-300:])
    assert time.monotonic() - inicio < 60, "tardó de más en fallar"

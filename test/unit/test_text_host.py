"""unit/text_host — las llamadas al host de 'lib/text', sin compilar nada.

Dos cosas que una prueba de punta a punta no puede recorrer entera:

- La COHERENCIA de las clases de caracteres en TODO Unicode: lo que
  'trim' recorta y lo que separa 'split_whitespace' es exactamente
  'is_space', y 'is_alnum' es exactamente 'is_alpha or is_digit'. La
  librería lo promete; aquí se comprueba carácter a carácter (1 114 112).
- Que 'lines' corta donde corta 'sistema.entrada.leer_linea', que la cuenta
  y el llenado de las partes coinciden, y que un mal uso de las llamadas
  es una excepción del PROGRAMA y no un error de Python que escapa.
"""

from __future__ import annotations

import io
import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _p in (_REPO, os.path.join(_REPO, "V0")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from runtime.interpreter import intrinsics  # noqa: E402
from runtime.interpreter.errors import IndexOutOfRangeError  # noqa: E402
from runtime.interpreter.memory.block import Block  # noqa: E402

_R = intrinsics.REGISTRY

#: textos con todo lo que hace dudar a un corte: vacíos, separadores en los
#: extremos, '\r' suelto, CRLF, espacios de Unicode, combinantes, astrales.
_MUESTRAS = [
    "", "a", "\n", "\r", "\r\n", "\n\n", "a\nb", "a\nb\n", "a\r\nb\r\n",
    "a\rb", "a\r\r\nb\r", " \t a  b\t", " x　y z\u0085",
    "x​y", "é ñ 😀\n𝐀\r\n", ",,a,,", "a<->b<->", "😀😀",
    "uno\fdos\vtres\x1cfin",
]


def _llenar(nombre: str, *args) -> list:
    """Lo que hace la librería: pide la cuenta, reserva y deja llenar."""
    n = _R["__cuenta_" + {"__partir__": "partes", "__palabras__": "palabras",
                          "__lineas__": "lineas"}[nombre] + "__"](*args)
    bloque = Block(max(n, 1))
    _R[nombre](*args, bloque, n)
    return [bloque.cells[i].read() for i in range(n)]


def test_trim_y_split_whitespace_usan_exactamente_is_space():
    distintos = []
    for cp in range(0x110000):
        c = chr(cp)
        espacio = _R["__es_espacio__"](c)
        if (espacio != (_R["__recorta__"](c) == "")
                or espacio != (_R["__recorta_inicio__"](c) == "")
                or espacio != (_R["__recorta_final__"](c) == "")
                or espacio != (_R["__cuenta_palabras__"](c) == 0)):
            distintos.append(hex(cp))
    assert not distintos, f"trim/split_whitespace y is_space no coinciden en: {distintos[:20]}"


def test_is_alnum_es_is_alpha_o_is_digit_en_todo_unicode():
    distintos = [hex(cp) for cp in range(0x110000)
                 if _R["__es_alfanumerico__"](chr(cp))
                 != (_R["__es_letra__"](chr(cp)) or _R["__es_digito__"](chr(cp)))]
    assert not distintos, f"is_alnum != is_alpha or is_digit en: {distintos[:20]}"


def test_is_digit_es_decimal_no_cualquier_numero():
    """'²', '①' y '½' son números para Python ('isdigit'/'isnumeric') pero
    no dígitos decimales: con ellos no se escribe un número en base diez."""
    assert all(_R["__es_digito__"](c) for c in "0789٣۵१")
    assert not any(_R["__es_digito__"](c) for c in "²①½ⅧaＡ")


def test_lines_corta_igual_que_leer_linea():
    """Leer un texto línea a línea por la entrada estándar y partirlo con
    'lines' da las mismas líneas."""
    try:
        for texto in _MUESTRAS:
            intrinsics.fijar_entrada(io.BytesIO(texto.encode("utf-8")))
            leidas = []
            while not _R["__entrada_terminada__"]():
                leidas.append(_R["__leer_linea__"]())
            assert _llenar("__lineas__", texto) == leidas, texto
    finally:
        intrinsics.fijar_entrada(None)


def test_la_cuenta_y_el_llenado_coinciden_y_split_es_el_de_python():
    for texto in _MUESTRAS:
        for sep in (",", "\n", "<->", "😀", "a", "\r\n"):
            assert _llenar("__partir__", texto, sep) == texto.split(sep), (texto, sep)
        assert _llenar("__palabras__", texto) == texto.split(), texto


def test_un_mal_uso_es_una_excepcion_del_programa():
    """Un bloque que no es bloque, una cuenta que no coincide o uno que no
    alcanza: 'IndiceFueraDeRango', nunca un 'TypeError' de Python. Y un
    separador vacío, que la librería no deja pasar, tampoco rompe aquí."""
    for llamada in (lambda: _R["__partir__"]("a,b", ",", None, 2),
                    lambda: _R["__partir__"]("a,b", ",", Block(5), 3),
                    lambda: _R["__lineas__"]("a\nb", Block(1), 2),
                    lambda: _R["__palabras__"]("a b", "no", 2)):
        try:
            llamada()
        except IndexOutOfRangeError:
            continue
        raise AssertionError("tenía que ser IndiceFueraDeRango")
    assert _R["__cuenta_partes__"]("abc", "") == 1
    assert _R["__apariciones__"]("abc", "") == 0

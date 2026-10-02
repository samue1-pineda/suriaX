"""unit/lexer — tokens, keywords, strings, comentarios y posiciones.

Contrato lexer -> parser: si un lexema cambia de ``TokenType`` o de posición,
el parser entero se rompe sin que ningún test de más arriba diga dónde.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import lex  # noqa: E402
from include.t_types import KEYWORDS, TokenType  # noqa: E402


def test_keywords_producen_su_tokentype():
    """CADA keyword de la tabla produce su TokenType (tabla = fuente de verdad)."""
    for lexeme, expected in KEYWORDS.items():
        tokens, errors = lex(lexeme)
        assert not errors, f"'{lexeme}' produjo errores léxicos: {errors}"
        assert tokens[0].type is expected, (
            f"'{lexeme}' -> {tokens[0].type}, se esperaba {expected}"
        )


def test_keywords_nuevas_del_manejo_de_errores():
    """error/try/catch/throw son keywords, no identificadores."""
    for lexeme, expected in (
        ("error", TokenType.ERRORTYPE), ("try", TokenType.TRY),
        ("catch", TokenType.CATCH), ("throw", TokenType.THROW),
        ("cast", TokenType.CAST), ("test", TokenType.TEST),
    ):
        tokens, _ = lex(lexeme)
        assert tokens[0].type is expected, f"'{lexeme}' -> {tokens[0].type}"


def test_alloc_ya_no_es_keyword():
    """'alloc' se retiró del lenguaje: hoy es un identificador normal."""
    tokens, errors = lex("alloc")
    assert not errors
    assert tokens[0].type is TokenType.IDENTIFIER, (
        f"'alloc' debería ser IDENTIFIER, es {tokens[0].type}"
    )


def test_literales_con_valor_parseado():
    tokens, _ = lex("42 3.5 true false null 'a'")
    assert tokens[0].type is TokenType.INT_LIT and tokens[0].value == 42
    assert tokens[1].type is TokenType.FLOAT_LIT and abs(tokens[1].value - 3.5) < 1e-9
    assert tokens[2].type is TokenType.TRUE
    assert tokens[3].type is TokenType.FALSE
    assert tokens[4].type is TokenType.NULL
    assert tokens[5].type is TokenType.CHAR_LIT and tokens[5].value == "a"


def test_posiciones_linea_columna():
    """ln/col son 1-based y sobreviven a saltos de línea."""
    tokens, _ = lex("int a;\nfloat b;")
    assert (tokens[0].ln, tokens[0].col) == (1, 1)
    float_tok = next(t for t in tokens if t.type is TokenType.FLOAT)
    assert float_tok.ln == 2, f"'float' debería estar en la línea 2, está en {float_tok.ln}"
    assert float_tok.col == 1


def test_comentarios_no_rompen_el_conteo_de_lineas():
    """Un bloque /- -/ multilínea no descuadra las posiciones posteriores."""
    tokens, _ = lex("// linea 1\n/- bloque\n   sigue -/\nint x;")
    int_tok = next(t for t in tokens if t.type is TokenType.INT)
    assert int_tok.ln == 4, f"'int' debería estar en la línea 4, está en {int_tok.ln}"


def test_fstring_interpolada_vs_plana():
    """Solo f"..." interpola; "..." es texto literal (opt-in del lexer)."""
    tokens, _ = lex('f"hola {nombre}!"')
    assert tokens[0].type is TokenType.STRING_LIT
    assert tokens[0].value.is_interpolated, "la f-string debería interpolar"

    tokens, _ = lex('"hola {nombre}!"')
    assert not tokens[0].value.is_interpolated, (
        "una cadena plana NO debe interpolar (las llaves son literales)"
    )


def test_literales_adyacentes_forman_uno_solo():
    """Como en C, C++ y Python: es la forma natural de partir un mensaje
    largo en varias líneas. Antes había que escribir '+', lo que pagaba en
    EJECUCIÓN algo que se sabe al leer el archivo."""
    tokens, errores = lex('"parte uno, "\n"parte dos"')
    assert not errores, [e.code for e in errores]
    assert len(tokens) == 2, "dos literales pegados son UN token (+ EOF)"
    assert tokens[0].type is TokenType.STRING_LIT
    assert tokens[0].value.flat() == "parte uno, parte dos"
    # el valor tiene la MISMA forma que si se hubiera escrito de una vez
    assert len(tokens[0].value.parts) == 1


def test_cada_literal_pegado_conserva_su_propia_regla():
    """El caso dudoso: pegar f"" con "". El prefijo gobierna SU literal, no
    la unión — si no, habría que mirar los vecinos para saber qué significa
    un literal."""
    tokens, _ = lex('f"vale {x} " "y {y} no"')
    assert tokens[0].value.is_interpolated, "la parte f sigue interpolando"
    # la parte plana viaja como texto, llaves incluidas
    assert "{y} no" in tokens[0].value.flat()

    tokens, _ = lex('"nada {x} " "aqui {y}"')
    assert not tokens[0].value.is_interpolated, (
        "dos cadenas planas pegadas siguen sin interpolar")


def test_los_caracteres_no_se_concatenan():
    """``'a' 'b'`` son CHAR_LIT, otro token: igual que en C, no se funden."""
    tokens, _ = lex("'a' 'b'")
    assert [t.type for t in tokens[:2]] == [TokenType.CHAR_LIT, TokenType.CHAR_LIT]


def test_la_posicion_del_literal_fundido_es_la_del_primero():
    """Un diagnóstico sobre el literal tiene que apuntar a donde empieza."""
    tokens, _ = lex('   "uno"\n   "dos"')
    assert (tokens[0].ln, tokens[0].col) == (1, 4), tokens[0]


def test_escapes_en_cadenas():
    tokens, _ = lex(r'"a\nb\tc"')
    assert tokens[0].value.flat() == "a\nb\tc"


def test_dunder_reconocido_por_forma():
    """El lexer reconoce la FORMA __x__ sin lista cerrada."""
    tokens, _ = lex("__cualquier_cosa__")
    assert tokens[0].type is TokenType.DUNDER


def test_flujo_termina_en_eof():
    tokens, _ = lex("int x;")
    assert tokens[-1].type is TokenType.EOF


def test_error_lexico_se_recupera_y_reporta():
    """Un carácter inválido produce diagnóstico pero NO detiene el tokenizado."""
    tokens, errors = lex("int x = §;")
    assert errors, "un carácter inválido debería reportarse"
    assert tokens[-1].type is TokenType.EOF, "el lexer debe llegar a EOF igual"


def test_un_digito_que_no_es_ascii_es_caracter_inesperado():
    """Regresion (ICE000): '²' y '٣' pasan 'str.isdigit()', asi que el lexer
    los trataba como numero y 'int()' reventaba con un ValueError. Un literal
    numerico de suriaX es solo de digitos ASCII; lo demas es LEX001.
    (Lo encontro el lexer del bootstrap: al reescribirlo en suriaX hubo que
    decidir QUE es un digito, y la V0 no lo habia decidido.)"""
    for texto in ("x = \u00b2;", "x = \u0663;"):
        tokens, errors = lex(texto)
        assert [e.code for e in errors] == ["LEX001"], (texto, errors)
        assert tokens[-1].type is TokenType.EOF

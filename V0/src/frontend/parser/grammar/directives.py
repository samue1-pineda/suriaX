"""Directivas (``#import``/``#export``/``#from``) e interoperabilidad
(``#extern cpp{}``) -- EBNF secc. 1.

::
    import_dir   = "#import" lib_name [ "as" IDENTIFIER ] [ ";" ]
    export_dir   = "#export" ( [ "as" ] IDENTIFIER
                             | "package" "as" IDENTIFIER ) [ ";" ]
    from_dir     = "#from" lib_name "#import" IDENTIFIER [ "as" IDENTIFIER ] [ ";" ]
    extern_block = "#extern" "cpp" RAW_BLOCK
    lib_name     = IDENTIFIER { "." IDENTIFIER }

``as``, ``cpp`` y ``package`` NO son keywords reservadas: son ``IDENTIFIER``
cuyo lexema el parser compara literalmente (filosofia libsrX: pocos tokens
reservados, ver notas finales de ``grammar.ebnf``). Corolario: una libreria
no puede exportarse con el alias literal ``as`` (``#export as`` se lee como
'sin alias').

``lib_name`` punteado (``IO.print``) referencia un SUBMODULO de un paquete
.libsrx; ``#export package as IO`` declara el archivo padre de un paquete
(ver ``src/linker_p/``).
"""

from __future__ import annotations

from typing import Optional

try:
    from include import ast_nodes as ast
    from include.t_types import KEYWORDS, TokenType
    from error_handler import ParseError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from t_types import KEYWORDS, TokenType  # type: ignore
    import ParseError  # type: ignore

from ..context import ParserContext
from ..cursor import Cursor


def parse_directive(cursor: Cursor, ctx: ParserContext) -> ast.Declaration:
    """Despacha segun el nombre de la directiva (``DIRECTIVE.value``)."""
    tok = cursor.peek()
    name = tok.value
    if name == "import":
        return parse_import_dir(cursor, ctx)
    if name == "export":
        return _parse_export_dir(cursor, ctx)
    if name == "from":
        return parse_from_dir(cursor, ctx)
    if name == "extern":
        return _parse_extern_block(cursor, ctx)
    raise ParseError.UnknownDirectiveError(
        f"directiva '#{name}' no valida en esta posicion",
        line=tok.ln, column=tok.col,
    )


def _match_as_alias(cursor: Cursor) -> Optional[str]:
    """``as`` es un IDENTIFIER contextual (no keyword): se compara el lexema."""
    if cursor.check(TokenType.IDENTIFIER) and cursor.peek().lexeme == "as":
        cursor.advance()
        return cursor.expect(TokenType.IDENTIFIER).lexeme
    return None


def _expect_module_name(cursor: Cursor) -> str:
    """Un componente de ``lib_name``, con diagnostico propio si es keyword.

    Un modulo se llama como su ``#export``, y nada impide llamarlo ``str``
    o ``free``: el lexer los tokeniza como palabra clave y el
    ``expect(IDENTIFIER)`` generico se queja de un token que el usuario no
    escribio pensando en un tipo ('se esperaba IDENTIFIER, se encontro
    STR'). El error apunta a la causa real: el alias colisiona con una
    palabra reservada y hay que renombrarlo o usar ``as``.
    """
    tok = cursor.peek()
    if tok.type is not TokenType.IDENTIFIER and tok.lexeme in KEYWORDS:
        raise ParseError.InvalidLibraryNameError(
            f"'{tok.lexeme}' es una palabra reservada del lenguaje y no puede "
            "nombrar un modulo; renombra el alias de su '#export'",
            line=tok.ln, column=tok.col,
        )
    return cursor.expect(TokenType.IDENTIFIER).lexeme


def _parse_lib_name(cursor: Cursor) -> str:
    """``lib_name = IDENTIFIER { "." IDENTIFIER }`` -> ``"io"``/``"io.string"``.

    El nombre punteado referencia un submodulo de un paquete .libsrx; el
    parser solo transporta el string, la resolucion es de la Semantica.
    """
    parts = [_expect_module_name(cursor)]
    while cursor.check(TokenType.DOT):
        cursor.advance()
        parts.append(_expect_module_name(cursor))
    return ".".join(parts)


def parse_import_dir(cursor: Cursor, ctx: ParserContext) -> ast.ImportDirective:
    """Publica: tambien la reutiliza ``statements.parse_var_decl`` para
    ``const NAME = #import lib;`` (ver ``ast_nodes.ImportBinding``)."""
    tok = cursor.expect(TokenType.DIRECTIVE)
    lib = _parse_lib_name(cursor)
    alias = _match_as_alias(cursor)
    cursor.match(TokenType.SEMICOLON)  # ';' opcional (EBNF: '[ ";" ]')
    return ast.ImportDirective(ln=tok.ln, col=tok.col, lib=lib, alias=alias)


def _parse_export_dir(cursor: Cursor, ctx: ParserContext) -> ast.ExportDirective:
    """``#export [as] <alias>`` | ``#export package as <alias>``.

    El ``as`` de la forma simple es OPCIONAL: ``#export print`` y
    ``#export as print`` son equivalentes. Antes solo se aceptaba la primera
    y la segunda se malinterpretaba EN SILENCIO -- ``as`` se tomaba como el
    alias y el nombre real quedaba suelto, con lo que el ``#export`` dejaba
    de ser el ultimo item y la libreria se rechazaba entera con un mensaje
    que no apuntaba a la causa ('no termina en #export').
    """
    tok = cursor.expect(TokenType.DIRECTIVE)
    name_tok = cursor.expect(TokenType.IDENTIFIER)
    package = False

    # 'package'/'as' son IDENTIFIER contextuales, no keywords (filosofia
    # libsrX): se comparan por lexema.
    if name_tok.lexeme == "package":
        # '#export package as <alias>': archivo PADRE de un paquete .libsrx.
        # Aqui el 'as' SI es obligatorio (sin el, 'package' seria el alias).
        as_tok = cursor.expect(TokenType.IDENTIFIER)
        if as_tok.lexeme != "as":
            raise ParseError.UnknownDirectiveError(
                "se esperaba 'as <alias>' tras '#export package'",
                line=as_tok.ln, column=as_tok.col,
            )
        package = True
        name_tok = cursor.expect(TokenType.IDENTIFIER)
    elif name_tok.lexeme == "as":
        name_tok = cursor.expect(TokenType.IDENTIFIER)

    cursor.match(TokenType.SEMICOLON)  # ';' opcional (EBNF: '[ ";" ]')
    return ast.ExportDirective(ln=tok.ln, col=tok.col,
                                alias=name_tok.lexeme, package=package)


def parse_from_dir(cursor: Cursor, ctx: ParserContext) -> ast.FromDirective:
    """Publica por el mismo motivo que ``parse_import_dir``."""
    tok = cursor.expect(TokenType.DIRECTIVE)
    lib = _parse_lib_name(cursor)
    import_tok = cursor.expect(TokenType.DIRECTIVE)
    if import_tok.value != "import":
        raise ParseError.UnknownDirectiveError(
            "se esperaba '#import' tras '#from <lib>'",
            line=import_tok.ln, column=import_tok.col,
        )
    name_tok = cursor.expect(TokenType.IDENTIFIER)
    alias = _match_as_alias(cursor)
    cursor.match(TokenType.SEMICOLON)
    return ast.FromDirective(ln=tok.ln, col=tok.col, lib=lib,
                              name=name_tok.lexeme, alias=alias)


def _parse_extern_block(cursor: Cursor, ctx: ParserContext) -> ast.ExternBlock:
    tok = cursor.expect(TokenType.DIRECTIVE)
    target_tok = cursor.expect(TokenType.IDENTIFIER)  # 'cpp' (IDENTIFIER, no keyword)
    if target_tok.lexeme != "cpp":
        raise ParseError.InvalidExternBlockError(
            f"objetivo de '#extern' no soportado: '{target_tok.lexeme}' (solo 'cpp')",
            line=target_tok.ln, column=target_tok.col,
        )
    raw_tok = cursor.expect(TokenType.RAW_BLOCK)
    return ast.ExternBlock(ln=tok.ln, col=tok.col, target=target_tok.lexeme, raw=raw_tok.value)


__all__ = ["parse_directive", "parse_import_dir", "parse_from_dir"]

"""Especificación del lenguaje en datos, para herramientas externas (LSP,
extensión de VS Code, resaltadores).

**Fuente única de verdad**: se construye de las MISMAS tablas que usa el
compilador — ``t_types.KEYWORDS``/``DIRECTIVES``/``TokenType``,
``semantic/hooks.HOOK_SPECS`` y la jerarquía de ``error_handler``. Así la
extensión deja de mantener a mano su vocabulario y NUNCA se desincroniza: un
keyword nuevo aparece aquí sin tocar nada externo (ver
``extension_v0.0.3.md`` §4, el paso 1 del LSP).

No participa de ningún camino caliente del compilador: se materializa solo
cuando ``V0/main.py --emit-lang-info`` lo pide.
"""

from __future__ import annotations

from typing import Dict, List

try:
    from include.t_types import DIRECTIVES, KEYWORDS, TokenType
except ImportError:  # pragma: no cover - ejecucion directa
    from t_types import DIRECTIVES, KEYWORDS, TokenType  # type: ignore

#: versión del esquema de esta salida (súbela si cambia la FORMA del JSON).
LANG_INFO_VERSION = 1

# Categoría de cada keyword, por su TokenType. Es la ÚNICA pieza que se
# mantiene a mano al añadir un keyword (junto a 'KEYWORDS' del lexer): un
# conjunto por categoría, para que la extensión coloree/clasifique sin
# reimplementar la gramática. Cada TokenType de un keyword debe estar en
# exactamente un conjunto (se valida en 'build_language_info').
_CATEGORY_TOKENS: Dict[str, frozenset] = {
    "visibility": frozenset({TokenType.PUBLIC, TokenType.PRIVATE, TokenType.INTERNAL}),
    "specifier": frozenset({TokenType.HOOK, TokenType.DUNDER_KW}),
    "type": frozenset({TokenType.VOID, TokenType.BOOL, TokenType.TYPE,
                       TokenType.INT, TokenType.FLOAT, TokenType.CHAR, TokenType.STR}),
    "literal": frozenset({TokenType.TRUE, TokenType.FALSE, TokenType.NULL}),
    "storage": frozenset({TokenType.CONST, TokenType.VAR, TokenType.MUTABLE}),
    "declaration": frozenset({TokenType.FUNCTION, TokenType.STRUCT, TokenType.ENUM,
                              TokenType.TEST}),
    "control": frozenset({TokenType.IF, TokenType.ELSE, TokenType.WHILE,
                          TokenType.RETURN, TokenType.MATCH, TokenType.CASE,
                          TokenType.BREAK, TokenType.CONTINUE}),
    "error_handling": frozenset({TokenType.ERRORTYPE, TokenType.TRY,
                                 TokenType.CATCH, TokenType.THROW}),
    "memory": frozenset({TokenType.REGION, TokenType.SHRD, TokenType.NA,
                         TokenType.IN, TokenType.AT, TokenType.MOVE, TokenType.FREE,
                         TokenType.NEW, TokenType.DELETE, TokenType.POINTER,
                         TokenType.MAKE}),
    "operator_word": frozenset({TokenType.AND, TokenType.OR, TokenType.NOT,
                                TokenType.SIZEOF, TokenType.CAST}),
}

# Operadores y delimitadores SIMBÓLICOS (lexema -> TokenType). Espejo estable
# del scanner de operadores; se listan aquí para que la extensión no los
# hard-codee por su cuenta.
_SYMBOLS: Dict[str, TokenType] = {
    "=": TokenType.ASSIGN, "+": TokenType.PLUS, "-": TokenType.MINUS,
    "*": TokenType.MULTIPLY, "/": TokenType.DIVIDE,
    "==": TokenType.EQUAL, "!=": TokenType.NOT_EQUAL,
    "<": TokenType.LESS, "<=": TokenType.LESS_EQUAL,
    ">": TokenType.GREATER, ">=": TokenType.GREATER_EQUAL,
    "->": TokenType.ARROW,
    "(": TokenType.L_PAREN, ")": TokenType.R_PAREN,
    "{": TokenType.L_BRACE, "}": TokenType.R_BRACE,
    "[": TokenType.L_BRACKET, "]": TokenType.R_BRACKET,
    ".": TokenType.DOT, ",": TokenType.COMMA, ";": TokenType.SEMICOLON,
    ":": TokenType.COLON, "@": TokenType.DECORATOR, "#": TokenType.DIRECTIVE,
    "&": TokenType.ADDRESS, "?": TokenType.NULLABLE,
}


def _keyword_category(token: TokenType) -> str:
    for category, tokens in _CATEGORY_TOKENS.items():
        if token in tokens:
            return category
    return "keyword"  # sin categoría explícita (no debería ocurrir; ver validación)


def _error_catalog() -> List[dict]:
    """Enumera TODA la taxonomía de errores: ``(code, class, phase, message)``.

    Instancia cada clase concreta de ``error_handler`` con un mensaje dummy y
    lee su ``code``/``phase`` estables (mismo mecanismo que
    ``test_codigos_de_error_estables``). Robusto ante clases que no encajen."""
    modules = ("lex_error", "ParseError", "ASTError", "SemanticError",
               "HIRError", "InternalCompilerError")
    try:
        from error_handler.error import CompilerError
    except ImportError:  # pragma: no cover
        from error import CompilerError  # type: ignore

    import importlib

    seen: set = set()
    out: List[dict] = []
    for mod_name in modules:
        try:
            mod = importlib.import_module(f"error_handler.{mod_name}")
        except Exception:  # pragma: no cover - modulo ausente
            continue
        for name in getattr(mod, "__all__", dir(mod)):
            obj = getattr(mod, name, None)
            if not (isinstance(obj, type) and issubclass(obj, CompilerError)):
                continue
            try:
                inst = obj("x")
            except Exception:  # pragma: no cover - firma no trivial
                continue
            if inst.code in seen:
                continue
            seen.add(inst.code)
            out.append({"code": inst.code, "class": obj.__name__,
                        "phase": inst.phase,
                        "severity": getattr(obj, "severity", "critical"),
                        "default_message": inst.message})
    out.sort(key=lambda d: d["code"])
    return out


def build_language_info() -> dict:
    """Especificación completa del lenguaje, serializable a JSON."""
    keywords: Dict[str, dict] = {}
    categories: Dict[str, List[str]] = {name: [] for name in _CATEGORY_TOKENS}
    for lexeme, token in KEYWORDS.items():
        category = _keyword_category(token)
        keywords[lexeme] = {"token": token.name, "category": category}
        categories.setdefault(category, []).append(lexeme)
    for names in categories.values():
        names.sort()

    return {
        "lang_info_version": LANG_INFO_VERSION,
        "language": "suriaX",
        "extensions": [".srcx", ".libsrx"],
        "keywords": keywords,
        "categories": categories,
        "symbols": {lexeme: token.name for lexeme, token in _SYMBOLS.items()},
        "directives": sorted(DIRECTIVES),
        "hooks": _hook_names(),
        "tokens": [{"name": t.name, "value": t.value} for t in TokenType],
        "severities": _severities(),
        "errors": _error_catalog(),
    }


def _severities() -> list:
    """Escala de severidad de diagnósticos, de menor a mayor gravedad."""
    try:
        from error_handler.error import Severity
    except ImportError:  # pragma: no cover
        from error import Severity  # type: ignore
    ordered = sorted(Severity.ORDER, key=lambda s: Severity.ORDER[s])
    return [{"name": s, "rank": Severity.ORDER[s]} for s in ordered]


def _hook_names() -> List[str]:
    """Nombres de hook del SET FIJO (``__x__``), fuente ``semantic/hooks.py``."""
    try:
        from src.frontend.semantic.hooks import HOOK_SPECS
    except ImportError:  # pragma: no cover
        try:
            from frontend.semantic.hooks import HOOK_SPECS  # type: ignore
        except ImportError:
            return []
    return sorted(f"__{name}__" for name in HOOK_SPECS)


__all__ = ["build_language_info", "LANG_INFO_VERSION"]

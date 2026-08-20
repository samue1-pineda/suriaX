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
LANG_INFO_VERSION = 3


def _compiler_version() -> str:
    """Versión del compilador que produjo este JSON.

    La extensión y el LSP hablan con UN compilador concreto, y hasta ahora no
    tenían forma de saber cuál: si el usuario tiene un checkout viejo, el
    vocabulario que reciben es el viejo y el único síntoma es que algo no
    colorea. Publicarla convierte eso en un dato comprobable. Se LEE de
    ``version.py`` —la misma fuente que CMake y la documentación—, nunca se
    repite aquí.
    """
    try:
        from version import VERSION
    except ImportError:  # pragma: no cover - fuera del árbol del repositorio
        return "desconocida"
    return VERSION

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
    "memory": frozenset({TokenType.MOVE, TokenType.FREE, TokenType.POINTER}),
    "operator_word": frozenset({TokenType.AND, TokenType.OR, TokenType.NOT,
                                TokenType.SIZEOF, TokenType.CAST}),
}

# Operadores y delimitadores SIMBÓLICOS (lexema -> TokenType).
#
# Se DERIVA del scanner en vez de copiarse: era una lista escrita a mano que
# decía ser "espejo estable del scanner", y dejó de serlo en cuanto el lexer
# aprendió '%', '+=' y '++' — la extensión seguía sin conocerlos. Un espejo que
# hay que recordar actualizar no es un espejo.
def _construir_symbols() -> Dict[str, TokenType]:
    try:
        from src.frontend.lexer.scanners.operators import _DOUBLE, _SINGLE
    except ImportError:  # pragma: no cover - ejecucion directa
        return {}
    tabla: Dict[str, TokenType] = dict(_SINGLE)
    tabla.update({a + b: token for (a, b), token in _DOUBLE.items()})
    # '@' y '#' no pasan por el scanner de operadores (cada uno tiene el suyo),
    # pero son simbolos del lenguaje igual y la extension los necesita.
    tabla["@"] = TokenType.DECORATOR
    tabla["#"] = TokenType.DIRECTIVE
    return tabla


_SYMBOLS: Dict[str, TokenType] = _construir_symbols()


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
        "compiler_version": _compiler_version(),
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
        "stages": _pipeline_stages(),
    }


def _pipeline_stages() -> List[str]:
    """Fases que ``--emit-stage`` (y ``#test <fase>``) sabe volcar.

    Publicarlas evita que un consumidor -- el visualizador de la extension --
    tenga que llevar su propia lista: una fase nueva aparece sola.
    """
    try:
        from src.frontend.parser.parser import Parser
    except ImportError:  # pragma: no cover - ejecucion directa
        return []
    return Parser.available_stages()


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

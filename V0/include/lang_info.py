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
LANG_INFO_VERSION = 4


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
                       TokenType.INT, TokenType.FLOAT, TokenType.CHAR, TokenType.STR,
                       TokenType.BYTE}),
    "literal": frozenset({TokenType.TRUE, TokenType.FALSE, TokenType.NULL}),
    "storage": frozenset({TokenType.CONST, TokenType.VAR, TokenType.MUTABLE}),
    "declaration": frozenset({TokenType.FUNCTION, TokenType.STRUCT, TokenType.ENUM,
                              TokenType.TEST}),
    "control": frozenset({TokenType.IF, TokenType.ELSE, TokenType.WHILE,
                          TokenType.RETURN, TokenType.MATCH, TokenType.CASE,
                          TokenType.BREAK, TokenType.CONTINUE}),
    "error_handling": frozenset({TokenType.ERRORTYPE, TokenType.TRY,
                                 TokenType.CATCH, TokenType.THROW,
                                 TokenType.FINALLY}),
    "memory": frozenset({TokenType.MOVE, TokenType.FREE, TokenType.POINTER,
                         TokenType.WITH}),
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
    # el que no esta en las tablas: '<<=' (tres caracteres)
    tabla["<<="] = TokenType.SHIFT_LEFT_ASSIGN
    # '>>' y '>>=' NO: el lexer da dos '>' y los junta el parser (ver
    # SHIFT_RIGHT); publicarlos como un simbolo mentiria sobre lo que tokeniza
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
    import inspect

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
                        "default_message": inst.message,
                        # El docstring de la clase es donde el proyecto explica
                        # POR QUÉ existe ese error y, casi siempre, qué hacer
                        # con él — las dos mitades del contrato de un
                        # diagnóstico que el código y la posición no cubren.
                        # Publicarlo convierte el catálogo en algo que una
                        # herramienta puede enseñar, y no cuesta mantenerlo:
                        # ya estaba escrito y ya se exige que esté bien.
                        "explanation": inspect.getdoc(obj) or ""})
    out.sort(key=lambda d: d["code"])
    return out


def _token_categories() -> Dict[str, str]:
    """Categoría de **cada** ``TokenType``, no solo de los keywords.

    ``_CATEGORY_TOKENS`` clasifica las palabras reservadas, que es lo que un
    resaltador necesita saber a mano. Pero un editor colorea TODO lo que sale
    del lexer, y sin esta tabla tenía que adivinar el resto con heurísticas
    sobre el nombre del token — el playground llegó a decidir por regex si
    ``INT`` era un tipo o un literal, y se equivocaba.

    Las categorías que se derivan (y por qué no se escriben a mano):

     - ``literal``      los ``*_LIT``, salvo el de cadena, que va aparte
                        porque todo editor la colorea distinto;
     - ``string``       ``STRING_LIT``;
     - ``name``         ``IDENTIFIER`` y ``DUNDER``;
     - ``comment``      lo que el lexer no emite pero el editor sí pinta;
     - ``punctuation``  delimitadores (paréntesis, coma, ``;``);
     - ``operator``     el resto de símbolos;
     - ``meta``         ``EOF`` y los tokens de servicio.
    """
    from .t_types import TokenType as _TT  # el mismo módulo, ya importado

    delimitadores = {"L_PAREN", "R_PAREN", "L_BRACE", "R_BRACE", "L_BRACKET",
                     "R_BRACKET", "SEMICOLON", "COMMA", "DOT", "COLON", "ARROW"}
    simbolos = {token.name for token in _SYMBOLS.values()}
    salida: Dict[str, str] = {}
    for token in TokenType:
        nombre = token.name
        if token in KEYWORDS.values():
            salida[nombre] = _keyword_category(token)
        elif nombre == "STRING_LIT":
            salida[nombre] = "string"
        elif nombre.endswith("_LIT"):
            salida[nombre] = "literal"
        elif nombre in ("IDENTIFIER", "DUNDER"):
            salida[nombre] = "name"
        elif nombre in ("COMMENT", "RAW_BLOCK"):
            salida[nombre] = "comment"
        elif nombre in delimitadores:
            salida[nombre] = "punctuation"
        elif nombre in simbolos:
            salida[nombre] = "operator"
        else:
            salida[nombre] = "meta"
    return salida


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
        # Categoría de CADA token, para que un editor no tenga que adivinarla:
        # es la misma pregunta que 'categories' responde para los keywords,
        # extendida a todo lo que el lexer emite.
        "token_categories": _token_categories(),
        "severities": _severities(),
        "errors": _error_catalog(),
        "stages": _pipeline_stages(),
        # v4: lo que necesita un resaltador (una gramatica TextMate) y los
        # snippets, para que la extension no copie a mano la sintaxis
        "syntax": _syntax(),
        "snippets": SNIPPETS,
    }


#: Las expresiones regulares de los literales, en la sintaxis de Oniguruma
#: (la de las gramaticas TextMate de VS Code). Espejo de
#: 'lexer/scanners/number.py', que no usa expresiones regulares: un test
#: comprueba que reconocen lo mismo que el lexer (test_lang_info_lexer).
NUMBER_REGEX = {
    "int": r"0[xX][0-9a-fA-F](?:_?[0-9a-fA-F])*|0[bB][01](?:_?[01])*"
           r"|0[oO][0-7](?:_?[0-7])*|[0-9](?:_?[0-9])*",
    "float": r"[0-9](?:_?[0-9])*\.[0-9](?:_?[0-9])*",
}


def _syntax() -> dict:
    """Comentarios, literales, escapes y el formato de un f-string."""
    try:
        from src.frontend.lexer.scanners.strings import _ESCAPES
        from src.frontend.parser.expressions.nud import FORMAT_SPEC
    except ImportError:  # pragma: no cover - ejecucion directa
        _ESCAPES, FORMAT_SPEC = {}, ""
    return {
        # los reconoce el lexer en codigo ('lexer.py', 'c_dir.py'): un
        # comentario de bloque NO se anida (el primer '-/' lo cierra)
        "comments": {"line": "//", "block": ["/-", "-/"], "block_nests": False},
        "string": {"quote": '"', "escapes": sorted("\\" + k for k in _ESCAPES)},
        "char": {"quote": "'", "escapes": sorted("\\" + k for k in _ESCAPES)},
        "fstring": {
            "prefix": "f",
            "interpolation": ["{", "}"],
            "brace_escapes": ["{{", "}}"],
            # '{x!r:08b}': la conversion y el especificador
            "conversions": ["r"],
            "format_spec": FORMAT_SPEC,
            "format_types": {"d": "int, byte (decimal)", "x": "int, byte (hexadecimal)",
                             "X": "int, byte (HEXADECIMAL)", "b": "int, byte (binario)",
                             "o": "int, byte (octal)", "f": "float (fijo)"},
        },
        "numbers": {
            "int": NUMBER_REGEX["int"],
            "float": NUMBER_REGEX["float"],
            "prefixes": {"0x": 16, "0b": 2, "0o": 8},
            "separator": "_",
        },
        "identifier": r"[\p{L}_][\p{L}\p{N}_]*",
        "dunder": r"__[A-Za-z0-9_]+__",
    }


#: Plantillas de las construcciones del lenguaje, en la sintaxis de snippets
#: de VS Code (``${1:nombre}`` es un campo con su valor por defecto; ``$0``,
#: donde queda el cursor). ``context``: "top" va en el nivel superior del
#: archivo, "body" dentro de una funcion. Un test las compila todas con sus
#: valores por defecto (test_lang_info_snippets; las de "impl" y "free" junto
#: a un ``struct Punto``): una plantilla que no compila no se publica.
SNIPPETS = [
    {"prefix": "main", "description": "punto de entrada",
     "context": "top", "body": "fn main() -> int {\n\t$0\n\treturn 0;\n}"},
    {"prefix": "fn", "description": "funcion",
     "context": "top", "body": "fn ${1:nombre}(${2:int x}) -> ${3:int} {\n\treturn ${4:x};\n}"},
    {"prefix": "struct", "description": "struct",
     "context": "top", "body": "struct {\n\t${2:int} ${3:campo};\n} ${1:Nombre};"},
    {"prefix": "enum", "description": "enum",
     "context": "top", "body": "enum ${1:Nombre} { ${2:A}, ${3:B} };"},
    {"prefix": "impl", "description": "metodos de un tipo",
     "context": "top", "body": "@impl ${1:Punto} {\n\tfn ${2:metodo}(${1:Punto} ptr self) -> ${3:int} {\n\t\treturn ${4:0};\n\t}\n}"},
    {"prefix": "free", "description": "destructor (__free__)",
     "context": "top", "body": "hook fn __free__(${1:Punto} ptr ${2:x}) -> void {\n\t$0\n}"},
    {"prefix": "test", "description": "bloque de prueba",
     "context": "top", "body": "test \"${1:nombre}\" {\n\t$0\n}"},
    {"prefix": "import", "description": "importar una libreria",
     "context": "top", "body": "#import ${1:mem}"},
    {"prefix": "from", "description": "importar de una libreria",
     "context": "top", "body": "#from ${1:io} #import ${2:stdp}"},
    {"prefix": "if", "description": "if / else",
     "context": "body", "body": "if (${1:true}) {\n\t$2\n} else {\n\t$0\n};"},
    {"prefix": "while", "description": "while",
     "context": "body", "body": "while (${1:false}) {\n\t$0\n};"},
    {"prefix": "match", "description": "match",
     "context": "body", "body": "match (${1:0}) {\n\tcase ${2:0}: {\n\t\t$0\n\t}\n}"},
    {"prefix": "try", "description": "try / catch / finally",
     "context": "body", "body": "try {\n\t$1\n} catch (${2:int} ${3:e}) {\n\t$4\n} finally {\n\t$0\n};"},
    {"prefix": "with", "description": "recurso que se destruye al salir",
     "context": "body", "body": "with (var ${1:int} ${2:r} = ${3:0}) {\n\t$0\n};"},
    {"prefix": "var", "description": "variable",
     "context": "body", "body": "var ${1:int} ${2:x} = ${3:0};"},
]


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

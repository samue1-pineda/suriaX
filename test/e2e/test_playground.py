"""e2e/playground — las fases que la página muestra salen del compilador.

Lo que se fija aquí no es cómo se ven, sino que **son las de verdad**: el
recolector (``driver/artifacts``) invoca el mismo lexer, el mismo parser y la
misma semántica que la CLI, así que un cambio en cualquiera de ellos se ve en
la página sin tocarla.

Y una propiedad que la hace útil: **cada fase se entrega aunque las anteriores
hayan fallado**. Un programa con un error de sintaxis igual tiene tokens, y
verlos es lo que explica el error. Lo que no se pudo producir dice por qué —
un panel vacío parecería un artefacto válido.
"""

from __future__ import annotations

import json
import os
import sys
import shutil
import threading
import urllib.error
import urllib.request

# helpers.omitir: la única forma de saltarse una prueba (el runner la cuenta
# como OMITIDA, nunca como pasada).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import omitir  # noqa: E402

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _p in (_REPO_ROOT, os.path.join(_REPO_ROOT, "V0"),
           os.path.join(_REPO_ROOT, "playground")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_VALIDO = """\
fn __write__(str s) -> void;

struct { int x; int y; } Punto;

fn area(Punto ptr p) -> int { return p.x * p.y; }

fn main() -> int {
    var Punto p = Punto{ x: 3, y: 4 };
    __write__(f"{area(&p)}\\n");
    return 0;
}
"""


def _collect(source: str):
    from driver.artifacts import collect
    return collect(source, path="prueba.srcx")


# --------------------------------------------------------------------------- #
# el recolector
# --------------------------------------------------------------------------- #

def test_un_programa_valido_entrega_todas_las_fases():
    datos = _collect(_VALIDO)
    assert not [d for d in datos["diagnostics"]
                if d["severity"] in ("critical", "panic")], datos["diagnostics"]
    for fase in ("tokens", "ast", "typed_ast", "symbols", "hir"):
        assert datos["phases"].get(fase, {}).get("ok"), (fase, datos["phases"])
    # el .phir viaja aparte: es lo que el backend web necesita para el .wat
    assert isinstance(datos.get("phir"), bytes) and datos["phir"], "sin .phir"


def test_los_tokens_traen_su_posicion():
    """Sin ``ln``/``col`` la página tendría que volver a buscar el lexema en el
    fuente, y se equivocaría donde aparece dos veces."""
    datos = _collect("fn main() -> int { return 0; }")
    tokens = datos["phases"]["tokens"]["tokens"]
    assert tokens, "sin tokens"
    assert all(t["ln"] >= 1 and t["col"] >= 1 for t in tokens), tokens[:5]
    assert any(t["type"] == "FUNCTION" for t in tokens), \
        [t["type"] for t in tokens[:5]]


def test_el_valor_de_un_token_no_es_un_repr_de_python():
    """La página la mira alguien que no conoce las clases del compilador.

    El valor de una cadena son los SEGMENTOS que el lexer separó; enseñarlos
    como ``Str(['x ', Interp('a')])`` es enseñar la estructura interna en vez
    de lo que el análisis léxico decidió.
    """
    datos = _collect('fn main() -> int { var str a = "x"; '
                     'var str b = f"hola {a}!"; return 0; }')
    valores = [t["value"] for t in datos["phases"]["tokens"]["tokens"]
               if t["type"] == "STRING_LIT"]
    assert valores, "sin literales de cadena"
    assert not any("Interp(" in v or "Str([" in v for v in valores), valores
    assert '"hola " + {a} + "!"' in valores, valores


def test_la_tabla_de_simbolos_es_un_ARBOL_de_scopes():
    """Enseñar solo el scope global sugiere que el compilador no sabe nada de
    lo que hay dentro de una función. Sabe: lo declara, lo tipa y lo destruye.
    """
    datos = _collect(
        "fn doble(int n) -> int { return n + n; }\n"
        "fn main() -> int {\n"
        "    var int x = 3;\n"
        "    while (x < 10) { var int y = doble(x); x = x + y; }\n"
        "    return x;\n"
        "}\n")
    fase = datos["phases"]["symbols"]
    scopes = {s["id"]: s for s in fase["scopes"]}
    assert scopes[0]["parent"] is None and scopes[0]["kind"] == "global"
    # una función abre su scope, y el cuerpo del 'while' otro DENTRO de ella
    funciones = [s for s in fase["scopes"] if s["kind"] == "function"]
    assert len(funciones) == 2, fase["scopes"]
    bloques = [s for s in fase["scopes"] if s["kind"] == "block"]
    assert bloques, "el cuerpo del while abre su propio scope"
    assert scopes[bloques[0]["parent"]]["kind"] == "function"
    # y cada scope dice DE QUIÉN es, no solo su número
    assert any(s["label"] == "fn main" for s in fase["scopes"]), fase["scopes"]


def test_cada_simbolo_dice_donde_se_declara_y_donde_se_usa():
    """La otra mitad de una tabla de símbolos: las referencias cruzadas.

    Quien resuelve un nombre es el único que sabe a qué símbolo apunta —dos
    'x' de scopes distintos se escriben igual—, así que la lista se llena en
    la Semántica y no volviendo a buscar el texto en el fuente.
    """
    datos = _collect(
        "fn main() -> int {\n"
        "    var int x = 3;\n"
        "    var int y = x + 1;\n"
        "    x = x + y;\n"
        "    return x;\n"
        "}\n")
    simbolos = {s["name"]: s for s in datos["phases"]["symbols"]["symbols"]}
    x = simbolos["x"]
    assert x["ln"] == 2, x
    assert x["mutable"] is True
    # línea 3 (lectura), línea 4 (escritura y lectura), línea 5 (retorno)
    assert [u["ln"] for u in x["uses"]] == [3, 4, 4, 5], x["uses"]
    assert x["uses"] == sorted(x["uses"], key=lambda u: (u["ln"], u["col"])), \
        "los usos van por posición, no por el orden en que se visitó el árbol"
    assert simbolos["y"]["uses"], "'y' se usa en la línea 4"


def test_dos_variables_con_el_MISMO_nombre_no_se_mezclan():
    """Es lo que un scope resuelve y una lista aplanada no puede."""
    datos = _collect(
        "fn f() -> int { var int v = 1; return v; }\n"
        "fn g() -> int { var int v = 2; return v + v; }\n"
        "fn main() -> int { return f() + g(); }\n")
    ves = [s for s in datos["phases"]["symbols"]["symbols"] if s["name"] == "v"]
    assert len(ves) == 2, ves
    assert ves[0]["scope"] != ves[1]["scope"], "cada una en su scope"
    assert sorted(len(s["uses"]) for s in ves) == [1, 2], \
        "los usos de una no se le cuentan a la otra"


def test_un_item_de_enum_no_sale_dos_veces():
    """'ROJO' y 'Color.ROJO' nombran el MISMO símbolo: una fila, no dos."""
    datos = _collect("enum Color { ROJO, VERDE };\n"
                     "fn main() -> int { var Color c = Color.ROJO; return 0; }\n")
    nombres = [(s["owner"], s["name"])
               for s in datos["phases"]["symbols"]["symbols"]]
    rojos = [n for n in nombres if n[1] == "ROJO"]
    assert len(rojos) == 1, nombres


def test_el_ast_tipado_trae_los_tipos_que_el_ast_no():
    """Es la única diferencia entre los dos árboles, y la que justifica que la
    página los muestre por separado."""
    datos = _collect(_VALIDO)
    crudo = json.dumps(datos["phases"]["ast"]["tree"])
    tipado = json.dumps(datos["phases"]["typed_ast"]["tree"])
    assert crudo != tipado, "el AST-tipado no añadió nada"
    assert "restype" in tipado


def test_el_hir_trae_sus_dos_vistas():
    """Una para LEER el programa y otra para depurar el FORMATO. Son
    preguntas distintas y un solo volcado no responde bien a las dos."""
    datos = _collect(_VALIDO)
    hir = datos["phases"]["hir"]
    assert hir["pretty"].startswith("unit "), hir["pretty"][:60]
    # el texto del protobuf habla de TAGS, no del programa
    assert "schema_version" in hir["text"], hir["text"][:120]


def test_la_tabla_de_simbolos_es_un_diagrama_de_clases():
    datos = _collect(_VALIDO)
    mermaid = datos["phases"]["symbols"]["mermaid"]
    assert mermaid.startswith("classDiagram"), mermaid[:60]
    assert "Punto" in mermaid


def test_el_diagrama_no_inventa_una_clase_por_parametro_de_tipo():
    """``T`` en ``Caja<T>`` se registra en el scope (es lo que permite escribir
    ``T valor;``) pero NO es un tipo: es un hueco. Dibujarlo ponía una caja
    por cada genérico y una flecha ``Caja --> T`` que no significa nada."""
    datos = _collect("struct { T valor; } Caja<T>;\n"
                     "fn main() -> int { return 0; };")
    mermaid = datos["phases"]["symbols"]["mermaid"]
    assert "class Caja~T~" in mermaid, mermaid
    assert "class T " not in mermaid and "--> T " not in mermaid, mermaid


def test_el_diagrama_usa_la_notacion_del_lenguaje():
    """Postfija (``Punto ptr``), como se escribe en suriaX. Antes salía de
    ``repr(Type)``, que es prefija: el diagrama era el único sitio donde un
    tipo se leía al revés que en el código."""
    datos = _collect("struct { int x; } Punto;\n"
                     "fn area(Punto ptr p) -> int { return p.x; };\n"
                     "fn main() -> int { return 0; };")
    mermaid = datos["phases"]["symbols"]["mermaid"]
    assert "Punto ptr" in mermaid and "ptr Punto" not in mermaid, mermaid


def test_un_programa_sin_tipos_sigue_dando_un_diagrama_valido():
    """Un ``classDiagram`` sin una sola clase no es un diagrama vacío para
    Mermaid: es un error de sintaxis, y el panel se quedaba en blanco."""
    datos = _collect("fn main() -> int { return 0; };")
    mermaid = datos["phases"]["symbols"]["mermaid"]
    assert mermaid.count("class ") >= 1, mermaid


def test_un_programa_roto_conserva_las_fases_que_si_pudo_producir():
    """La propiedad que hace útil la página cuando algo falla."""
    datos = _collect("fn main() -> int { var int x = ; return q; }")
    assert datos["phases"]["tokens"]["ok"], "un error de sintaxis no borra los tokens"
    assert datos["phases"]["ast"]["ok"]
    assert [d for d in datos["diagnostics"] if d["severity"] == "critical"]


def test_sin_hir_se_dice_por_que():
    """La frontera no se cruza con un programa inválido, y decirlo es más útil
    que enseñar un HIR a medias."""
    datos = _collect("fn main() -> int { return q; }")
    hir = datos["phases"]["hir"]
    assert hir["ok"] is False
    assert hir["reason"], "un panel sin motivo parece un artefacto vacío"


def test_un_aviso_no_impide_el_hir():
    """SEM030 es un aviso: la compilación continúa y el artefacto se emite.
    Es el mismo contrato que en la CLI."""
    datos = _collect(
        "enum Color { ROJO, VERDE };\n"
        "fn main() -> int {\n"
        "    var Color c = Color.ROJO;\n"
        "    match (c) { case Color.ROJO: { return 1; } }\n"
        "    return 0;\n"
        "}\n")
    assert any(d["code"] == "SEM030" for d in datos["diagnostics"]), \
        datos["diagnostics"]
    assert datos["phases"]["hir"]["ok"], datos["phases"]["hir"]


# --------------------------------------------------------------------------- #
# el servidor
# --------------------------------------------------------------------------- #

def _con_servidor(comprobar) -> None:
    """Levanta el servidor en un puerto libre y se lo pasa a ``comprobar``."""
    from http.server import ThreadingHTTPServer
    from server import Handler

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    hilo = threading.Thread(target=httpd.serve_forever, daemon=True)
    hilo.start()
    try:
        comprobar(f"http://127.0.0.1:{httpd.server_address[1]}")
    finally:
        httpd.shutdown()
        httpd.server_close()
        hilo.join(timeout=10)


def test_el_servidor_compila_y_sirve_la_pagina():
    def comprobar(base):
        with urllib.request.urlopen(f"{base}/", timeout=30) as r:
            assert r.status == 200
            assert b"<title>suriaX" in r.read()

        cuerpo = json.dumps({"source": _VALIDO}).encode()
        peticion = urllib.request.Request(
            f"{base}/api/compile", data=cuerpo,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(peticion, timeout=180) as r:
            datos = json.loads(r.read())
        assert datos["phases"]["hir"]["ok"], datos["phases"]["hir"]
        # el .phir NO viaja al navegador: son bytes y la página no los usa
        assert "phir" not in datos
        # el panel de WebAssembly responde SIEMPRE: con sus dos vistas o con
        # el motivo por el que el target no lo generó.
        wasm = datos["phases"]["wasm"]
        assert wasm["ok"] is False or {"pretty", "wat"} <= set(wasm), wasm
        if not wasm["ok"]:
            assert wasm["reason"], "un panel sin motivo parece un artefacto vacío"

    _con_servidor(comprobar)


def test_el_lexer_solo_responde_sin_correr_el_resto():
    """El editor pide los tokens en cada pausa al escribir: correr la
    semántica para colorear sería pagar cien veces lo que cuesta."""
    from driver.artifacts import lex_only

    datos = lex_only("fn main() -> int { move x; return 0; }")
    tipos = [t["type"] for t in datos["tokens"]]
    assert "FUNCTION" in tipos and "MOVE" in tipos, tipos
    # y no trae nada más que el léxico: ni AST, ni símbolos, ni HIR
    assert set(datos) == {"tokens", "diagnostics"}, sorted(datos)


def test_el_servidor_no_sirve_nada_fuera_de_static():
    """Un '..' en la ruta saldría del directorio publicado."""
    def comprobar(base):
        try:
            urllib.request.urlopen(f"{base}/../server.py", timeout=30)
        except urllib.error.HTTPError as exc:
            assert exc.code == 404, exc.code
            return
        raise AssertionError("sirvió un archivo de fuera de 'static/'")

    _con_servidor(comprobar)


def test_un_fuente_demasiado_grande_se_rechaza():
    """Compilar es trabajo real y el servidor es público: hay una cota."""
    def comprobar(base):
        from server import MAX_SOURCE_BYTES
        cuerpo = json.dumps({"source": "a" * (MAX_SOURCE_BYTES + 1024)}).encode()
        peticion = urllib.request.Request(
            f"{base}/api/compile", data=cuerpo,
            headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(peticion, timeout=60)
        except urllib.error.HTTPError as exc:
            assert exc.code == 413, exc.code
            return
        raise AssertionError("aceptó un fuente por encima del límite")

    _con_servidor(comprobar)


# --------------------------------------------------------------------------- #
# el contrato del lenguaje: la página NO clasifica ni explica por su cuenta
# --------------------------------------------------------------------------- #

def test_cada_token_trae_su_categoria_del_compilador():
    """``lang_info`` existe "para que la extensión coloree sin reimplementar
    la gramática". Sin una categoría por token, un editor la adivina — el
    playground llegó a decidir por regex si ``INT`` era un tipo o un literal.
    """
    from include.lang_info import build_language_info
    from include.t_types import TokenType

    categorias = build_language_info()["token_categories"]
    faltan = [t.name for t in TokenType if t.name not in categorias]
    assert not faltan, f"tokens sin categoría: {faltan}"
    # las categorías son las del LENGUAJE, no las de un resaltador cualquiera
    assert categorias["MOVE"] == "memory"
    assert categorias["TRY"] == "error_handling"
    assert categorias["INT"] == "type" and categorias["INT_LIT"] == "literal"
    assert categorias["STRING_LIT"] == "string"


def test_el_catalogo_explica_por_que_existe_cada_error():
    """El docstring de cada clase es donde el proyecto explica por qué existe
    ese error y qué hacer. Publicarlo convierte el catálogo en algo que una
    herramienta puede enseñar, y no cuesta mantenerlo: ya estaba escrito."""
    from include.lang_info import build_language_info

    errores = build_language_info()["errors"]
    assert errores, "catálogo vacío"
    sin_explicar = [e["code"] for e in errores if not e["explanation"].strip()]
    assert not sin_explicar, (
        f"códigos sin explicación (su clase no tiene docstring): {sin_explicar}")


def test_el_servidor_publica_el_contrato_del_lenguaje():
    def comprobar(base):
        with urllib.request.urlopen(f"{base}/api/language", timeout=60) as r:
            datos = json.loads(r.read())
        assert datos["token_categories"]["FUNCTION"] == "declaration"
        assert any(e["code"] == "SEM001" for e in datos["errors"])

    _con_servidor(comprobar)


# --------------------------------------------------------------------------- #
# las fases del target web son etapas con entrega propia
# --------------------------------------------------------------------------- #

_CON_IO = """\
#from io #import stdp

fn main() -> int {
    stdp.println("hola");
    return 0;
}
"""


def test_el_enlace_muestra_QUE_trajo_de_cada_libreria():
    """Decir "se resolvió el import de IO" no explica nada. Lo que explica es
    ver lo que llegó: que ``IO.stdp`` aporta ``println`` y que debajo hay un
    prototipo ``__write__`` cuyo cuerpo pone quien ejecuta — de ahí sale el
    'host' que luego aparece en el WebAssembly."""
    datos = _collect(_CON_IO)
    enlace = datos["phases"]["link"]
    assert enlace["ok"], enlace

    unidades = {u["alias"]: u for u in enlace["libraries"]}
    assert "IO.stdp" in unidades, sorted(unidades)
    stdp = unidades["IO.stdp"]

    firmas = {f["signature"]: f for f in stdp["functions"]}
    assert any(s.startswith("fn println(") for s in firmas), sorted(firmas)
    # ...y la parte que sorprende: su implementación real es un PROTOTIPO
    prototipos = [s for s, f in firmas.items() if f["prototype"]]
    assert any("__write__" in s for s in prototipos), prototipos
    # cada unidad viaja en su propio artefacto, no copiada dentro del tuyo
    assert stdp["bytes"] > 0 and stdp["phir"].endswith(".phir"), stdp


def test_lo_que_el_target_no_soporta_es_un_ERROR_de_compilacion():
    """El programa va DIRECTO al backend web. Si el target no soporta algo,
    eso no es "una fase que no produjo nada": es que el programa **no compila
    para ese target**. Enseñarlo como un hueco invitaba a pensar que el
    intérprete lo salvaría, y por ese camino no pasa el intérprete."""
    if shutil.which("node") is None:
        omitir("node no está instalado; el target web no corre")
    from server import compile_source

    datos = compile_source(
        "#from io #import stdp\n"
        "fn main() -> int {\n"
        '    try { stdp.println("a"); } catch (e) { stdp.println("b"); }\n'
        "    return 0;\n"
        "};\n")
    # el frontend lo acepta: 'try' es parte del lenguaje
    assert not [d for d in datos["diagnostics"] if d["phase"] != "web"], \
        datos["diagnostics"]
    # ...y el target lo rechaza, con su posición y como diagnóstico de VERDAD
    delTarget = [d for d in datos["diagnostics"] if d["phase"] == "web"]
    assert delTarget, "el target aceptó algo que no sabe compilar"
    assert all(d["line"] > 0 for d in delTarget), delTarget
    assert datos["phases"]["wasm"]["ok"] is False


def test_no_soportado_y_no_compilado_se_distinguen():
    """Dicen cosas distintas y sugieren acciones distintas: un ``WEB0xx`` es
    definitivo ("el target decidió no ejecutar esto") y un ``WEB1xx`` es
    trabajo pendiente del compilador."""
    if shutil.which("node") is None:
        omitir("node no está instalado; el target web no corre")
    from server import compile_source

    # un struct: el codegen todavía no llega, pero no está prohibido
    datos = compile_source("#from io #import stdp\n"
                           "struct { int x; } P;\n"
                           "fn main() -> int { var P p = P{x:1}; return p.x; };\n")
    clases = {d["kind"] for d in datos["diagnostics"] if d["phase"] == "web"}
    assert clases == {"not-compiled"}, clases

    # '#extern cpp': eso SÍ es una decisión del target (no hay toolchain C++)
    datos = compile_source("#from io #import stdp\n"
                           "fn main() -> int { stdp.println(\"a\"); return 0; };\n"
                           "#extern cpp{\nint f() { return 1; }\n}\n")
    clases = {d["kind"] for d in datos["diagnostics"] if d["phase"] == "web"}
    assert "unsupported" in clases, clases


def test_el_modo_depuracion_mide_la_misma_compilacion():
    from server import compile_source
    datos = compile_source(_CON_IO, debug=True)
    assert "times" in datos["debug"] and "metrics" in datos["debug"]
    assert datos["debug"]["metrics"]["tokens"] > 0
    # sin pedirlo, no aparece: no se enseña una pestaña vacía
    assert "debug" not in compile_source(_CON_IO)


def test_el_env_no_pisa_lo_que_ya_esta_en_el_entorno():
    """Railway inyecta la configuración como variables; el .env es para el
    otro caso. Si un .env olvidado pudiera cambiar el puerto donde escucha la
    plataforma, sería una trampa."""
    import tempfile
    from server import cargar_env

    with tempfile.TemporaryDirectory() as tmp:
        ruta = os.path.join(tmp, ".env")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write("# un comentario\n"
                     "SURIAX_PRUEBA_NUEVA=valor\n"
                     'SURIAX_PRUEBA_COMILLAS="con comillas"\n'
                     "SURIAX_PRUEBA_EXISTENTE=del_archivo\n")
        os.environ["SURIAX_PRUEBA_EXISTENTE"] = "del_entorno"
        try:
            cargar_env(ruta)
            assert os.environ["SURIAX_PRUEBA_NUEVA"] == "valor"
            assert os.environ["SURIAX_PRUEBA_COMILLAS"] == "con comillas"
            assert os.environ["SURIAX_PRUEBA_EXISTENTE"] == "del_entorno"
        finally:
            for clave in ("SURIAX_PRUEBA_NUEVA", "SURIAX_PRUEBA_COMILLAS",
                          "SURIAX_PRUEBA_EXISTENTE"):
                os.environ.pop(clave, None)

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


# --------------------------------------------------------------------------- #
# los proveedores fallan por separado
#
# El compilador y el target web son dos proveedores detrás de dos adaptadores.
# Lo que se fija aquí es que el fallo de uno no se lleva al otro, y que un
# fallo INTERNO no se le atribuye al programa: son cuatro estados (ok,
# error_del_programa, no_disponible, error_interno) y cada uno pide una acción
# distinta a quien lo lee.
#
# Los fallos se simulan cambiando la función que lanza el proceso (o la que
# recolecta las fases): así se prueban también donde node no está.
# --------------------------------------------------------------------------- #

import contextlib
import subprocess


@contextlib.contextmanager
def _parche(modulo, **nuevos):
    """Cambia atributos de un módulo y los repone al salir, pase lo que pase."""
    viejos = {clave: getattr(modulo, clave) for clave in nuevos}
    for clave, valor in nuevos.items():
        setattr(modulo, clave, valor)
    try:
        yield
    finally:
        for clave, valor in viejos.items():
            setattr(modulo, clave, valor)


def _con_node_falso(lanzar):
    """El adaptador web con un node de mentira: ``lanzar(cmd)`` hace de él."""
    from capas import web
    return _parche(web, version_de_node=lambda: 22, _lanzar=lanzar)


def _proceso(cmd, codigo=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(cmd, codigo, stdout, stderr)


def _frontend_intacto(datos):
    """Las fases del compilador llegaron, falle lo que falle el target."""
    for fase in ("tokens", "ast", "typed_ast", "symbols", "hir", "link"):
        assert datos["phases"][fase]["ok"], (fase, datos["phases"][fase])
    assert datos["providers"]["compiler"]["status"] == "ok", datos["providers"]


def _target_roto(datos):
    wasm = datos["phases"]["wasm"]
    assert wasm["ok"] is False and wasm["status"] == "error_interno", wasm
    assert wasm["reason"].startswith("el backend web falló por dentro"), wasm
    assert datos["providers"]["web"]["status"] == "error_interno"
    assert datos["status"] == "error_interno"
    # un fallo interno NO es un diagnóstico del programa
    assert not [d for d in datos["diagnostics"] if d["phase"] == "web"], \
        datos["diagnostics"]


def test_un_target_web_que_no_responde_no_se_lleva_al_compilador():
    """Antes el ``TimeoutExpired`` salía como un 500 y la página se quedaba
    sin NINGUNA fase, también las que el compilador sí había producido."""
    from server import compile_source

    def lanzar(cmd):
        raise subprocess.TimeoutExpired(cmd, 1)

    with _con_node_falso(lanzar):
        datos = compile_source(_VALIDO)
    _frontend_intacto(datos)
    _target_roto(datos)
    assert "no respondió" in datos["phases"]["wasm"]["reason"]


def test_un_target_web_que_muere_dice_lo_que_dijo_al_morir():
    """Sin informe no hay nada que atribuirle al programa. Su salida de error
    es lo único que explica el fallo; antes se tiraba. Y se publica sin las
    rutas de la máquina donde corre el servidor."""
    from capas import config
    from server import compile_source

    def lanzar(cmd):
        return _proceso(cmd, 3, "", f"TypeError: boom\n  at {config.REPO}"
                                    f"{os.sep}web{os.sep}main.ts:1:1\n")

    with _con_node_falso(lanzar):
        datos = compile_source(_VALIDO)
    _frontend_intacto(datos)
    _target_roto(datos)
    detalle = datos["phases"]["wasm"]["detail"]
    assert "TypeError: boom" in detalle, detalle
    assert "sin informe" in datos["phases"]["wasm"]["reason"]
    assert config.REPO not in detalle and "<repo>" in detalle, detalle


def test_un_target_que_no_genera_ni_explica_no_culpa_al_programa():
    """Con un informe válido, sin artefacto y sin diagnósticos, la página
    decía "el target web todavía no compila construcciones del programa". Era
    inventar un motivo: el target no había dicho nada."""
    from server import compile_source

    def lanzar(cmd):
        return _proceso(cmd, 0, json.dumps({"ok": True, "diagnostics": []}))

    with _con_node_falso(lanzar):
        datos = compile_source(_VALIDO)
    _frontend_intacto(datos)
    _target_roto(datos)


def test_lo_que_el_target_diagnostica_si_es_del_programa():
    """La otra cara: un diagnóstico del target es un error DEL PROGRAMA, y no
    se confunde con un fallo interno."""
    from server import compile_source

    def lanzar(cmd):
        return _proceso(cmd, 1, json.dumps({"ok": False, "diagnostics": [
            {"code": "WEB101", "line": 3, "col": 1, "message": "struct"}]}))

    with _con_node_falso(lanzar):
        datos = compile_source(_VALIDO)
    _frontend_intacto(datos)
    wasm = datos["phases"]["wasm"]
    assert wasm["status"] == "error_del_programa" and not wasm["ok"], wasm
    assert [d["kind"] for d in datos["diagnostics"] if d["phase"] == "web"] \
        == ["not-compiled"], datos["diagnostics"]
    assert datos["status"] == "error_del_programa"


def test_un_target_que_si_genera_entrega_sus_dos_vistas():
    from server import compile_source

    def lanzar(cmd):
        with open(cmd[cmd.index("--emit-wat") + 1], "w", encoding="utf-8") as fh:
            fh.write("(module)")
        with open(cmd[cmd.index("--emit-pretty") + 1], "w",
                  encoding="utf-8") as fh:
            fh.write("fn main")
        return _proceso(cmd, 0, json.dumps({"ok": True, "diagnostics": []}))

    with _con_node_falso(lanzar):
        datos = compile_source(_VALIDO)
    wasm = datos["phases"]["wasm"]
    assert wasm == {"ok": True, "status": "ok", "wat": "(module)",
                    "pretty": "fn main"}, wasm
    assert datos["status"] == "ok" and datos["api"] == "1", datos["status"]


def test_sin_node_el_target_no_esta_disponible_y_no_es_un_fallo():
    """Que falte node lo arregla quien instala el entorno, no quien mantiene
    el compilador: es otro estado."""
    from capas import web
    from server import compile_source

    def lanzar(cmd):
        raise AssertionError("sin node no hay nada que lanzar")

    with _parche(web, version_de_node=lambda: None, _lanzar=lanzar):
        datos = compile_source(_VALIDO)
    _frontend_intacto(datos)
    assert datos["phases"]["wasm"]["status"] == "no_disponible"
    assert "node 22" in datos["phases"]["wasm"]["reason"]
    assert datos["status"] == "no_disponible"


def test_un_compilador_que_falla_por_dentro_no_tira_el_servidor():
    """Y viceversa: si el que falla es el compilador, el servidor contesta
    200 con la MISMA forma de siempre y dice quién falló. Antes era un 500
    con un solo campo, y la página no tenía pestañas que enseñar."""
    from capas import compilador

    def recolectar(fuente):
        raise RuntimeError("se rompió el enlazador")

    def lanzar(cmd):
        raise AssertionError("sin HIR no se invoca al target web")

    def comprobar(base):
        peticion = urllib.request.Request(
            f"{base}/api/compile",
            data=json.dumps({"source": _VALIDO}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(peticion, timeout=60) as r:
            assert r.status == 200
            datos = json.loads(r.read())
        assert datos["status"] == "error_interno"
        propio = datos["providers"]["compiler"]
        assert propio["status"] == "error_interno", propio
        assert propio["detail"] == "RuntimeError: se rompió el enlazador"
        for fase in compilador.FASES:
            panel = datos["phases"][fase]
            assert panel["ok"] is False and panel["status"] == "error_interno"
            assert "el compilador falló por dentro" in panel["reason"], panel
        # el target no falló: no tuvo nada que procesar
        assert datos["phases"]["wasm"]["status"] == "no_disponible"
        assert datos["diagnostics"] == []

        # y la página se sigue sirviendo
        with urllib.request.urlopen(f"{base}/", timeout=30) as r:
            assert r.status == 200

    with _parche(compilador, _recolectar=recolectar), _con_node_falso(lanzar):
        _con_servidor(comprobar)


def test_un_error_del_programa_no_es_un_fallo_de_nadie():
    from capas import web
    from server import compile_source

    with _parche(web, version_de_node=lambda: None):
        datos = compile_source("fn main() -> int { return q; }")
    assert datos["providers"]["compiler"]["status"] == "error_del_programa"
    assert datos["status"] == "error_del_programa"


_VARIOS = (
    _CON_IO,
    "#import array.vector as vec\n"
    "fn main() -> int { var vec.Vector<int> v = vec.dynamic<int>(2);"
    " v.push(1); return v.get(0); }\n",
    "#import collections.dictionary as dic\n"
    "fn main() -> int { var dic.Dictionary<str, int> d = dic.make<str, int>(2);"
    ' d.put("a", 1); return d.get("a"); }\n',
)


def test_compilar_a_la_vez_da_lo_mismo_que_compilar_en_serie():
    """El frontend guarda estado global y el servidor atiende con hilos: sin
    el candado del adaptador, un programa VÁLIDO salía con ``SEM010`` porque
    otra compilación le había cambiado la caché del enlazador a media
    resolución (medido: 10 de 90 en paralelo distintas de la serie)."""
    from capas import web
    from server import compile_source

    def resumen(fuente):
        datos = compile_source(fuente)
        return ([d["code"] for d in datos["diagnostics"]],
                datos["phases"]["hir"]["ok"],
                datos["providers"]["compiler"]["status"])

    with _parche(web, version_de_node=lambda: None):
        serie = [resumen(f) for f in _VARIOS]
        assert all(r == ([], True, "ok") for r in serie), serie
        for _ in range(4):
            salida = [None] * (len(_VARIOS) * 5)

            def trabajo(i):
                salida[i] = resumen(_VARIOS[i % len(_VARIOS)])

            hilos = [threading.Thread(target=trabajo, args=(i,))
                     for i in range(len(salida))]
            for h in hilos:
                h.start()
            for h in hilos:
                h.join()
            distintas = [r for i, r in enumerate(salida)
                         if r != serie[i % len(_VARIOS)]]
            assert not distintas, distintas[:3]


# --------------------------------------------------------------------------- #
# el transporte: lo que el servidor promete a cualquiera que lo llame
# --------------------------------------------------------------------------- #

def _pedir(base, ruta, *, metodo="GET", cuerpo=None, cabeceras=None):
    """``(código, cabeceras, json)`` de una petición, falle o no."""
    peticion = urllib.request.Request(f"{base}{ruta}", data=cuerpo,
                                      method=metodo, headers=cabeceras or {})
    try:
        with urllib.request.urlopen(peticion, timeout=60) as r:
            return r.status, r.headers, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, json.loads(exc.read() or b"null")


def test_la_salud_dice_el_estado_de_cada_proveedor_sin_compilar():
    """Para quien despliega: una sola pregunta que dice qué falta."""
    from capas import compilador, web

    def no_se_compila(fuente):
        raise AssertionError("la salud no compila nada")

    def comprobar(base):
        codigo, _, datos = _pedir(base, "/api/health")
        assert codigo == 200
        assert datos["api"] == "1"
        assert datos["providers"]["compiler"]["status"] == "ok", datos
        assert datos["providers"]["web"] == {
            "status": "no_disponible", "node": None,
            "detail": datos["providers"]["web"]["detail"]}, datos
        assert "node 22" in datos["providers"]["web"]["detail"]
        assert datos["status"] == "no_disponible"

    with _parche(compilador, _recolectar=no_se_compila), \
            _parche(web, version_de_node=lambda: None):
        _con_servidor(comprobar)


def test_un_error_http_tiene_la_forma_de_la_rfc_9457():
    """Un error HTTP es "no pude atender la petición", que no es lo mismo que
    un programa que no compila. Lleva una forma que una herramienta puede
    leer, y conserva ``error`` para quien ya lo leía."""
    def comprobar(base):
        from server import MAX_SOURCE_BYTES
        codigo, cabeceras, datos = _pedir(
            base, "/api/compile", metodo="POST",
            cuerpo=json.dumps({"source": "a" * (MAX_SOURCE_BYTES + 8)}).encode(),
            cabeceras={"Content-Type": "application/json"})
        assert codigo == 413
        assert cabeceras["Content-Type"].startswith("application/problem+json")
        assert datos["status"] == 413 and datos["title"] and datos["detail"]
        assert datos["error"] == datos["detail"]

    _con_servidor(comprobar)


def test_el_servidor_rechaza_lo_que_no_es_una_peticion_valida():
    def comprobar(base):
        json_ = {"Content-Type": "application/json"}
        # un formulario de otra página no pone a compilar a un servidor local
        codigo, _, _ = _pedir(base, "/api/compile", metodo="POST",
                              cuerpo=b'{"source": ""}',
                              cabeceras={"Content-Type": "text/plain"})
        assert codigo == 415, codigo
        codigo, _, _ = _pedir(base, "/api/compile", metodo="POST",
                              cuerpo=b"[1, 2]", cabeceras=json_)
        assert codigo == 400, codigo
        codigo, _, _ = _pedir(base, "/api/compile", metodo="POST",
                              cuerpo=b'{"source": 7}', cabeceras=json_)
        assert codigo == 400, codigo
        codigo, _, _ = _pedir(base, "/api/compile", metodo="POST",
                              cuerpo=b"{no es json", cabeceras=json_)
        assert codigo == 400, codigo
        # el método equivocado dice cuál es el bueno
        codigo, cabeceras, _ = _pedir(base, "/api/compile")
        assert codigo == 405 and "POST" in cabeceras["Allow"], cabeceras
        codigo, cabeceras, _ = _pedir(base, "/api/health", metodo="POST",
                                      cuerpo=b"{}", cabeceras=json_)
        assert codigo == 405 and "GET" in cabeceras["Allow"], cabeceras
        codigo, _, _ = _pedir(base, "/api/noexiste", metodo="POST",
                              cuerpo=b"{}", cabeceras=json_)
        assert codigo == 404, codigo

    _con_servidor(comprobar)


def test_las_respuestas_llevan_las_cabeceras_de_seguridad():
    def comprobar(base):
        with urllib.request.urlopen(f"{base}/", timeout=30) as r:
            assert r.headers["X-Content-Type-Options"] == "nosniff"
            assert r.headers["Referrer-Policy"] == "no-referrer"
            assert "Python" not in r.headers["Server"], r.headers["Server"]
        _, cabeceras, _ = _pedir(base, "/api/language")
        assert cabeceras["X-Content-Type-Options"] == "nosniff"
        assert cabeceras["Cache-Control"] == "no-store"
        assert cabeceras["Content-Security-Policy"] == "default-src 'none'"
        # sin configurarlo, ningún otro origen puede llamar a la API
        assert cabeceras["Access-Control-Allow-Origin"] is None

    _con_servidor(comprobar)


def test_otro_origen_solo_entra_si_se_configura():
    """La integración desde otro sitio es una decisión de quien despliega
    (``SURIAX_CORS_ORIGIN``), y se concede a UN origen, no a todos."""
    from capas import config

    def comprobar(base):
        codigo, cabeceras, _ = _pedir(base, "/api/compile", metodo="OPTIONS")
        assert codigo == 204
        assert cabeceras["Access-Control-Allow-Origin"] == "https://otro.example"
        assert "POST" in cabeceras["Access-Control-Allow-Methods"]
        _, cabeceras, _ = _pedir(base, "/api/language")
        assert cabeceras["Access-Control-Allow-Origin"] == "https://otro.example"

    with _parche(config, ORIGEN_PERMITIDO="https://otro.example"):
        _con_servidor(comprobar)


def test_por_defecto_el_servidor_solo_escucha_en_esta_maquina():
    """Publicarlo en la red es una decisión (``HOST=0.0.0.0``), no un
    descuido. Y una variable ilegible no arranca con el valor por defecto."""
    entorno = {k: v for k, v in os.environ.items()
               if k not in ("HOST", "PORT") and not k.startswith("SURIAX_")}
    orden = [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'playground');"
             "from capas import config; print(config.HOST, config.PUERTO)"]
    if os.path.isfile(os.path.join(_REPO_ROOT, ".env")):
        omitir("hay un .env en la raíz: los valores por defecto no se ven")
    sale = subprocess.run(orden, capture_output=True, text=True, env=entorno,
                          cwd=_REPO_ROOT, timeout=60)
    assert sale.stdout.split() == ["127.0.0.1", "8000"], (sale.stdout,
                                                          sale.stderr)
    sale = subprocess.run(orden, capture_output=True, text=True,
                          env={**entorno, "SURIAX_WEB_TIMEOUT": "dos minutos"},
                          cwd=_REPO_ROOT, timeout=60)
    assert sale.returncode != 0 and "SURIAX_WEB_TIMEOUT" in sale.stderr, \
        (sale.returncode, sale.stderr)


# --------------------------------------------------------------------------- #
# la descripción de la API dice lo que el servidor hace
#
# Una descripción que se escribe aparte se queda atrás. Estas pruebas la atan
# al código: las rutas, los estados y los campos obligatorios salen de las
# respuestas de verdad.
# --------------------------------------------------------------------------- #

def _openapi():
    with open(os.path.join(_REPO_ROOT, "playground", "openapi.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def _obligatorios(api, esquema):
    return api["components"]["schemas"][esquema]["required"]


def test_la_descripcion_de_la_api_tiene_las_rutas_del_servidor():
    import server
    from capas import config

    api = _openapi()
    assert api["openapi"].startswith("3.1"), api["openapi"]
    assert api["info"]["version"] == config.API
    descritas = {ruta: next(iter(metodos)).upper()
                 for ruta, metodos in api["paths"].items()}
    assert descritas == server._RUTAS, (descritas, server._RUTAS)


def test_los_estados_descritos_son_los_del_codigo():
    from capas import estados

    descritos = _openapi()["components"]["schemas"]["Estado"]["enum"]
    assert sorted(descritos) == sorted(estados._GRAVEDAD), descritos


def test_las_respuestas_traen_lo_que_la_descripcion_promete():
    from capas import aplicacion, web

    api = _openapi()
    fases = api["components"]["schemas"]["Compilacion"]["properties"][
        "phases"]["required"]
    with _parche(web, version_de_node=lambda: None):
        for fuente in (_VALIDO, "fn main() -> int { return q; }",
                       "fn main( {"):
            datos = aplicacion.compile_source(fuente)
            assert set(_obligatorios(api, "Compilacion")) <= set(datos), datos
            assert sorted(datos["phases"]) == sorted(fases), datos["phases"]
            for nombre, fase in datos["phases"].items():
                assert set(_obligatorios(api, "Fase")) <= set(fase), nombre
                # sin artefacto, siempre hay un motivo
                assert fase["ok"] or fase["reason"], (nombre, fase)
            for diag in datos["diagnostics"]:
                assert set(_obligatorios(api, "Diagnostico")) <= set(diag)
            for proveedor in datos["providers"].values():
                assert set(_obligatorios(api, "Proveedor")) <= set(proveedor)
        assert set(_obligatorios(api, "Lexico")) <= \
            set(aplicacion.lex_source("fn"))
        assert set(_obligatorios(api, "Salud")) <= set(aplicacion.health())


def test_el_servidor_publica_su_descripcion():
    def comprobar(base):
        codigo, _, datos = _pedir(base, "/api/openapi.json")
        assert codigo == 200 and datos == _openapi()

    _con_servidor(comprobar)


def test_el_entorno_se_puede_comprobar_sin_levantar_el_servidor():
    """``--check`` es para quien acaba de clonar: dice qué hay y qué falta,
    y solo sale con 0 si está todo."""
    import io
    import server
    from capas import web

    def correr(node):
        salida = io.StringIO()
        with _parche(web, version_de_node=lambda: node), \
                contextlib.redirect_stdout(salida):
            return server.main(["--check"]), salida.getvalue()

    codigo, texto = correr(None)
    assert codigo == 1, texto
    assert "compilador  ok" in texto and "no_disponible" in texto, texto
    assert "node 22" in texto, texto
    codigo, texto = correr(22)
    assert codigo == 0 and "target web  ok" in texto, texto


# --------------------------------------------------------------------------- #
# las cotas, y la documentación de la configuración
# --------------------------------------------------------------------------- #

def test_el_target_web_no_lanza_mas_procesos_de_los_permitidos():
    """Cada invocación es un node entero. Sin cota, N peticiones a la vez son
    N procesos; con ella, la que no cabe espera y, si no le toca, lo dice."""
    from capas import config, web

    dentro, soltar = threading.Event(), threading.Event()
    lanzados = []

    def lanzar(cmd):
        lanzados.append(cmd)
        dentro.set()
        soltar.wait(30)
        return _proceso(cmd, 1, json.dumps({"diagnostics": [
            {"code": "WEB101", "line": 1, "message": "x"}]}))

    primero = []
    with _con_node_falso(lanzar), \
            _parche(web, _cupo=threading.BoundedSemaphore(1)), \
            _parche(config, WEB_TIEMPO=1):
        hilo = threading.Thread(
            target=lambda: primero.append(web.bajar(b"x", {})))
        hilo.start()
        try:
            assert dentro.wait(30), "el primero no llegó a lanzarse"
            fases, diagnosticos, proveedor = web.bajar(b"x", {})
        finally:
            soltar.set()
            hilo.join(30)
    assert len(lanzados) == 1, "el segundo no debía lanzar otro proceso"
    assert fases["wasm"]["status"] == "no_disponible", fases
    assert "ocupado" in fases["wasm"]["reason"] and diagnosticos == []
    assert primero[0][2]["status"] == "error_del_programa", primero


def test_un_cliente_que_no_termina_de_enviar_no_ocupa_un_hilo_para_siempre():
    import socket
    import time
    from capas import config

    def comprobar(base):
        puerto = int(base.rsplit(":", 1)[1])
        inicio = time.monotonic()
        with socket.create_connection(("127.0.0.1", puerto), timeout=30) as s:
            # promete 50 bytes de cuerpo y no envía ninguno
            s.sendall(b"POST /api/compile HTTP/1.1\r\nHost: x\r\n"
                      b"Content-Type: application/json\r\n"
                      b"Content-Length: 50\r\n\r\n")
            assert s.recv(1024) == b"", "se esperaba que cerrase sin responder"
        assert time.monotonic() - inicio < 15, "tardó de más en soltarlo"
        codigo, _, _ = _pedir(base, "/api/health")
        assert codigo == 200, "el servidor dejó de atender"

    with _parche(config, ESPERA_CLIENTE=1):
        _con_servidor(comprobar)


def test_la_configuracion_documentada_es_la_que_se_lee():
    """Tres sitios nombran las variables: el código que las lee, la plantilla
    ``.env.example`` y la tabla del README. Una que falte en uno es una
    variable que alguien no sabrá que existe."""
    import re

    def leer(*partes):
        with open(os.path.join(_REPO_ROOT, *partes), encoding="utf-8") as fh:
            return fh.read()

    codigo = leer("playground", "capas", "config.py")
    leidas = set(re.findall(r'(?:environ\.get|_entero)\("([A-Z_]+)"', codigo))
    assert {"HOST", "PORT", "SURIAX_CORS_ORIGIN"} <= leidas, leidas

    plantilla = set(re.findall(r"^([A-Z_]+)=", leer(".env.example"), re.M))
    assert plantilla == leidas, plantilla ^ leidas

    readme = leer("playground", "README.md")
    tabla = readme[readme.index("### Configuración"):readme.index("## Publicarlo")]
    documentadas = set(re.findall(r"^\| `([A-Z_]+)` \|", tabla, re.M))
    assert documentadas == leidas, documentadas ^ leidas


def test_el_procfile_publica_el_servidor():
    """Se perdió una vez y el README lo seguía citando. En una plataforma hay
    que escuchar en todas las interfaces: con el valor por defecto el
    servidor arrancaría y nadie llegaría a él."""
    with open(os.path.join(_REPO_ROOT, "Procfile"), encoding="utf-8") as fh:
        orden = fh.read().strip()
    assert orden == "web: HOST=0.0.0.0 python playground/server.py", orden


# --------------------------------------------------------------------------- #
# lo que se puede usar en el playground
#
# El playground corre con el perfil 'playground' del target web: ninguna
# capacidad habilitada y una lista blanca de librerías. Qué entra y qué no se
# decide en ``web/src/target/policy.ts``, como datos; aquí se fija que el
# servidor lo PIDE y lo que eso significa para quien escribe un programa.
# --------------------------------------------------------------------------- #

def test_el_servidor_le_pide_al_target_el_perfil_del_playground():
    """Sin pedirlo, el target usa el suyo, que deja importar cualquier
    librería: el servidor creería estar contenido y no lo estaría."""
    from server import compile_source

    ordenes = []

    def lanzar(cmd):
        ordenes.append(cmd)
        return _proceso(cmd, 1, json.dumps({"diagnostics": [
            {"code": "WEB007", "line": 1, "message": "x"}]}))

    with _con_node_falso(lanzar):
        compile_source(_VALIDO)
    cmd = ordenes[0]
    assert cmd[cmd.index("--policy") + 1] == "playground", cmd


def test_una_libreria_denegada_da_UN_diagnostico_que_dice_por_que():
    """Con el perfil del target, un ``#import text`` daba cuarenta ``WEB002``
    dentro de una librería que el usuario no escribió. Con el del playground
    es uno, en su ``#import``, y distingue "nunca" de "todavía no"."""
    if shutil.which("node") is None:
        omitir("node no está instalado; el target web no corre")
    from server import compile_source

    casos = {
        "#import sistema.archivos as arc": "no tiene archivos, procesos ni rutas",
        "#import sistema.proceso as pro": "no tiene archivos, procesos ni rutas",
        "#import text": "todavía no representa",
        "#import mem": "runtime nativo",
    }
    for importe, motivo in casos.items():
        datos = compile_source(f"#from io #import stdp\n{importe}\n"
                               "fn main() -> int { return 0; }\n")
        _frontend_intacto(datos)
        denegadas = [d for d in datos["diagnostics"] if d["code"] == "WEB007"]
        assert len(denegadas) == 1, (importe, datos["diagnostics"])
        assert denegadas[0]["line"] == 2 and motivo in denegadas[0]["message"], \
            denegadas
        assert denegadas[0]["kind"] == "unsupported"
        # y la librería no se revisa por dentro
        assert not [d for d in datos["diagnostics"] if d["code"] == "WEB002"], \
            (importe, datos["diagnostics"][:3])
        assert datos["phases"]["wasm"]["status"] == "error_del_programa"


def test_lo_que_el_target_sabe_ejecutar_si_pasa():
    if shutil.which("node") is None:
        omitir("node no está instalado; el target web no corre")
    from server import compile_source

    datos = compile_source(
        "#from io #import stdp\n"
        "#import math.basic as mb\n"
        "#import excepciones\n"
        "fn main() -> int {\n"
        '    stdp.println(f"{mb.max(2.0, 3.0)}");\n'
        "    return 0;\n"
        "}\n")
    assert datos["status"] == "ok", (datos["diagnostics"],
                                     datos["phases"]["wasm"])
    assert "(module" in datos["phases"]["wasm"]["wat"]


def test_los_mensajes_no_publican_las_rutas_del_servidor():
    """``SEM009`` enumera las rutas donde buscó. En la CLI ayudan; a un
    visitante solo le cuentan cómo está montado el servidor."""
    from capas import config, web
    from server import compile_source

    with _parche(web, version_de_node=lambda: None):
        datos = compile_source("#import noexiste\n"
                               "fn main() -> int { return 0; }\n")
    mensaje = next(d["message"] for d in datos["diagnostics"]
                   if d["code"] == "SEM009")
    assert "<repo>" in mensaje, mensaje
    todo = json.dumps(datos, ensure_ascii=False)
    for ruta in (config.REPO, config.REPO.replace("\\", "/"),
                 config.REPO.replace("\\", "\\\\")):
        assert ruta not in todo, ruta


# --------------------------------------------------------------------------- #
# la página: de dónde puede cargar cosas
# --------------------------------------------------------------------------- #

def _estatico(nombre):
    with open(os.path.join(_REPO_ROOT, "playground", "static", nombre),
              encoding="utf-8") as fh:
        return fh.read()


def test_la_pagina_lleva_su_politica_de_contenido():
    """Todo de este servidor, salvo lo que se nombra. Sin ella, un script
    inyectado en la página podría cargar código de cualquier sitio."""
    def comprobar(base):
        with urllib.request.urlopen(f"{base}/", timeout=30) as r:
            csp = r.headers["Content-Security-Policy"]
        reglas = dict(parte.strip().split(" ", 1) for parte in csp.split(";"))
        assert reglas["default-src"] == "'none'", csp
        assert reglas["script-src"] == "'self' https://cdn.jsdelivr.net", csp
        assert reglas["connect-src"] == "'self'", csp
        assert "'unsafe-inline'" not in reglas["script-src"]
        assert "'unsafe-eval'" not in csp
        # los archivos que no son la página no la necesitan
        with urllib.request.urlopen(f"{base}/app.js", timeout=30) as r:
            assert r.headers["Content-Security-Policy"] is None

    _con_servidor(comprobar)


def test_lo_que_la_pagina_carga_de_fuera_tiene_la_version_fija():
    """Mermaid es código de un tercero que entra en la página. Con un rango
    (``@11``) cambia el día que publican otra versión, sin que nadie aquí lo
    haya visto; con la versión exacta, subirla es una decisión."""
    import re

    fuentes = _estatico("app.js") + _estatico("grafo.js") + \
        _estatico("index.html")
    externos = set(re.findall(r'''(?:import\(\s*|src=|href=)["'](https?://[^"']+)''',
                              fuentes))
    scripts = {u for u in externos if "cdn." in u or u.endswith((".js", ".mjs"))}
    assert scripts, "se esperaba al menos Mermaid"
    for url in scripts:
        assert url.startswith("https://cdn.jsdelivr.net/npm/"), url
        assert re.search(r"@\d+\.\d+\.\d+/", url), f"versión sin fijar: {url}"
    # y la página no trae scripts ni estilos escritos dentro del HTML
    html = _estatico("index.html")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html), "script en línea"
    assert " onclick=" not in html and "javascript:" not in html


# --------------------------------------------------------------------------- #
# lo que el frontend acepta, el target lo lee
#
# Tres cosas que un programa VÁLIDO hacía salir como un fallo que no era
# suyo: una prueba (`test`/`expect`) era ".phir corrupto", una suma de cien
# términos pasaba el frontend y el lector del target la rechazaba, y una de
# trescientos tumbaba al emisor del HIR.
# --------------------------------------------------------------------------- #

_CON_PRUEBA = """\
#from io #import stdp

fn doble(int n) -> int { return n + n; }

fn main() -> int {
    stdp.println(f"{doble(21)}");
    return 0;
}

test "doble" {
    expect (doble(2) == 4) { stdp.println("bien"); };
} errfinally {
    stdp.println("fallo");
} finally {
    stdp.println("fin");
}
"""


def test_un_programa_con_pruebas_compila_para_el_target_web():
    """El target no corre pruebas —las quita y ejecuta el programa—, pero
    tiene que leerlas: antes un `expect` era una sentencia "sin variante" y
    el diagnóstico decía que el .phir estaba corrupto."""
    if shutil.which("node") is None:
        omitir("node no está instalado; el target web no corre")
    from server import compile_source

    datos = compile_source(_CON_PRUEBA)
    assert datos["status"] == "ok", (datos["diagnostics"],
                                     datos["phases"]["wasm"].get("reason"))
    assert "doble" in datos["phases"]["wasm"]["pretty"]


def _suma(terminos):
    return ("#from io #import stdp\n"
            "fn main() -> int {\n"
            "    var int total = " + " + ".join(["1"] * terminos) + ";\n"
            '    stdp.println(f"{total}");\n'
            "    return 0;\n"
            "}\n")


def test_una_expresion_larga_que_cabe_llega_hasta_el_webassembly():
    """Una suma de 400 términos no anida al escribirse, pero sí en el árbol
    y en el HIR. Cabe en el límite del lenguaje, así que tiene que caber en
    todos los que vienen después."""
    if shutil.which("node") is None:
        omitir("node no está instalado; el target web no corre")
    from server import compile_source

    datos = compile_source(_suma(400))
    assert datos["status"] == "ok", (datos["providers"],
                                     datos["phases"]["wasm"].get("reason"),
                                     datos["phases"]["wasm"].get("detail"))


def test_una_expresion_demasiado_larga_es_un_error_del_programa():
    """...y la que no cabe es `PAR025`, con su línea: un error DEL PROGRAMA.
    Era un `RecursionError` en el emisor del HIR, y el playground lo enseñaba
    como un fallo interno del compilador."""
    from capas import web
    from server import compile_source

    with _parche(web, version_de_node=lambda: None):
        datos = compile_source(_suma(600))
    assert datos["providers"]["compiler"]["status"] == "error_del_programa", \
        datos["providers"]
    assert [(d["code"], d["line"]) for d in datos["diagnostics"]] == \
        [("PAR025", 3)], datos["diagnostics"]


def test_el_lector_del_target_admite_lo_que_el_parser_deja_pasar():
    """El tope del lector (mensajes anidados en el HIR) se calcula desde el
    límite del lenguaje (niveles del árbol): cada nivel son como mucho dos
    mensajes. Valía 200 "porque el frontend no produce árboles tan hondos",
    y nadie comprobaba esa frase."""
    import re
    from src.frontend.parser.grammar.program import MAX_NESTING

    with open(os.path.join(_REPO_ROOT, "web", "src", "hir", "wire.ts"),
              encoding="utf-8") as fh:
        tope = int(re.search(r"MAX_NESTING_DEPTH = (\d+);", fh.read()).group(1))
    assert tope >= 2 * MAX_NESTING, (tope, MAX_NESTING)

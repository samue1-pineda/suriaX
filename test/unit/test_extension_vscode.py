"""unit/extension_vscode — la extensión dice lo mismo que el compilador.

La extensión de VS Code (``tooling/vscode``) tiene una parte declarativa que
se GENERA desde ``lang_info`` y un cliente delgado escrito a mano (ver
``tooling/vscode/ARQUITECTURA.md``). Aquí se fijan tres cosas:

 1. que lo que hay en el disco es lo que se generaría hoy (una palabra nueva
    en el lenguaje sin regenerar es una palabra que el editor no pinta);
 2. que la gramática de colores **decide lo mismo que el lexer**: se tokeniza
    cada fuente del repositorio con el lexer de verdad y con la gramática, y
    cada token tiene que caer en el ámbito de su categoría;
 3. que el código del cliente no trae dependencias ni ejecuta nada que una
    carpeta sin confianza pueda elegir.

Para lo segundo hace falta ejecutar la gramática sin VS Code. ``_Gramatica``
es un intérprete mínimo de TextMate: lo justo para las construcciones que el
generador usa (``match``, ``begin``/``end``, capturas, ``include`` del
repositorio y de ``$self``). No es el motor del editor —las expresiones
regulares las evalúa ``re`` de Python y no Oniguruma—, así que prueba la
gramática, no al editor.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import lex  # noqa: E402

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_EXTENSION = os.path.join(_REPO, "tooling", "vscode")
if _EXTENSION not in sys.path:
    sys.path.insert(0, _EXTENSION)


def _leer(nombre):
    with open(os.path.join(_EXTENSION, nombre), encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
# un intérprete mínimo de TextMate
# --------------------------------------------------------------------------- #

def _regex(patron: str):
    """Una expresión de la gramática, para ``re``. Las dos clases de Unicode
    que el generador usa se traducen; el resto es sintaxis común."""
    patron = patron.replace("[\\p{L}\\p{N}_]", "\\w").replace("[\\p{L}_]", "[^\\W\\d]")
    assert "\\p{" not in patron, f"clase Unicode sin traducir: {patron}"
    return re.compile(patron)


class _Gramatica:
    def __init__(self, datos: dict):
        self.datos = datos
        self.repositorio = datos["repository"]
        self._cache: dict = {}

    def _reglas(self, patrones):
        """Aplana los ``include`` a una lista de reglas con ``match``/``begin``."""
        salida = []
        for patron in patrones:
            destino = patron.get("include")
            if destino is None:
                if "match" in patron or "begin" in patron:
                    salida.append(patron)
                else:
                    salida.extend(self._reglas(patron.get("patterns", [])))
            elif destino == "$self":
                salida.extend(self._reglas(self.datos["patterns"]))
            elif destino.startswith("#"):
                salida.extend(self._reglas([self.repositorio[destino[1:]]]))
            # 'source.cpp' y demás gramáticas ajenas: aquí no pintan nada
        return salida

    def _de(self, regla) -> list:
        clave = id(regla)
        if clave not in self._cache:
            self._cache[clave] = self._reglas(
                self.datos["patterns"] if regla is None else regla.get("patterns", []))
        return self._cache[clave]

    def ambitos(self, texto: str) -> list:
        """El ámbito más interno de cada carácter (``""`` si ninguno)."""
        salida = [""] * len(texto)
        pila = []                       # reglas begin/end abiertas
        pos = 0
        for linea in texto.splitlines(keepends=True):
            fin_linea = pos + len(linea)
            i = pos
            while i <= fin_linea:
                abierta = pila[-1] if pila else None
                mejor = None            # (inicio, orden, regla, match, cierra)
                if abierta is not None:
                    m = _regex(abierta["end"]).search(texto, i, fin_linea)
                    if m:
                        mejor = (m.start(), -1, abierta, m, True)
                for orden, regla in enumerate(self._de(abierta)):
                    m = _regex(regla.get("match") or regla["begin"]).search(
                        texto, i, fin_linea)
                    if m and (mejor is None or (m.start(), orden) < mejor[:2]):
                        mejor = (m.start(), orden, regla, m, False)
                dentro = (abierta or {}).get("name", "")
                if mejor is None:
                    self._pinta(salida, i, fin_linea, dentro)
                    break
                inicio, _, regla, m, cierra = mejor
                self._pinta(salida, i, inicio, dentro)
                if cierra:
                    self._pinta(salida, inicio, m.end(), dentro)
                    self._capturas(salida, regla.get("endCaptures"), m)
                    pila.pop()
                elif "match" in regla:
                    self._pinta(salida, inicio, m.end(), regla.get("name", dentro))
                    self._capturas(salida, regla.get("captures"), m)
                else:
                    self._pinta(salida, inicio, m.end(), regla.get("name", dentro))
                    self._capturas(salida, regla.get("beginCaptures"), m)
                    pila.append(regla)
                i = m.end() if m.end() > i else i + 1
            pos = fin_linea
        return salida

    @staticmethod
    def _pinta(salida, desde, hasta, nombre):
        if nombre:
            for k in range(desde, min(hasta, len(salida))):
                salida[k] = nombre

    def _capturas(self, salida, capturas, m):
        for indice, datos in (capturas or {}).items():
            if m.group(int(indice)) is not None and "name" in datos:
                self._pinta(salida, m.start(int(indice)), m.end(int(indice)),
                            datos["name"])


def _gramatica():
    return _Gramatica(_leer(os.path.join("syntaxes", "suriax.tmLanguage.json")))


# --------------------------------------------------------------------------- #
# lo generado está al día
# --------------------------------------------------------------------------- #

def test_los_archivos_de_la_extension_estan_al_dia():
    """Añadir una palabra al lenguaje y no regenerar deja al editor atrás.
    ``python tooling/vscode/generar.py`` los pone al día."""
    import generar

    assert generar.desfasados() == [], (
        "regenera con: python tooling/vscode/generar.py")


def test_la_extension_reconoce_los_archivos_de_suriaX():
    from include.lang_info import build_language_info

    info = build_language_info()
    manifiesto = _leer("package.json")
    lenguaje, = manifiesto["contributes"]["languages"]
    assert lenguaje["extensions"] == info["extensions"] == [".srcx", ".libsrx"]
    assert _leer(os.path.join("syntaxes", "suriax.tmLanguage.json"))["fileTypes"] \
        == ["srcx", "libsrx"]


#: el ÚNICO código de la extensión que corre dentro del editor. Añadir un
#: archivo aquí es una decisión (ver ARQUITECTURA.md), no un accidente.
_CODIGO_DEL_CLIENTE = {"extension.js", "rpc.js"}

#: lo que ese código puede pedir con ``require``: la API del editor y
#: módulos de node. Nada de npm.
_REQUIRE_PERMITIDOS = {"vscode", "child_process", "path"}


def test_el_codigo_de_la_extension_es_un_cliente_sin_dependencias():
    """La extensión ya carga código en el editor —el cliente que lanza el
    servidor de lenguaje—, y esta prueba cambió A PROPÓSITO el día que lo
    hizo. Lo que conserva es su espíritu: nada de terceros sin auditar.
    Ni paquetes de npm, ni scripts que npm/vsce ejecutarían, ni un paso de
    compilación: dos archivos de JavaScript escritos a mano, que solo piden
    la API de VS Code, módulos de node y el uno al otro."""
    manifiesto = _leer("package.json")
    for clave in ("browser", "dependencies", "devDependencies", "optionalDependencies",
                  "peerDependencies", "bundledDependencies", "scripts", "extensionDependencies"):
        assert clave not in manifiesto, clave
    assert manifiesto["main"] == "./extension.js"
    assert sorted(manifiesto["activationEvents"]) == ["onDebugResolve:suriax",
                                                      "onLanguage:suriax"]
    codigo = {n for n in os.listdir(_EXTENSION) if n.endswith((".js", ".ts", ".mjs", ".cjs"))}
    assert codigo == _CODIGO_DEL_CLIENTE, codigo
    for prohibido in ("node_modules", "package-lock.json", "yarn.lock", "tsconfig.json"):
        assert not os.path.exists(os.path.join(_EXTENSION, prohibido)), prohibido
    for nombre in sorted(_CODIGO_DEL_CLIENTE):
        with open(os.path.join(_EXTENSION, nombre), encoding="utf-8") as fh:
            fuente = fh.read()
        # el editor lo comprueba con el verificador de TypeScript, sin compilarlo
        assert fuente.startswith("// @ts-check"), nombre
        pedidos = set(re.findall(r"""require\(\s*['"]([^'"]+)['"]\s*\)""", fuente))
        ajenos = {p for p in pedidos if not p.startswith("./")} - _REQUIRE_PERMITIDOS
        assert not ajenos, f"{nombre} pide {sorted(ajenos)}"
        for propio in (p for p in pedidos if p.startswith("./")):
            assert os.path.basename(propio) + ".js" in _CODIGO_DEL_CLIENTE, (nombre, propio)


def test_la_extension_se_genero_con_el_lang_info_del_compilador():
    """El cliente compara esta versión con la que anuncia el servidor: si
    alguien instala una extensión vieja contra un compilador nuevo, se le
    dice que los colores pueden no coincidir."""
    from include.lang_info import LANG_INFO_VERSION

    assert _leer("package.json")["suriax"] == {"langInfoVersion": LANG_INFO_VERSION}


def test_los_ajustes_que_ejecutan_algo_no_los_decide_una_carpeta_sin_confianza():
    """``pythonPath`` y ``compilerRoot`` deciden QUÉ se ejecuta. Una carpeta
    clonada no puede elegirlos (``restrictedConfigurations``), y sin
    confianza la extensión solo colorea."""
    manifiesto = _leer("package.json")
    ajustes = manifiesto["contributes"]["configuration"]["properties"]
    assert set(ajustes) == {"suriax.pythonPath", "suriax.compilerRoot"}
    confianza = manifiesto["capabilities"]["untrustedWorkspaces"]
    assert confianza["supported"] == "limited"
    assert set(confianza["restrictedConfigurations"]) == set(ajustes)
    comando, = manifiesto["contributes"]["commands"]
    assert comando["command"] == "suriax.reiniciarServidor"
    with open(os.path.join(_EXTENSION, "extension.js"), encoding="utf-8") as fh:
        cliente = fh.read()
    assert "workspace.isTrusted" in cliente
    for nombre in (*ajustes, comando["command"]):
        assert f"'{nombre.split('.', 1)[1]}'" in cliente or f"'{nombre}'" in cliente, nombre


def test_depurar_lanza_el_depurador_del_compilador():
    """La extensión no trae un depurador: lanza el del compilador
    (``--dap``) con ``lanzar.py``. Así el mismo depurador sirve a cualquier
    editor. ``depurar.py`` es el respaldo declarativo del manifiesto, por si
    el JavaScript no se activa."""
    import lanzar

    manifiesto = _leer("package.json")
    depurador, = manifiesto["contributes"]["debuggers"]
    assert depurador["type"] == "suriax" and depurador["languages"] == ["suriax"]
    assert depurador["program"] == "./depurar.py"
    assert os.path.isfile(os.path.join(_EXTENSION, depurador["program"]))
    assert manifiesto["contributes"]["breakpoints"] == [{"language": "suriax"}]
    inicial, = depurador["initialConfigurations"]
    assert inicial["program"] == "${file}" and inicial["request"] == "launch"
    # ...y desde este repositorio, el lanzador encuentra al compilador
    assert os.path.samefile(lanzar.raiz_del_compilador(), _REPO)
    assert lanzar.MODOS == ("--lsp", "--dap")
    import contextlib
    import io
    dicho = io.StringIO()
    with contextlib.redirect_stderr(dicho):
        assert lanzar.main(["--emit-lang-info"]) == 2, "solo lanza los dos servidores"
    assert dicho.getvalue().startswith("uso: python lanzar.py")


def test_las_banderas_que_la_extension_anuncia_son_las_que_el_depurador_acepta():
    """``"flags"`` de launch.json las lee el depurador con el analizador de
    la terminal. La extensión las NOMBRA en su ayuda: si anunciara una que el
    depurador rechaza, o callara una que acepta, la ayuda mentiría."""
    import generar
    from cli.depurar import banderas

    propiedades = _leer("package.json")["contributes"]["debuggers"][0][
        "configurationAttributes"]["launch"]["properties"]
    assert propiedades["flags"]["type"] == "array"
    for bandera in generar.BANDERAS_AL_DEPURAR:
        assert bandera in propiedades["flags"]["description"], bandera

    programa = os.path.join(_REPO, "V0", "main.py")
    for bandera in generar.BANDERAS_AL_DEPURAR:
        banderas(programa, [bandera])               # no lanza: se acepta
    # y TODA bandera del compilador que no está en la lista se rechaza
    from cli.args import build_parser
    del_compilador = {opcion for accion in build_parser()._actions
                      for opcion in accion.option_strings
                      if opcion.startswith("--") and opcion not in ("--help", "--version")}
    assert set(generar.BANDERAS_AL_DEPURAR) <= del_compilador
    for bandera in sorted(del_compilador - set(generar.BANDERAS_AL_DEPURAR)):
        accion = next(a for a in build_parser()._actions
                      if bandera in a.option_strings)
        escritas = [bandera] if accion.nargs in (0, "?") else [bandera, "x"]
        try:
            banderas(programa, escritas)
        except ValueError:
            continue
        raise AssertionError(f"el depurador acepta {bandera} y la extensión "
                             "no la anuncia")


def test_la_version_de_la_extension_es_la_del_compilador():
    from version import VERSION

    assert _leer("package.json")["version"] == VERSION


def test_cada_archivo_que_el_manifiesto_nombra_existe():
    aporta = _leer("package.json")["contributes"]
    rutas = [aporta["languages"][0]["configuration"],
             aporta["grammars"][0]["path"], aporta["snippets"][0]["path"]]
    for ruta in rutas:
        assert os.path.isfile(os.path.join(_EXTENSION, ruta)), ruta


def test_los_fragmentos_son_los_del_compilador():
    from include.lang_info import build_language_info

    del_compilador = build_language_info()["snippets"]
    fragmentos = _leer(os.path.join("snippets", "suriax.json"))
    assert len(fragmentos) == len(del_compilador), "dos fragmentos se pisaron"
    assert sorted(f["prefix"] for f in fragmentos.values()) == \
        sorted(f["prefix"] for f in del_compilador)
    assert all("\n".join(f["body"]) for f in fragmentos.values())


# --------------------------------------------------------------------------- #
# los colores dicen lo mismo que el lexer
# --------------------------------------------------------------------------- #

#: categoría del lexer -> cómo debe empezar el ámbito de la gramática.
#: ``None``: ese token no lleva un ámbito de palabra reservada (es un nombre).
def _esperado(categoria: str, tipo: str):
    import generar

    if tipo == "DIRECTIVE":
        return (generar.AMBITO_DIRECTIVA,)
    if tipo == "DECORATOR":
        return (generar.AMBITO_DECORADOR,)
    if tipo == "CHAR_LIT":
        return (generar.AMBITO_CARACTER, generar.AMBITO_ESCAPE)
    if tipo in ("INT_LIT", "FLOAT_LIT"):
        return ("constant.numeric",)
    if categoria == "string":
        return ("string.quoted.double",)
    if categoria == "operator":
        return (generar.AMBITO_OPERADOR,)
    if categoria == "punctuation":
        return (generar.AMBITO_PUNTUACION,)
    if categoria in generar.AMBITOS:
        return (generar.AMBITOS[categoria],)
    return None


_NO_ES_PALABRA = ("entity.name.function", "support.function", "")


def _desacuerdos(fuente: str, archivo: str, gramatica, categorias) -> list:
    tokens, errores = lex(fuente, file=archivo)
    if errores:
        return []                       # un fuente con errores léxicos: no aplica
    ambitos = gramatica.ambitos(fuente)
    inicios = [0]
    for linea in fuente.splitlines(keepends=True):
        inicios.append(inicios[-1] + len(linea))
    malos = []
    for token in tokens:
        tipo = token.type.name
        if tipo in ("EOF", "RAW_BLOCK") or not token.lexeme:
            continue
        donde = inicios[token.ln - 1] + token.col - 1
        if fuente[donde:donde + len(token.lexeme)] != token.lexeme:
            continue                    # el lexema no es texto literal del fuente
        ambito = ambitos[donde]
        esperado = _esperado(categorias.get(tipo, ""), tipo)
        if esperado is None:
            bien = ambito.startswith(_NO_ES_PALABRA[:2]) or ambito == ""
        else:
            bien = ambito.startswith(esperado)
        if not bien:
            malos.append((archivo, token.ln, token.col, tipo, token.lexeme[:20],
                          ambito or "(sin ámbito)"))
    return malos


def _fuentes():
    rutas = []
    for patron in ("lib/**/*.libsrx", "src/**/*.libsrx", "src/**/*.srcx",
                   "test/e2e/**/*.srcx", "test/web/fixtures/*.srcx"):
        rutas += glob.glob(os.path.join(_REPO, patron), recursive=True)
    return sorted(set(rutas))


def test_la_gramatica_colorea_cada_token_como_lo_clasifica_el_lexer():
    """Sobre TODO el suriaX del repositorio: la librería estándar, el
    compilador V1 y los programas de prueba. Un resaltador que decide por su
    cuenta acaba pintando ``move`` como un nombre."""
    from include.lang_info import build_language_info

    categorias = build_language_info()["token_categories"]
    gramatica = _gramatica()
    rutas = _fuentes()
    assert len(rutas) > 50, f"se esperaba un corpus grande, hay {len(rutas)}"
    malos, vistos = [], 0
    for ruta in rutas:
        with open(ruta, encoding="utf-8") as fh:
            fuente = fh.read().replace("\r\n", "\n")
        vistos += 1
        malos += _desacuerdos(fuente, os.path.relpath(ruta, _REPO), gramatica,
                              categorias)
    assert not malos, f"{len(malos)} desacuerdos en {vistos} archivos: {malos[:6]}"


def _ambitos_de(fuente: str) -> dict:
    """``{trozo de texto: ámbito}`` de los trozos pintados, para leer un caso."""
    ambitos = _gramatica().ambitos(fuente)
    salida, i = {}, 0
    while i < len(fuente):
        j = i
        while j < len(fuente) and ambitos[j] == ambitos[i]:
            j += 1
        if ambitos[i] and fuente[i:j].strip():
            salida.setdefault(fuente[i:j].strip(), ambitos[i])
        i = j
    return salida


def test_lo_que_el_lexer_no_ve_tambien_se_pinta():
    """Los comentarios no son tokens, y el interior de una cadena tampoco: la
    comparación con el lexer no los cubre. Se fijan aquí."""
    vistos = _ambitos_de(
        '// una línea\n'
        '/- un bloque\n'
        '   de dos líneas -/\n'
        'fn saluda(str nombre) -> void {\n'
        '    var str s = f"hola {nombre!r:10} {{literal}} \\n";\n'
        "    var char c = '\\n';\n"
        '    __free__(s); mide(s);\n'
        '}\n')
    assert vistos["// una línea"] == "comment.line.double-slash.suriax"
    # un comentario de bloque sigue abierto en la línea siguiente
    assert vistos["/- un bloque\n   de dos líneas -/"] == "comment.block.suriax"
    assert vistos["saluda"] == "entity.name.function.suriax"
    assert vistos["{{"] == "constant.character.escape.suriax"
    assert vistos["\\n"] == "constant.character.escape.suriax"
    assert vistos["!r:10"] == "constant.other.format.suriax"
    assert vistos["'\\n'"] == "string.quoted.single.suriax"
    assert vistos["__free__"] == "support.function.hook.suriax"
    assert vistos["mide"] == "entity.name.function.call.suriax"
    # dentro del hueco de un f-string vuelve a ser código
    assert "nombre" not in vistos or not vistos["nombre"].startswith("string")


def test_una_palabra_reservada_dentro_de_un_nombre_no_se_pinta():
    """``importe`` no es ``import``, ni ``año_int`` es ``int``: los nombres de
    suriaX admiten letras de cualquier alfabeto y la gramática no usa el
    límite de palabra de ASCII."""
    vistos = _ambitos_de("var int entero = 1; var int ñint = 2; var int importe = 3;\n"
                         "var int test_ = 4; var int ifé = 5;\n")
    assert vistos["int"] == "storage.type.primitive.suriax"
    for nombre in ("entero", "ñint", "importe", "test_", "ifé"):
        assert nombre not in vistos, (nombre, vistos.get(nombre))


def test_un_bloque_extern_no_se_pinta_como_suriaX():
    """Lo de dentro es C++: sus ``if`` y sus ``int`` no son los de suriaX, y
    el bloque acaba en SU llave, no en la primera que aparezca."""
    fuente = ("#extern cpp{\n"
              "int f() { if (true) { return 1; } return 0; }\n"
              "}\n"
              "fn main() -> int { return 0; }\n")
    ambitos = _gramatica().ambitos(fuente)
    dentro = fuente.index("int f()")
    fuera = fuente.index("fn main")
    assert ambitos[fuente.index("#extern")] == "keyword.control.directive.suriax"
    assert not any("suriax" in a for a in ambitos[dentro:fuente.index("}\nfn")]), \
        sorted(set(ambitos[dentro:fuera]))
    assert ambitos[fuera] == "keyword.declaration.suriax"
    assert ambitos[fuente.index("int {")] == "storage.type.primitive.suriax"

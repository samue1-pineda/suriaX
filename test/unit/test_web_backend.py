"""unit/web_backend — puente entre la suite de Python y la del backend web.

El backend web (``web/``) es TypeScript y trae su propia suite, que corre
con el *test runner* de node (sin frameworks, igual que esta). Este módulo
la ENGANCHA a ``python test/main.py`` para que siga habiendo **un solo
comando** que corra todo: si el lector del HIR deja de entender un ``.phir``,
el fallo aparece en la misma corrida que los demás.

Requisitos y degradación: node ejecuta los ``.ts`` borrando los tipos —
nativo desde la v23, tras la bandera ``--experimental-strip-types`` en la
v22. Sin node (o con uno anterior), estos tests **se saltan con aviso** en
vez de fallar: el backend web no es una dependencia del compilador y la CI
del frontend no puede quedar roja por no tener node instalado.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
#: el CODIGO del backend web.
_WEB_DIR = os.path.join(_REPO_ROOT, "web")
#: y su SUITE, que vive con el resto de las pruebas del proyecto (todas bajo
#: 'test/'). Estan separadas a proposito: en 'web/' queda lo que se publica.
_WEB_TESTS = os.path.join(_REPO_ROOT, "test", "web")

#: node < 22 no sabe ejecutar TypeScript de ninguna forma.
_MIN_NODE_MAJOR = 22
#: desde node 23 el borrado de tipos está activo sin bandera.
_STRIP_TYPES_BY_DEFAULT = 23


def _node_major() -> int | None:
    """Versión mayor de node, o ``None`` si no está disponible."""
    node = shutil.which("node")
    if node is None:
        return None
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True,
                             timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    version = out.stdout.strip().lstrip("v")
    try:
        return int(version.split(".", 1)[0])
    except ValueError:
        return None


def _skip(reason: str) -> None:
    print(f"      (omitido: {reason})", file=sys.stderr)


def test_suite_del_backend_web():
    """Corre ``node --test test/web/*.test.ts`` y exige que pase entera."""
    major = _node_major()
    if major is None:
        _skip("node no está instalado; la suite del backend web no se ejecuta")
        return
    if major < _MIN_NODE_MAJOR:
        _skip(f"node v{major} no ejecuta TypeScript (se necesita v{_MIN_NODE_MAJOR}+)")
        return

    cmd = ["node", "--test"]
    if major < _STRIP_TYPES_BY_DEFAULT:
        cmd.insert(1, "--experimental-strip-types")
    # patrón entre comillas: lo expande node, no la shell (aquí no hay shell).
    cmd.append("*.test.ts")

    result = subprocess.run(cmd, cwd=_WEB_TESTS, capture_output=True, text=True,
                            timeout=300)
    if result.returncode != 0:
        # la salida del runner de node ya dice qué test falló y por qué.
        raise AssertionError(
            "la suite del backend web falló:\n"
            + result.stdout[-4000:]
            + result.stderr[-2000:]
        )


def test_el_reserializador_produce_protobuf_valido():
    """El `.phir` que reescribe el backend web lo acepta el protobuf REAL.

    Es la prueba que la suite de TypeScript no puede hacer sola: allí el
    escritor y el lector son míos, así que podrían compartir un malentendido
    del formato y las pruebas de ida y vuelta pasarían igual. Aquí los bytes
    los valida `google.protobuf` con el descriptor generado del `.proto`, y
    se comparan los DOS módulos en el formato de texto canónico — que además
    normaliza el orden de las entradas de los `map`, lo único que protobuf no
    fija.
    """
    major = _node_major()
    if major is None or major < _MIN_NODE_MAJOR:
        _skip("node no disponible para re-serializar")
        return
    try:
        from google.protobuf import text_format  # noqa: F401
        from src.HIR.stubs import load_hir_pb2
        pb = load_hir_pb2()
    except Exception as exc:  # noqa: BLE001 - protobuf/protoc es opcional aquí
        _skip(f"protobuf no disponible ({exc.__class__.__name__})")
        return

    original = os.path.join(_WEB_TESTS, "fixtures", "calc.phir")
    with tempfile.TemporaryDirectory() as tmp:
        reescrito = os.path.join(tmp, "reescrito.phir")
        cmd = ["node"]
        if major < _STRIP_TYPES_BY_DEFAULT:
            cmd.append("--experimental-strip-types")
        cmd += [os.path.join(_WEB_DIR, "main.ts"), original, "--reencode", reescrito]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, (
            f"el re-serializador falló:\n{result.stdout}\n{result.stderr}")

        from google.protobuf import text_format

        def _leer(ruta):
            modulo = pb.Module()
            with open(ruta, "rb") as fh:
                modulo.ParseFromString(fh.read())   # falla si los bytes no valen
            return text_format.MessageToString(modulo)

        assert _leer(reescrito) == _leer(original), (
            "el .phir re-serializado no es equivalente al original")


def test_los_fixtures_phir_estan_presentes():
    """Los golden ``.phir`` del backend web viajan en el repo.

    Se generan con el compilador (``--emit-hir``) y se versionan: sin ellos,
    la suite del web probaría el lector solo contra sus propios bytes, que es
    exactamente la prueba que no vale.
    """
    fixtures = os.path.join(_WEB_TESTS, "fixtures")
    esperados = ["prog.srcx", "prog.phir", "calc.srcx", "calc.phir",
                 "control.srcx", "control.phir",
                 "IO.phir", "IO.stdp.phir", "IO.stdpf.phir"]
    faltan = [f for f in esperados if not os.path.isfile(os.path.join(fixtures, f))]
    assert not faltan, f"faltan fixtures del backend web: {faltan}"


def test_el_backend_web_no_depende_de_node_en_src():
    """``web/src/`` tiene que poder correr en el navegador.

    Un ``import`` de un módulo de node en ``src/`` rompería el target sin que
    nada más lo note (el CLI y las pruebas sí pueden usarlos). Es la misma
    frontera que el frontend mantiene con ``config/``: el compilador no
    importa el paquete de configuración, solo el entrypoint lo hace.
    """
    src = os.path.join(_WEB_DIR, "src")
    ofensores = []
    for carpeta, _dirs, archivos in os.walk(src):
        for nombre in archivos:
            if not nombre.endswith(".ts"):
                continue
            ruta = os.path.join(carpeta, nombre)
            with open(ruta, encoding="utf-8") as fh:
                for n, linea in enumerate(fh, 1):
                    if "node:" in linea and ("import" in linea or "require" in linea):
                        ofensores.append(f"{os.path.relpath(ruta, _REPO_ROOT)}:{n}")
    assert not ofensores, (
        "web/src/ no puede importar módulos de node (rompe el target navegador): "
        + ", ".join(ofensores)
    )


def _enums_del_proto() -> dict:
    """``{nombre: {MIEMBRO: numero}}`` leídos del ``.proto``.

    Se parsea el texto y no el descriptor generado a propósito: este test
    tiene que correr sin protobuf instalado, que es justo la situación en la
    que nadie más está mirando el esquema.
    """
    import re

    ruta = os.path.join(_REPO_ROOT, "V0", "src", "HIR", "proto", "hir.proto")
    with open(ruta, encoding="utf-8") as fh:
        texto = fh.read()
    texto = re.sub(r"//[^\n]*", "", texto)          # los comentarios estorban

    enums = {}
    for m in re.finditer(r"\benum\s+(\w+)\s*\{(.*?)\}", texto, re.S):
        nombre, cuerpo = m.group(1), m.group(2)
        enums[nombre] = {k: int(v) for k, v in
                         re.findall(r"(\w+)\s*=\s*(\d+)\s*;", cuerpo)}
    return enums


def _espejos_del_web() -> dict:
    """``{nombre: {MIEMBRO: numero}}`` leídos de ``web/src/hir/schema.ts``."""
    import re

    ruta = os.path.join(_WEB_DIR, "src", "hir", "schema.ts")
    with open(ruta, encoding="utf-8") as fh:
        texto = fh.read()
    texto = re.sub(r"//[^\n]*", "", texto)
    texto = re.sub(r"/\*.*?\*/", "", texto, flags=re.S)

    espejos = {}
    for m in re.finditer(r"export const (\w+) = \{(.*?)\} as const;", texto, re.S):
        nombre, cuerpo = m.group(1), m.group(2)
        espejos[nombre] = {k: int(v) for k, v in
                           re.findall(r"(\w+)\s*:\s*(\d+)\s*,", cuerpo)}
    return espejos


def test_el_espejo_del_backend_web_coincide_con_el_proto():
    """``schema.ts`` copia a mano los enums del ``.proto``: no pueden divergir.

    El backend web no genera código del ``.proto`` (no hay build step en el
    navegador): reescribe los enums a mano. Eso funciona mientras alguien se
    acuerde de tocar los dos, y no se acordó: ``HookKind`` seguía declarando
    ``MAKE = 2`` —retirado con el modelo por regiones, y ``reserved`` en el
    ``.proto`` desde entonces— y le faltaban ``MIN``/``MAX``, así que un
    ``.phir`` que usara ``__min__`` llegaba al lector como ``__hook10__``.

    Un número **reservado** es un error más grave que uno ausente: significa
    que el espejo puede volver a usarlo para otra cosa, y entonces los dos
    lados leerían el mismo byte como cosas distintas.
    """
    import re

    proto = _enums_del_proto()
    espejos = _espejos_del_web()

    for nombre in ("TypeKind", "SymbolKind", "HookKind"):
        assert nombre in proto, f"el .proto perdió el enum {nombre}"
        assert nombre in espejos, f"schema.ts no declara {nombre}"

        sobran = {k: v for k, v in espejos[nombre].items()
                  if proto[nombre].get(k) != v}
        assert not sobran, (
            f"schema.ts declara en {nombre} lo que el .proto no: {sobran}. "
            "El espejo tiene que copiar el .proto, no adelantarse a él")

    # los números RESERVADOS del .proto no pueden reaparecer en el espejo
    ruta = os.path.join(_REPO_ROOT, "V0", "src", "HIR", "proto", "hir.proto")
    with open(ruta, encoding="utf-8") as fh:
        crudo = re.sub(r"//[^\n]*", "", fh.read())
    for m in re.finditer(r"\benum\s+(\w+)\s*\{(.*?)\}", crudo, re.S):
        nombre, cuerpo = m.group(1), m.group(2)
        if nombre not in espejos:
            continue
        reservados = {int(n) for linea in re.findall(r"reserved\s+([^;]+);", cuerpo)
                      for n in re.findall(r"\b(\d+)\b", linea)}
        usados = reservados & set(espejos[nombre].values())
        assert not usados, (
            f"schema.ts usa en {nombre} números que el .proto tiene RESERVADOS: "
            f"{sorted(usados)}")


def test_el_espejo_del_web_no_se_queda_sin_hooks():
    """Todo hook del compilador tiene nombre en el backend web.

    Sin esto, un hook nuevo llega al lector como ``__hook11__``: no revienta
    —lo cual es peor—, solo enseña un diagnóstico que no nombra nada real.
    """
    import re

    ruta = os.path.join(_WEB_DIR, "src", "hir", "schema.ts")
    with open(ruta, encoding="utf-8") as fh:
        texto = fh.read()
    nombrados = set(re.findall(r"\[HookKind\.(\w+),", texto))
    declarados = set(_espejos_del_web()["HookKind"])
    faltan = declarados - nombrados
    assert not faltan, (
        f"HOOK_KIND_NAMES no nombra estos hooks: {sorted(faltan)}")

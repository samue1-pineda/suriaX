"""unit/paquete_vsix — el ``.vsix`` de la extensión, sin vsce ni npm.

``tooling/vscode/empaquetar.py`` arma el paquete con la biblioteca estándar.
Aquí se fija QUÉ viaja (exactamente la lista de abajo: un archivo nuevo en
la extensión tiene que decidirse, no colarse), que el zip tiene la forma de
un paquete OPC que VS Code instala y que es reproducible.

Que VS Code lo instala de verdad se comprobó a mano, en una carpeta de
extensiones desechable (``code --install-extension X.vsix --extensions-dir
<temporal>``): no se hace aquí porque necesita el editor instalado.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import zipfile
from xml.etree import ElementTree

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_EXTENSION = os.path.join(_REPO, "tooling", "vscode")
for _p in (_REPO, os.path.join(_REPO, "V0"), _EXTENSION):
    if _p not in sys.path:
        sys.path.insert(0, _p)

#: TODO lo que viaja. Ni el generador, ni el empaquetador, ni la
#: documentación de desarrollo, ni un .vsix anterior, ni __pycache__.
_ESPERADOS = {
    "[Content_Types].xml",
    "extension.vsixmanifest",
    "extension/package.json",
    "extension/language-configuration.json",
    "extension/syntaxes/suriax.tmLanguage.json",
    "extension/snippets/suriax.json",
    "extension/extension.js",
    "extension/rpc.js",
    "extension/lanzar.py",
    "extension/depurar.py",
    "extension/README.md",
    "extension/LICENSE",
}


def _empaqueta(carpeta: str) -> str:
    import empaquetar
    return empaquetar.empaqueta(os.path.join(carpeta, "prueba.vsix"))


def test_el_paquete_lleva_exactamente_la_extension():
    with tempfile.TemporaryDirectory(prefix="suriax-vsix-") as tmp:
        with zipfile.ZipFile(_empaqueta(tmp)) as zf:
            nombres = set(zf.namelist())
            assert nombres == _ESPERADOS, (sorted(nombres - _ESPERADOS),
                                           sorted(_ESPERADOS - nombres))
            # lo de dentro es el archivo del repositorio, byte a byte
            for nombre in nombres:
                if nombre.startswith("extension/"):
                    with open(os.path.join(_EXTENSION, *nombre.split("/")[1:]), "rb") as fh:
                        assert zf.read(nombre) == fh.read(), nombre


def test_el_paquete_tiene_la_forma_de_opc_que_lee_vs_code():
    with tempfile.TemporaryDirectory(prefix="suriax-vsix-") as tmp:
        with zipfile.ZipFile(_empaqueta(tmp)) as zf:
            paquete = json.loads(zf.read("extension/package.json"))
            tipos = ElementTree.fromstring(zf.read("[Content_Types].xml"))
            manifiesto = ElementTree.fromstring(zf.read("extension.vsixmanifest"))
            nombres = zf.namelist()

    ns = "{http://schemas.openxmlformats.org/package/2006/content-types}"
    por_extension = {d.get("Extension") for d in tipos.iter(ns + "Default")}
    sueltos = {o.get("PartName") for o in tipos.iter(ns + "Override")}
    # cada parte del zip tiene su tipo: por su extensión o por su nombre
    for nombre in nombres:
        if nombre == "[Content_Types].xml":
            continue
        extension = os.path.splitext(nombre)[1]
        assert extension in por_extension or "/" + nombre in sueltos, nombre

    vsx = "{http://schemas.microsoft.com/developer/vsx-schema/2011}"
    identidad = manifiesto.find(f"{vsx}Metadata/{vsx}Identity")
    assert identidad.get("Id") == paquete["name"]
    assert identidad.get("Version") == paquete["version"]
    assert identidad.get("Publisher") == paquete["publisher"]
    motor = {p.get("Id"): p.get("Value")
             for p in manifiesto.iter(vsx + "Property")}["Microsoft.VisualStudio.Code.Engine"]
    assert motor == paquete["engines"]["vscode"]
    activos = {a.get("Type"): a.get("Path") for a in manifiesto.iter(vsx + "Asset")}
    assert activos["Microsoft.VisualStudio.Code.Manifest"] == "extension/package.json"
    for ruta in activos.values():
        assert ruta in nombres, ruta


def test_el_paquete_es_reproducible():
    """El mismo árbol da los mismos bytes: dos paquetes se comparan con un
    hash, y un cambio en el .vsix siempre es un cambio en la extensión."""
    with tempfile.TemporaryDirectory(prefix="suriax-vsix-") as tmp:
        import empaquetar
        uno = empaquetar.empaqueta(os.path.join(tmp, "uno.vsix"))
        dos = empaquetar.empaqueta(os.path.join(tmp, "dos.vsix"))
        with open(uno, "rb") as a, open(dos, "rb") as b:
            assert hashlib.sha256(a.read()).digest() == hashlib.sha256(b.read()).digest()


def test_vscodeignore_se_lee_como_lo_lee_vsce():
    """Rutas relativas a la extensión; ``carpeta/`` es todo lo de dentro;
    ``**`` cualquier profundidad; ``!`` vuelve a incluir y gana la última."""
    import empaquetar

    with tempfile.TemporaryDirectory(prefix="suriax-vsix-") as tmp:
        with open(os.path.join(tmp, ".vscodeignore"), "w", encoding="utf-8") as fh:
            fh.write("# comentario\nsolo_raiz.py\ndist/\n**/*.log\n*.md\n!LEEME.md\n")
        reglas = empaquetar.reglas(tmp)

    def fuera(ruta):
        return empaquetar.ignorado(ruta, reglas)

    assert fuera("solo_raiz.py") and not fuera("sub/solo_raiz.py")
    assert fuera("dist/a.vsix") and fuera("dist/x/y.txt") and not fuera("distinto.txt")
    assert fuera("a.log") and fuera("x/y/a.log")
    assert fuera("NOTAS.md") and not fuera("LEEME.md")
    assert not fuera("extension.js")


def test_no_empaqueta_archivos_generados_desfasados():
    """Empaquetar una gramática vieja es repartir un editor que no está de
    acuerdo con el compilador: se niega y dice cómo arreglarlo."""
    import empaquetar
    import generar

    original = generar.desfasados
    generar.desfasados = lambda: ["package.json"]
    try:
        with tempfile.TemporaryDirectory(prefix="suriax-vsix-") as tmp:
            try:
                empaquetar.empaqueta(os.path.join(tmp, "x.vsix"))
            except SystemExit as exc:
                assert "generar.py" in str(exc), exc
                assert not os.path.exists(os.path.join(tmp, "x.vsix"))
            else:
                raise AssertionError("empaquetó archivos desfasados")
    finally:
        generar.desfasados = original

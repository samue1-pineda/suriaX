"""backend/backend_cpp: los bloques #extern cpp.

Parte de ``test_backend_cpp.py`` (partido por tema); lo compartido esta en
``backend_cpp_support.py``.
"""

import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import omitir  # noqa: E402
from backend_cpp_support import (  # noqa: E402
    _COMPILER,
    _REPO_ROOT,
    _cargar,
    _con_referencia,
    _cpp,
)

# --------------------------------------------------------------------------- #
# '#extern cpp': el viaje hasta el lado de C++
# --------------------------------------------------------------------------- #

def _std_cpp() -> str:
    """``-std=c++NN`` con el estándar ÚNICO del proyecto (``version.py``): lo
    que el backend emite se compila como se compilará de verdad, no con el
    estándar por defecto de cada compilador."""
    sys.path.insert(0, _REPO_ROOT)
    from version import CXX_STANDARD
    return f"-std=c++{CXX_STANDARD}"


def _compilador_cpp() -> str | None:
    """Un compilador de C++ del sistema, o ``None``."""
    for nombre in ("c++", "g++", "clang++"):
        ruta = shutil.which(nombre)
        if ruta is not None:
            return ruta
    return None


def test_los_bloques_extern_aterrizan_como_cpp_compilable():
    """El lexer lo captura crudo, la Semántica no lo mira y el HIR lo
    transporta intacto. Aquí se convierte en un archivo que un compilador de
    C++ acepta — que es lo único que demuestra que el viaje sirvió: si nunca
    se compiló el código generado, no se probó."""
    def comprobar(binario, phir, tmp):
        salida = os.path.join(tmp, "extern.cpp")
        resultado = _cpp(binario, phir, "--emit-cpp", salida)
        assert resultado.returncode == 0, resultado.stderr
        assert os.path.isfile(salida), resultado.stderr

        with open(salida, encoding="utf-8") as fh:
            texto = fh.read()
        assert "ayuda_nativa" in texto, texto
        assert "#line" in texto, "sin '#line' los errores no vuelven al .srcx"

        compilador = _compilador_cpp()
        if compilador is None:
            omitir("no hay compilador de C++ para verificar lo emitido")
        compilado = subprocess.run([compilador, _std_cpp(), "-fsyntax-only", salida],
                                   capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=120)
        assert compilado.returncode == 0, (
            "lo que el backend emite no es C++ válido:\n" + compilado.stderr)

    _con_referencia(comprobar)


def test_un_error_en_el_cpp_apunta_al_srcx_del_usuario():
    """La razón de ser del ``#line``: quien escribe ``#extern cpp`` depura su
    propio archivo, no uno generado que nunca vio."""
    compilador = _compilador_cpp()
    if compilador is None:
        omitir("no hay compilador de C++")

    def comprobar(binario, _phir, tmp):
        # un programa aparte, con C++ ROTO a propósito
        fuente = os.path.join(tmp, "roto.srcx")
        with open(fuente, "w", encoding="utf-8") as fh:
            fh.write("fn main() -> int { return 0; }\n"
                     "\n"
                     "#extern cpp{\n"
                     "int roto( { return 1; }\n"
                     "}\n")
        phir = os.path.join(tmp, "roto.phir")
        emit = subprocess.run(
            [sys.executable, _COMPILER, fuente, "--emit-hir", phir],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180, cwd=_REPO_ROOT)
        assert emit.returncode == 0 and os.path.isfile(phir), emit.stderr

        salida = os.path.join(tmp, "roto.cpp")
        assert _cpp(binario, phir, "--emit-cpp", salida).returncode == 0

        compilado = subprocess.run([compilador, _std_cpp(), "-fsyntax-only", salida],
                                   capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=120)
        assert compilado.returncode != 0, "el C++ roto tenía que fallar"
        # el error habla del .srcx y de la línea REAL del bloque (la 4)
        assert "roto.srcx:4" in compilado.stderr, compilado.stderr

    _con_referencia(comprobar)


def test_un_target_desconocido_se_rechaza_con_su_unidad():
    """Solo 'cpp' viaja a este backend. Un target que no conoce se rechaza en
    vez de escribirse en un archivo que luego no compila."""
    from V0.src.HIR.stubs import load_hir_pb2

    def comprobar(binario, phir, tmp):
        pb = load_hir_pb2()
        module = _cargar(phir)
        decl = module.items.add()
        decl.ln, decl.col = 1, 1
        decl.extern_block.target = "rust"
        decl.extern_block.raw = "fn nada() {}"
        raro = os.path.join(tmp, "raro.phir")
        with open(raro, "wb") as fh:
            fh.write(module.SerializeToString(deterministic=True))

        resultado = _cpp(binario, raro, "--emit-cpp",
                         os.path.join(tmp, "raro.cpp"))
        assert resultado.returncode != 0, "un target desconocido no debe pasar"
        assert "rust" in resultado.stderr, resultado.stderr

    _con_referencia(comprobar)

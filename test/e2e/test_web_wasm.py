"""e2e/web_wasm — prueba DIFERENCIAL: intérprete vs target web.

El mismo `.srcx`, el mismo `.phir`, dos ejecutores distintos:

    python V0/main.py prog.srcx --run     -> intérprete (tree-walk, Python)
    node   web/main.ts prog.phir --run    -> WebAssembly generado por el web

Si los dos no dan la MISMA salida y el MISMO valor de retorno, uno de los dos
está mal — y esa es exactamente la garantía que hace útil tener dos backends.
Es el mismo criterio que ya aplica ``test_native_memory.py`` entre el backend
de memoria en C++ y el de Python puro.

Además compara el tercer ejecutor, el backend de JS puro (``--run-js``), que
sale del MISMO WIR que el WebAssembly: si difieren, el fallo está en un emisor
y no en el lowering.

Se salta (con aviso) si falta node o protobuf: el compilador no depende del
target web y su CI no puede quedar roja por eso.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_WEB_MAIN = os.path.join(_REPO_ROOT, "web", "main.ts")
_COMPILER = os.path.join(_REPO_ROOT, "V0", "main.py")

_MIN_NODE_MAJOR = 22
_STRIP_TYPES_BY_DEFAULT = 23

#: Programas dentro del subconjunto que el codegen v1 traduce. El valor de
#: retorno se mantiene pequeño a propósito: el intérprete lo entrega como
#: código de salida del proceso, y un código de salida son 8 bits.
PROGRAMAS = {
    "aritmetica": """
fn suma(int a, int b) -> int {
    return a + b;
}

fn doble(int x) -> int {
    return suma(x, x);
}

fn main() -> int {
    var int a = 20;
    var int b = 22;
    var int total = suma(a, b);
    total = total + doble(1);
    var int cociente = total / 4;
    return cociente;
}
""",
    "impresion": """
#from io #import stdp

fn main() -> int {
    stdp.println("una linea");
    stdp.print("sin salto");
    stdp.println("");
    return 7;
}
""",
    "modulo_y_llamadas": """
#from io #import stdp

fn triple(int x) -> int {
    return x + x + x;
}

fn main() -> int {
    stdp.println("empieza");
    var int valor = triple(4);
    stdp.println("termina");
    return valor - 2;
}
""",
    "condicionales": """
#from io #import stdp

fn clasificar(int n) -> int {
    if (n < 0) {
        return 1;
    } else if (n == 0) {
        return 2;
    } else {
        return 3;
    }
}

fn main() -> int {
    if (clasificar(-4) == 1) {
        stdp.println("negativo");
    }
    if (clasificar(0) == 2) {
        stdp.println("cero");
    }
    return clasificar(9) + clasificar(-1);
}
""",
    "bucles": """
#from io #import stdp

fn suma_hasta(int n) -> int {
    var int total = 0;
    var int i = 1;
    while (i <= n) {
        total = total + i;
        i = i + 1;
    }
    return total;
}

fn impares_hasta(int tope) -> int {
    var int total = 0;
    var int i = 0;
    while (true) {
        i = i + 1;
        if (i > tope) {
            break;
        }
        var int resto = i - (i / 2) * 2;
        if (resto == 0) {
            continue;
        }
        total = total + i;
    }
    return total;
}

fn main() -> int {
    stdp.println("sumando");
    return suma_hasta(10) + impares_hasta(6);
}
""",
    "cortocircuito": """
#from io #import stdp

fn en_rango(int x) -> bool {
    return x > 3 and x < 10;
}

fn fuera(int x) -> bool {
    return x < 0 or x > 100;
}

fn main() -> int {
    var int total = 0;
    if (en_rango(5)) {
        total = total + 1;
        stdp.println("dentro");
    }
    if (fuera(200)) {
        total = total + 2;
        stdp.println("fuera");
    }
    if (not en_rango(50)) {
        total = total + 4;
    }
    return total;
}
""",
}


def _node_major() -> int | None:
    node = shutil.which("node")
    if node is None:
        return None
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True,
                             timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return int(out.stdout.strip().lstrip("v").split(".", 1)[0])
    except ValueError:
        return None


def _skip(reason: str) -> None:
    print(f"      (omitido: {reason})", file=sys.stderr)


def _node_cmd(major: int, *args: str) -> list[str]:
    cmd = ["node"]
    if major < _STRIP_TYPES_BY_DEFAULT:
        cmd.append("--experimental-strip-types")
    return [*cmd, _WEB_MAIN, *args]


#: Líneas que imprime el propio compilador antes de ejecutar: no son del
#: programa y se descartan para poder comparar salidas.
_RUIDO = re.compile(
    r"^(frontend OK:|HIR \(|  unidad '|\(diagnosticos|reporte de|tokens volcados)")


def _salida_del_programa(stdout: str) -> str:
    return "".join(
        line for line in stdout.splitlines(keepends=True) if not _RUIDO.match(line)
    )


def _ejecutar_interprete(source_path: str) -> tuple[str, int]:
    """Compila y ejecuta con el intérprete. Devuelve (salida, retorno)."""
    result = subprocess.run(
        [sys.executable, _COMPILER, source_path, "--run"],
        capture_output=True, text=True, timeout=180, cwd=_REPO_ROOT,
    )
    return _salida_del_programa(result.stdout), result.returncode


def _ejecutar_web(major: int, phir_path: str, *, backend: str) -> tuple[str, int]:
    """Ejecuta el `.phir` con el target web. Devuelve (salida, retorno).

    El CLI del web respeta el mismo contrato que el intérprete: por stdout
    sale SOLO lo que el programa imprime y el valor de ``main`` es el código
    de salida. Por eso aquí no hay que limpiar nada.
    """
    flag = "--run" if backend == "wasm" else "--run-js"
    result = subprocess.run(
        _node_cmd(major, phir_path, flag),
        capture_output=True, text=True, timeout=180, cwd=_REPO_ROOT,
    )
    # Por stderr solo debería salir la marca '[wasm] main() -> N'. Cualquier
    # otra cosa es un fallo del ejecutor que NO puede confundirse con "el
    # programa no imprimió nada" (fue justo el bug que esta prueba encontró).
    ruido = [
        line for line in result.stderr.splitlines()
        if line.strip() and not line.startswith(("[wasm] main()", "[js] main()"))
    ]
    assert not ruido, (
        f"el target web no ejecutó el programa:\n" + "\n".join(ruido))
    return result.stdout, result.returncode


def _para_cada_programa(comprobar) -> None:
    major = _node_major()
    if major is None or major < _MIN_NODE_MAJOR:
        _skip("node no disponible; no se puede ejecutar el target web")
        return
    # El .srcx tiene que estar donde el linker encuentre ./lib (la raíz del
    # repo), igual que cualquier fuente del proyecto.
    for nombre, fuente in PROGRAMAS.items():
        # El prefijo no es cosmetico: el directorio se crea EN LA RAIZ del
        # repo (el linker resuelve './lib' desde ahi), asi que una corrida
        # interrumpida deja un resto visible en 'git status'. Con nombre
        # propio el .gitignore lo reconoce sin tapar nada mas.
        with tempfile.TemporaryDirectory(dir=_REPO_ROOT,
                                         prefix="suriax-web-") as tmp:
            os.symlink(os.path.join(_REPO_ROOT, "lib"), os.path.join(tmp, "lib"))
            # El temporal esta DENTRO del repo, asi que la busqueda de
            # configuracion subiria hasta el '.suriaX_config.yaml' del
            # desarrollador. Uno con 'target: interp' hace que '--emit-hir'
            # ademas EJECUTE, y el proceso termina con el codigo que devuelve
            # main() -- 11 para 'aritmetica' --, que aqui se leia como "no
            # compilo". La prueba declara su entorno en vez de heredarlo: el
            # buscador para en este archivo y no llega al de arriba.
            with open(os.path.join(tmp, ".suriaX_config.yaml"), "w",
                      encoding="utf-8") as fh:
                fh.write("version: 1\ntarget: native\n")
            src = os.path.join(tmp, f"{nombre}.srcx")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write(fuente)
            phir = os.path.join(tmp, f"{nombre}.phir")
            emit = subprocess.run(
                [sys.executable, _COMPILER, src, "--emit-hir", phir],
                capture_output=True, text=True, timeout=180, cwd=_REPO_ROOT,
            )
            if emit.returncode != 0 or not os.path.isfile(phir):
                if "protobuf" in (emit.stdout + emit.stderr).lower():
                    _skip("protobuf no disponible para emitir el HIR")
                    return
                raise AssertionError(
                    f"'{nombre}' no compiló:\n{emit.stdout}\n{emit.stderr}")

            # Las unidades .libsrx se emiten al directorio de dumps del
            # proyecto; el lector las resuelve RELATIVAS al .phir principal,
            # así que tienen que viajar a su lado (igual que al distribuir).
            dumps = os.path.join(_REPO_ROOT, "dumps")
            if os.path.isdir(dumps):
                for archivo in os.listdir(dumps):
                    if archivo.endswith(".phir") and not archivo.startswith("__"):
                        shutil.copy(os.path.join(dumps, archivo),
                                    os.path.join(tmp, archivo))
            comprobar(major, nombre, src, phir)


def test_el_wasm_da_la_misma_salida_que_el_interprete():
    """La garantía central: dos ejecutores, un solo comportamiento."""
    def comprobar(major, nombre, src, phir):
        esperada, retorno = _ejecutar_interprete(src)
        obtenida, valor = _ejecutar_web(major, phir, backend="wasm")
        assert obtenida == esperada, (
            f"'{nombre}': el WebAssembly imprime distinto que el intérprete\n"
            f"  intérprete: {esperada!r}\n  wasm      : {obtenida!r}")
        assert valor == retorno, (
            f"'{nombre}': main() devuelve {valor} en wasm y {retorno} en el intérprete")

    _para_cada_programa(comprobar)


def test_los_dos_backends_del_web_coinciden():
    """WASM y JS salen del mismo WIR: tienen que ser indistinguibles."""
    def comprobar(major, nombre, src, phir):
        por_wasm = _ejecutar_web(major, phir, backend="wasm")
        por_js = _ejecutar_web(major, phir, backend="js")
        assert por_wasm == por_js, (
            f"'{nombre}': los backends del target web difieren\n"
            f"  wasm: {por_wasm!r}\n  js  : {por_js!r}")

    _para_cada_programa(comprobar)

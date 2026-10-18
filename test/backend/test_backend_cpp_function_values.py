"""backend/backend_cpp: funciones como valores (``TypeKind.FUNCTION_TYPE`` = 13).

Hoy solo las ejecuta el intérprete. La VM las RECHAZA con ``VM001`` y un
mensaje estable —decisión del mantenedor: rechazar de forma explícita, no
implementarlas todavía—, y las VISTAS (``--pretty``, ``--summary``) las
siguen leyendo, byte-idénticas a las de Python, que es lo que exige el
diferencial entre consumidores.

El rechazo es del lowering a MIR, función por función, y no de la carga: en
el PROGRAMA, una función que recibe, devuelve o usa un valor función es una
construcción que el MIR no cubre (``--check-mir`` falla y ``suri --run
compiler`` lo ejecuta en el intérprete); en una LIBRERÍA se baja a un cuerpo
que falla con ``VM001`` si alguien la llama. Rechazar al cargar dejaba fuera
de la VM a todo programa con un ``Vector``: ``array.vector`` declara
``sort_by(fn(T ptr, T ptr) -> int cmp)``.

También vive aquí la colisión "un método de ``@impl`` con nombre llano pisa a
una ``fn`` homónima del módulo": en la VM dependía del ORDEN de declaración
(``emplace`` se queda con la primera), así que se prueban los dos órdenes.

Lo compartido está en ``backend_cpp_support.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend_cpp_support import (  # noqa: E402
    _cargar,
    _codigo_de_proceso,
    _con_programa,
    _cpp,
    _en_el_path,
    _vm,
)

_FUNCTION_VALUES = """\
fn doble(int x) -> int { return x * 2; }

fn aplica(fn(int) -> int f, int v) -> int { return f(v); }

fn main() -> int {
    var fn(int) -> int g = doble;
    var (fn(int) -> int)? h = null;
    return aplica(g, 20) + 2;
}
"""

_VM001_TAIL = (
    " usa funciones como valores (el tipo 'fn(int) -> int'): la VM todavia no "
    "las ejecuta. Ejecutalo con el interprete: python V0/main.py <fuente>.srcx "
    "--run interpreter")


def _vm001(phir: str) -> str:
    """El mensaje EXACTO de VM001 para ``phir`` (sin la posición): nombra el
    fuente que dice la unidad (``Module.source_file``)."""
    return f"VM001: '{_cargar(phir).source_file}'" + _VM001_TAIL


def test_la_vm_rechaza_funciones_como_valores_con_vm001():
    """``--check-mir`` (el que consulta ``suri --run compiler`` antes de
    elegir motor) y ``--run`` fallan nombrando cada función que las usa, con
    su posición; ninguno ejecuta nada."""
    def comprobar(binario, phir, corrida):
        # el intérprete sí lo ejecuta: el rechazo es de la VM, no del programa
        assert corrida.returncode == _codigo_de_proceso(42), (
            corrida.stdout, corrida.stderr)
        mensaje = _vm001(phir)
        comprobado = _cpp(binario, phir, "--check-mir")
        assert comprobado.returncode == 1, (comprobado.stdout, comprobado.stderr)
        # 'aplica' (su parámetro) en 3:1 y 'main' (sus variables) en 5:1
        assert comprobado.stderr == f"3:1  {mensaje}\n5:1  {mensaje}\n", comprobado.stderr
        corrido = _cpp(binario, phir, "--run")
        assert corrido.returncode == 1, (corrido.stdout, corrido.stderr)
        assert corrido.stdout == "", corrido.stdout
        assert corrido.stderr == (
            f"\nel MIR no cubre 2 construccion(es):\n  3:1  {mensaje}\n"
            f"  5:1  {mensaje}\n"), corrido.stderr
        # '--resolve' no inventa un destino para 'f(v)': lo dice
        resuelto = _cpp(binario, phir, "--resolve")
        assert resuelto.returncode == 1, resuelto.stderr
        assert "llama f -> SIN RESOLVER" in resuelto.stdout, resuelto.stdout
    _con_programa(_FUNCTION_VALUES, comprobar)


def test_las_vistas_leen_funciones_como_valores_igual_que_python():
    """Rechazar la ejecución no es dejar de LEER: ``--pretty`` y
    ``--summary`` escriben ``fn(A) -> R`` (y ``(fn…)?`` dentro de un
    nullable) exactamente como ``pretty.format_type``."""
    def comprobar(binario, phir, _corrida):
        _en_el_path()
        from src.HIR.pretty import pretty
        from runtime.interpreter.loader import summarize
        modulo = _cargar(phir)
        vista = _cpp(binario, phir, "--pretty")
        assert vista.returncode == 0, vista.stderr
        assert vista.stdout == pretty(modulo), (
            f"--- Python ---\n{pretty(modulo)}\n--- C++ ---\n{vista.stdout}")
        # que la prueba mire de verdad las tres formas de escribirlo
        assert "  #2   fn(int) -> int\n" in vista.stdout, vista.stdout
        assert "  #3   (fn(int) -> int)?\n" in vista.stdout, vista.stdout
        assert "f:(fn(int) -> int)(v:int)" in vista.stdout, vista.stdout
        resumen = _cpp(binario, phir, "--summary")
        assert resumen.returncode == 0, resumen.stderr
        assert resumen.stdout == summarize(modulo) + "\n", resumen.stdout
        verificado = _cpp(binario, phir, "--verify")
        assert verificado.returncode == 0, verificado.stderr
    _con_programa(_FUNCTION_VALUES, comprobar)


def test_un_programa_sin_funciones_como_valores_sigue_corriendo():
    """Un programa que solo LLAMA a funciones no tiene ningún tipo función
    y corre como siempre."""
    fuente = ("fn doble(int x) -> int { return x * 2; }\n"
              "fn main() -> int { return doble(21); }\n")

    def comprobar(binario, phir, _corrida):
        assert _vm(binario, phir) == 42
        assert _cpp(binario, phir, "--check-mir").returncode == 0
    _con_programa(fuente, comprobar)


def test_vm001_tambien_ve_la_funcion_anidada_en_un_nullable():
    """Un programa cuyo ÚNICO tipo función va dentro de un ``?``: la
    comprobación recorre ``inner`` y ``args``, no solo el kind de arriba."""
    fuente = ("fn main() -> int {\n"
              "    var (fn(int) -> int)? h = null;\n"
              "    return 0;\n"
              "}\n")

    def comprobar(binario, phir, _corrida):
        _en_el_path()
        tipos = [t.kind for t in _cargar(phir).types]
        assert 13 not in tipos, f"la prueba necesita la función SOLO anidada: {tipos}"
        obtenido = _cpp(binario, phir, "--check-mir")
        assert obtenido.returncode == 1, (obtenido.stdout, obtenido.stderr)
        assert obtenido.stderr == f"1:1  {_vm001(phir)}\n", obtenido.stderr
    _con_programa(fuente, comprobar)


_VECTOR = """\
#from io #import stdp
#import array.vector as vec

fn compara(int ptr a, int ptr b) -> int { return b[0] - a[0]; }

fn main() -> int {
    var vec.Vector<int> v = vec.dynamic<int>(4);
    v.push(3);
    v.push(1);
    v.push(2);
ORDENAR    stdp.println(f"{v.len()} {v[0]}");
    return v[0];
}
"""


def _vector_declara_funciones(phir: str) -> None:
    """La premisa de las dos pruebas de ``Vector``: la unidad de
    ``array.vector`` ligada junto a ``phir`` tiene algún tipo función. Si la
    librería deja de declararlas, las pruebas ya no miden nada y se omiten
    diciéndolo (``helpers.omitir``)."""
    from helpers import omitir
    carpeta = os.path.dirname(phir)
    for nombre in os.listdir(carpeta):
        if nombre.startswith("array.vector") and nombre.endswith(".phir"):
            if any(t.kind == 13 for t in _cargar(os.path.join(carpeta, nombre)).types):
                return
            omitir("lib/array/vector.libsrx ya no declara funciones como valores "
                   "(sort_by/filter): esta prueba no mide nada")
    raise AssertionError(f"no está la unidad de array.vector: {os.listdir(carpeta)}")


def test_un_programa_con_vector_corre_aunque_la_libreria_declare_funciones():
    """``array.vector`` declara ``sort_by``/``filter`` con un parámetro
    función. Un programa que usa un ``Vector`` sin llamarlas corre en la VM
    igual que en el intérprete: la librería no se rechaza por declararlas."""
    def comprobar(binario, phir, corrida):
        _vector_declara_funciones(phir)
        obtenido = _cpp(binario, phir, "--run", "--quiet")
        assert obtenido.returncode == corrida.returncode == _codigo_de_proceso(3), (
            obtenido.stdout, obtenido.stderr, corrida.returncode)
        assert obtenido.stdout == "3 3\n", obtenido.stdout
        assert _cpp(binario, phir, "--check-mir").returncode == 0
    _con_programa(_VECTOR.replace("ORDENAR", ""), comprobar)


def test_llamar_a_sort_by_con_una_funcion_es_vm001_en_la_linea_del_programa():
    """Quien LLAMA a ``v.sort_by(compara)`` le pasa un valor función: el
    rechazo apunta a esa línea del programa (11:15, el argumento), no al
    cuerpo de la librería."""
    def comprobar(binario, phir, corrida):
        _vector_declara_funciones(phir)
        # el intérprete lo ordena de mayor a menor: v[0] == 3
        assert corrida.returncode == _codigo_de_proceso(3), (corrida.stdout, corrida.stderr)
        obtenido = _cpp(binario, phir, "--check-mir")
        assert obtenido.returncode == 1, (obtenido.stdout, obtenido.stderr)
        mensaje = _vm001(phir).replace("'fn(int) -> int'", "'fn(int ptr, int ptr) -> int'")
        assert obtenido.stderr == f"11:15  {mensaje}\n", obtenido.stderr
    _con_programa(_VECTOR.replace("ORDENAR", "    v.sort_by(compara);\n"), comprobar)


_FN = "fn distancia(int x) -> int { return x + 100; }\n"
_METHOD = ("struct { int x; } Punto;\n"
           "@impl Punto {\n"
           "    fn distancia(Punto ptr self) -> int { return self.x; }\n"
           "}\n")
_MAIN = ("fn main() -> int {\n"
         "    var Punto p = Punto{ x: 7 };\n"
         "    return distancia(5) + p.distancia();\n"
         "}\n")


def test_un_metodo_homonimo_no_pisa_a_la_funcion_del_modulo():
    """``distancia(5)`` es la función (105) y ``p.distancia()`` el método
    (7), declare quien declare primero. Antes, con el método primero, la VM
    llamaba al método con 5 como receptor: error de ejecución."""
    for orden, fuente in (("fn primero", _FN + _METHOD + _MAIN),
                          ("metodo primero", _METHOD + _FN + _MAIN)):
        def comprobar(binario, phir, corrida, orden=orden):
            assert corrida.returncode == _codigo_de_proceso(112), (
                orden, corrida.stdout, corrida.stderr)
            obtenido = _cpp(binario, phir, "--run")
            assert obtenido.returncode == _codigo_de_proceso(112), (
                orden, obtenido.stdout, obtenido.stderr)
            assert "[vm] main() -> 112" in obtenido.stdout, (orden, obtenido.stdout)
        _con_programa(fuente, comprobar)

"""backend/backend_cpp: el MIR y la VM contra el interprete (aritmetica y control).

Parte de ``test_backend_cpp.py`` (partido por tema); lo compartido esta en
``backend_cpp_support.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend_cpp_support import (  # noqa: E402
    _codigo_de_proceso,
    _con_programa,
    _cpp,
    _vm,
)

# --------------------------------------------------------------------------- #
# MIR + VM: el backend nativo empieza a EJECUTAR
# --------------------------------------------------------------------------- #
# '--resolve' demuestra que el backend entiende el HIR; esto demuestra que
# puede correrlo. La prueba no es que la VM devuelva "algo": es que devuelva
# LO MISMO que el intérprete, porque dos ejecutores que discrepan son dos
# lenguajes. Es el mismo diferencial que ya protege la vista legible.

_ARITMETICA = """\
fn abs(int x) -> int { if (x < 0) { return -x; }; return x; };

fn suma_hasta(int n) -> int {
    var int total = 0;
    var int i = 1;
    while (i <= n) { total = total + i; i = i + 1; };
    return total;
};

fn fib(int n) -> int {
    if (n < 2) { return n; };
    return fib(n - 1) + fib(n - 2);
};

fn en_rango(int x) -> bool { return x > 3 and x < 10; };

fn main() -> int {
    var int r = 0;
    if (en_rango(abs(-5))) { r = 1; };
    return abs(-5) + suma_hasta(10) + fib(15) + r;
};
"""


def test_la_vm_devuelve_lo_mismo_que_el_interprete():
    """El diferencial: aritmética, control de flujo, recursión y
    cortocircuito, ejecutados por los dos."""
    def comprobar(binario, phir, corrida):
        obtenido = _vm(binario, phir)
        assert obtenido is not None, "la VM no ejecutó"
        assert obtenido == 671, obtenido      # 5 + 55 + 610 + 1
        # el proceso del intérprete devuelve 8 bits en POSIX y 32 en Windows
        assert corrida.returncode == _codigo_de_proceso(obtenido), (
            f"la VM dio {obtenido} y el intérprete salió con "
            f"{corrida.returncode}")
    _con_programa(_ARITMETICA, comprobar)


def test_el_cortocircuito_es_un_grafo_y_no_una_instruccion():
    """'a and b' no evalúa 'b' si no hace falta, y en el MIR eso se ve: hay
    una rama y dos caminos que se juntan. Es la razón de que el CFG sea
    explícito (ROADMAP Fase 6)."""
    def comprobar(binario, phir, _corrida):
        salida = _cpp(binario, phir, "--mir").stdout
        assert "branch" in salida, salida
        # el lado derecho vive en su propio bloque: si se evaluara siempre,
        # estaría en el mismo que la condición
        assert salida.count("bb") > 4, salida
    _con_programa(_ARITMETICA, comprobar)


def test_la_division_entera_trunca_igual_en_la_vm():
    """La semántica no puede diferir entre ejecutores: '-7 / 2' es -3 en los
    dos, y '(a/b)*b + a%b == a' se cumple en los dos."""
    def comprobar(binario, phir, corrida):
        obtenido = _vm(binario, phir)
        assert obtenido == 0, obtenido
        assert corrida.returncode == 0
    _con_programa("""\
fn main() -> int {
    var int fallos = 0;
    if (-7 / 2 != -3) { fallos = fallos + 1; };
    if (7 / -2 != -3) { fallos = fallos + 1; };
    if (-7 % 2 != -1) { fallos = fallos + 1; };
    if (-7 / 2 * 2 + -7 % 2 != -7) { fallos = fallos + 1; };
    return fallos;
};
""", comprobar)


def test_los_enteros_envuelven_a_64_bits_en_la_vm():
    """El 'int' del lenguaje es de 64 bits y envuelve. En C++ el
    desbordamiento con signo es comportamiento indefinido, así que la VM hace
    la cuenta en el tipo sin signo: sin eso el compilador podría optimizar
    asumiendo que no desborda y el resultado dejaría de coincidir."""
    def comprobar(binario, phir, corrida):
        assert _vm(binario, phir) == 0
        assert corrida.returncode == 0
    _con_programa("""\
fn main() -> int {
    var int max = 9223372036854775807;
    var int min = -9223372036854775808;
    var int fallos = 0;
    if (max + 1 != min) { fallos = fallos + 1; };
    if (min - 1 != max) { fallos = fallos + 1; };
    return fallos;
};
""", comprobar)


def test_lo_que_ningun_motor_ejecuta_falla_igual_en_la_VM():
    """El MIR baja todo lo que el intérprete ejecuta. Lo que el intérprete
    rechaza AL EJECUTAR (RT011: ``&`` sobre un elemento, ``&xs[0]``, que
    necesitaría un puntero interior) la VM lo rechaza igual, con el mismo
    código y en el mismo momento, en vez de negarse a compilar el programa.

    Si algún día el MIR vuelve a tener una construcción que no sabe bajar,
    esta prueba tiene que apuntarle (la VM la nombra con su posición y dice
    "el MIR no cubre"): mientras quede algo sin cubrir, tiene que doler."""
    def comprobar(binario, phir, _corrida):
        resultado = _cpp(binario, phir, "--run")
        assert resultado.returncode == 70, resultado.stderr
        assert "no cubre" not in resultado.stderr, resultado.stderr
        assert "RT011" in resultado.stderr, resultado.stderr
    _con_programa("""#import mem
fn usa(int ptr p) -> void { };
fn main() -> int { var int ptr mutable xs = mem.reserve<int>(2); usa(&xs[0]); return 0; };
""", comprobar)


# --------------------------------------------------------------------------- #
# los límites de --run: pasos y memoria del programa
# --------------------------------------------------------------------------- #

_CADENAS = """#import mem
fn main() -> int {
    var int i = 0;
    var str s = "";
    while (i < 2000) {
        s = s + "abcdefghij";
        i = i + 1;
    };
    var int ptr mutable b = mem.reserve<int>(1000);
    mem.release<int>(b);
    return len(s) / 1000;
};
"""


def test_los_pasos_se_limitan_y_cero_es_sin_limite():
    """'--pasos N' es el límite de la VM (RT010 con la posición); '0' lo
    quita. Es lo que hace falta para que la V1 se compile a sí misma, que
    pasa del límite por defecto."""
    def comprobar(binario, phir, _corrida):
        corto = _cpp(binario, phir, "--run", "--quiet", "--pasos", "500")
        assert corto.returncode == 70, corto.stderr
        assert "RT010" in corto.stderr and "(500)" in corto.stderr, corto.stderr
        libre = _cpp(binario, phir, "--run", "--quiet", "--pasos", "0")
        assert libre.returncode == _codigo_de_proceso(20), libre.stderr
    _con_programa(_CADENAS, comprobar)


def test_la_memoria_del_programa_se_limita():
    """'--memoria-max' corta con RT023 y la posición cuando el PROGRAMA pasa
    del tamaño, y antes RECOGE las cadenas que ya nadie usa: con 64K el
    programa termina (su cadena viva es de 20 KB, aunque haya creado unos 20
    MB de cadenas intermedias); con 20K no cabe ni la cadena viva."""
    def comprobar(binario, phir, _corrida):
        holgado = _cpp(binario, phir, "--run", "--quiet", "--memoria-max", "64K")
        assert holgado.returncode == _codigo_de_proceso(20), holgado.stderr
        justo = _cpp(binario, phir, "--run", "--quiet", "--memoria-max", "20K")
        assert justo.returncode == 70, justo.stderr
        assert "RT023" in justo.stderr and "(20480 bytes)" in justo.stderr, justo.stderr
        assert "(6:" in justo.stderr, justo.stderr   # la concatenación
        # el pico que reporta '--memoria' es el de lo que la VM retuvo de
        # verdad (las intermedias incluidas, antes de barrerse)
        informe = _cpp(binario, phir, "--run", "--memoria")
        assert "bytes del programa: pico" in informe.stderr, informe.stderr
        assert "vivos al terminar 0" in informe.stderr, informe.stderr
    _con_programa(_CADENAS, comprobar)


def test_un_limite_mal_escrito_es_un_error_de_uso():
    def comprobar(binario, phir, _corrida):
        for opciones in (["--memoria-max", "2X"], ["--pasos", "-3"], ["--pasos"]):
            r = _cpp(binario, phir, "--run", *opciones)
            assert r.returncode == 2, (opciones, r.stderr)
            assert opciones[0] in r.stderr, (opciones, r.stderr)
    _con_programa("fn main() -> int { return 0; };\n", comprobar)

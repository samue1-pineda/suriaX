"""e2e/llamadas_al_host — lo que el nicho necesitaba pedirle a la máquina.

suriaX apunta a herramientas de línea de comandos que analizan código o
texto. Escribiéndolas faltaba: leer la entrada estándar (usarlas en una
tubería), borrar y renombrar archivos y saber cuándo cambiaron (un build,
un almacén que se compacta), lanzar otro programa (un script de build) y el
reloj. Aquí se prueban en el intérprete, que es el motor de referencia; la
VM y el target web todavía no las tienen (ver ``lib/LLAMADAS_AL_HOST.md``).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_ENV = {**os.environ, "PYTHONUTF8": "1"}


def _corre(fuente: str, *, entrada: bytes = b"", carpeta: str | None = None):
    """Compila y ejecuta ``fuente`` en el intérprete con ``entrada`` por su
    entrada estándar. Devuelve ``(código, salida, errores)``."""
    def en(tmp):
        ruta = os.path.join(tmp, "prog.srcx")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(fuente)
        hecho = subprocess.run(
            [sys.executable, os.path.join(_REPO, "V0", "main.py"), ruta,
             "--run", "interpreter"],
            cwd=tmp, input=entrada, capture_output=True, env=_ENV, timeout=300)
        salida = hecho.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        # lo que imprime el compilador antes del programa no es del programa
        salida = "\n".join(l for l in salida.split("\n")
                           if not l.startswith(("HIR (", "frontend OK", "  unidad ")))
        return hecho.returncode, salida, hecho.stderr.decode("utf-8", "replace")

    if carpeta is not None:
        return en(carpeta)
    with tempfile.TemporaryDirectory(prefix="suriax-host-") as tmp:
        return en(tmp)


# --------------------------------------------------------------------------- #
# sistema.entrada
# --------------------------------------------------------------------------- #

_LINEAS = """\
#from io #import stdp
#import sistema.entrada as entrada
fn main() -> int {
    var int n = 0;
    while (not entrada.terminada()) {
        stdp.println(f"[{entrada.linea()}]");
        n = n + 1;
    };
    return n;
}
"""


def test_la_entrada_se_lee_linea_a_linea_sin_sus_fines():
    """'\\r\\n' y '\\n' no son parte de la línea, y la última cuenta aunque
    no termine en salto: es como llega un archivo por una tubería."""
    codigo, salida, error = _corre(_LINEAS, entrada="uno\r\ndos\n\ntrés".encode())
    assert codigo == 4, error[-400:]
    assert salida.strip().split("\n") == ["[uno]", "[dos]", "[]", "[trés]"], salida


def test_una_entrada_vacia_no_tiene_lineas():
    codigo, salida, _ = _corre(_LINEAS, entrada=b"")
    assert codigo == 0 and "[" not in salida, salida


def test_pedir_una_linea_que_no_hay_es_un_error_del_programa():
    fuente = ("#from io #import stdp\n"
              "#import sistema.entrada as entrada\n"
              "#import excepciones as exc\n"
              "fn main() -> int {\n"
              "    var str a = entrada.linea();\n"
              "    try { var str b = entrada.linea(); }\n"
              "    catch (exc.ErrorDeArchivo e) { stdp.println(e.mensaje); return 1; };\n"
              "    return 0;\n"
              "}\n")
    codigo, salida, _ = _corre(fuente, entrada=b"sola\n")
    assert codigo == 1 and "se terminó" in salida, salida


def test_todo_devuelve_lo_que_queda_tal_cual():
    fuente = ("#from io #import stdp\n"
              "#import sistema.entrada as entrada\n"
              "fn main() -> int {\n"
              "    var str primera = entrada.linea();\n"
              "    var str resto = entrada.todo();\n"
              '    stdp.println(f"{primera}|{len(resto)}|{entrada.terminada()}");\n'
              "    return 0;\n"
              "}\n")
    _, salida, error = _corre(fuente, entrada=b"a\nb\r\nc")
    # 'b\r\nc' son 4 caracteres: los fines de línea se conservan
    assert salida.strip() == "a|4|true", (salida, error[-300:])


def test_todo_incluye_la_linea_que_terminada_ya_miro():
    """'terminada()' tiene que leer por adelantado para saber si queda algo;
    esa línea no se puede perder."""
    fuente = ("#from io #import stdp\n"
              "#import sistema.entrada as entrada\n"
              "fn main() -> int {\n"
              "    var bool queda = not entrada.terminada();\n"
              '    stdp.println(f"{queda}|{entrada.todo()}");\n'
              "    return 0;\n"
              "}\n")
    _, salida, error = _corre(fuente, entrada=b"uno")
    assert salida.strip() == "true|uno", (salida, error[-300:])


def test_una_entrada_que_no_es_utf8_es_un_error_del_programa():
    codigo, _, error = _corre(_LINEAS, entrada=b"\xff\xfe\n")
    assert codigo == 70 and "EXC003" in error and "UTF-8" in error, error[-300:]


# --------------------------------------------------------------------------- #
# sistema.archivos: borrar, renombrar, modificado
# --------------------------------------------------------------------------- #

_ARCHIVOS = """\
#from io #import stdp
#import sistema.archivos as arch
#import excepciones as exc
fn main() -> int {
    arch.escribir("viejo.txt", "uno");
    arch.escribir("nuevo.txt", "dos");
    arch.renombrar("viejo.txt", "nuevo.txt");
    stdp.println(f"{arch.existe("viejo.txt")} {arch.leer("nuevo.txt")}");
    arch.crear_carpeta("vacia");
    arch.crear_carpeta("llena");
    arch.escribir("llena/x.txt", "x");
    arch.borrar("nuevo.txt");
    arch.borrar("vacia");
    stdp.println(f"{arch.existe("nuevo.txt")} {arch.existe("vacia")}");
    try { arch.borrar("llena"); } catch (exc.ErrorDeArchivo e) { stdp.println(e.mensaje); };
    try { arch.borrar("no_esta.txt"); } catch (exc.ErrorDeArchivo e) { stdp.println(e.mensaje); };
    try { arch.renombrar("no_esta.txt", "otro.txt"); } catch (exc.ErrorDeArchivo e) { stdp.println(e.mensaje); };
    stdp.println(f"{arch.modificado("llena/x.txt")}");
    try { var int f = arch.modificado("no_esta.txt"); } catch (exc.ErrorDeArchivo e) { stdp.println(e.mensaje); };
    return 0;
}
"""


def test_borrar_renombrar_y_la_fecha_de_un_archivo():
    with tempfile.TemporaryDirectory(prefix="suriax-host-") as tmp:
        antes = time.time()
        codigo, salida, error = _corre(_ARCHIVOS, carpeta=tmp)
        despues = time.time()
        assert codigo == 0, error[-400:]
        lineas = salida.strip().split("\n")
        # renombrar REEMPLAZA un destino que existe
        assert lineas[0] == "false uno", lineas
        assert lineas[1] == "false false", lineas
        # una carpeta con cosas dentro no se borra; lo que no existe, tampoco
        assert "la carpeta no está vacía" in lineas[2], lineas
        assert lineas[3] == "no existe 'no_esta.txt'", lineas
        assert lineas[4] == "no existe 'no_esta.txt'", lineas
        assert lineas[6] == "no existe 'no_esta.txt'", lineas
        assert os.path.isfile(os.path.join(tmp, "llena", "x.txt"))
        # milisegundos desde 1970, los del sistema de archivos
        fecha = int(lineas[5]) / 1000
        assert antes - 5 <= fecha <= despues + 5, (fecha, antes, despues)
        real = os.stat(os.path.join(tmp, "llena", "x.txt")).st_mtime_ns // 1_000_000
        assert int(lineas[5]) == real


# --------------------------------------------------------------------------- #
# sistema.comandos
# --------------------------------------------------------------------------- #

def _orden(*partes: str) -> str:
    """El código suriaX que arma un 'Vector<str>' con ``partes``."""
    lineas = [f"    var vec.Vector<str> orden = vec.dynamic<str>({len(partes) + 1});"]
    for parte in partes:
        escapada = parte.replace("\\", "\\\\").replace('"', '\\"')
        lineas.append(f'    orden.push("{escapada}");')
    return "\n".join(lineas) + "\n"


_CABECERA = ("#from io #import stdp\n"
             "#import array.vector as vec\n"
             "#import sistema.comandos as cmd\n"
             "#import excepciones as exc\n")


def test_un_programa_lanzado_devuelve_su_codigo_su_salida_y_sus_errores():
    hijo = ("import sys; d = sys.stdin.read(); sys.stdout.write(d.upper()); "
            "sys.stderr.write('aviso'); sys.exit(3)")
    fuente = (_CABECERA + "fn main() -> int {\n" + _orden(sys.executable, "-c", hijo)
              + '    var cmd.Resultado r = cmd.ejecutar_con_entrada(&orden, "hola ñ");\n'
                '    stdp.println(f"{r.codigo}|{r.salida}|{r.errores}");\n'
                "    return 0;\n}\n")
    codigo, salida, error = _corre(fuente)
    assert codigo == 0, error[-400:]
    # un código distinto de 0 NO es una excepción: es un dato
    assert salida.strip() == "3|HOLA Ñ|aviso", salida


def test_los_argumentos_llegan_tal_cual_sin_interprete_de_ordenes():
    """Un argumento con espacios, comillas o ';' es UN argumento: no hay un
    intérprete de órdenes que lo parta o lo ejecute."""
    hijo = "import sys; print(len(sys.argv) - 1); [print(a) for a in sys.argv[1:]]"
    raros = ["dos palabras", "a;b", 'con "comillas"', "$HOME", "%PATH%"]
    fuente = (_CABECERA + "fn main() -> int {\n" + _orden(sys.executable, "-c", hijo, *raros)
              + "    var cmd.Resultado r = cmd.ejecutar(&orden);\n"
                "    stdp.print(r.salida);\n"
                "    return r.codigo;\n}\n")
    codigo, salida, error = _corre(fuente)
    assert codigo == 0, error[-400:]
    # el hijo escribe sus fines de línea ('\r\n' en Windows) y llegan tal
    # cual, como los de un archivo: se comparan las líneas sin ellos.
    lineas = [l.rstrip("\r") for l in salida.strip().split("\n")]
    assert lineas == [str(len(raros)), *raros], salida


def test_un_programa_que_no_existe_o_una_orden_vacia_son_errores_del_programa():
    fuente = (_CABECERA + "fn main() -> int {\n" + _orden("no_existe_este_programa_xyz")
              + "    try { var cmd.Resultado r = cmd.ejecutar(&orden); }\n"
                "    catch (exc.ErrorDeArchivo e) { stdp.println(e.mensaje); };\n"
                "    var vec.Vector<str> vacia = vec.dynamic<str>(1);\n"
                "    try { var cmd.Resultado r = cmd.ejecutar(&vacia); }\n"
                "    catch (exc.ValorInvalido e) { stdp.println(e.mensaje); };\n"
                "    return 0;\n}\n")
    codigo, salida, error = _corre(fuente)
    assert codigo == 0, error[-400:]
    lineas = salida.strip().split("\n")
    assert lineas[0] == "no existe el programa 'no_existe_este_programa_xyz'", lineas
    assert "la orden está vacía" in lineas[1], lineas


# --------------------------------------------------------------------------- #
# sistema.tiempo
# --------------------------------------------------------------------------- #

def test_la_hora_el_reloj_y_dormir():
    fuente = ("#from io #import stdp\n"
              "#import sistema.tiempo as tiempo\n"
              "#import excepciones as exc\n"
              "fn main() -> int {\n"
              "    var int ahora = tiempo.ahora();\n"
              "    var int inicio = tiempo.reloj();\n"
              "    tiempo.dormir(50);\n"
              "    var int pasado = tiempo.reloj() - inicio;\n"
              '    stdp.println(f"{ahora}|{pasado}");\n'
              "    try { tiempo.dormir(-1); } catch (exc.ValorInvalido e) { stdp.println(e.mensaje); };\n"
              "    return 0;\n"
              "}\n")
    antes = time.time() * 1000
    codigo, salida, error = _corre(fuente)
    despues = time.time() * 1000
    assert codigo == 0, error[-400:]
    medida, mensaje = salida.strip().split("\n")
    ahora, pasado = (int(x) for x in medida.split("|"))
    assert antes - 60_000 <= ahora <= despues, (ahora, antes, despues)
    # nanosegundos: dormir 50 ms son al menos 50 000 000
    assert 50_000_000 <= pasado < 10_000_000_000, pasado
    assert "no va hacia atrás" in mensaje, mensaje

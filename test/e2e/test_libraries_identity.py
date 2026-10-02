"""e2e/libraries: identidad de un tipo, el vector de la stdlib y la busqueda de la stdlib.

Parte de ``test_libraries.py`` (partido por tema); lo compartido esta en
``libraries_support.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import assert_project_output, run_project  # noqa: E402
from libraries_support import (  # noqa: E402
    W,
)

# --------------------------------------------------------------------------- #
# IDENTIDAD de un tipo: (unidad, nombre), no solo nombre
# --------------------------------------------------------------------------- #
# Los tipos siempre estuvieron separados por unidad para el checker, pero sus
# HOOKS, conversiones y dunders se indexaban por el nombre a secas. Con dos
# librerías declarando 'Node', el '__free__' que corría lo decidía el orden de
# carga — en silencio, sin un diagnóstico. Que un lenguaje de PROPIEDAD
# destruya con el destructor equivocado es el peor fallo posible del sistema
# de módulos, y es el que estas pruebas fijan.

#: dos librerías independientes, cada una con SU 'Node' y SU '__len__'.
_HOMONIMOS = {
    "lib/uno.libsrx": (
        "public struct { int x; } Node;\n"
        "public hook fn __len__(Node ptr n) -> int { return 1; }\n"
        "public fn haz() -> Node { return Node{ x: 0 }; }\n"
        "#export as uno\n"
    ),
    "lib/dos.libsrx": (
        "public struct { int y; } Node;\n"
        "public hook fn __len__(Node ptr n) -> int { return 2; }\n"
        "public fn haz() -> Node { return Node{ y: 0 }; }\n"
        "#export as dos\n"
    ),
}


def test_dos_tipos_homonimos_no_comparten_su_hook():
    """El hook que corre es el de la librería del VALOR, no el del que se
    cargara primero. Se comprueban los dos sentidos: una sola dirección
    pasaría por casualidad según el orden de carga."""
    for lib, esperado in (("uno", "1"), ("dos", "2")):
        assert_project_output({
            **_HOMONIMOS,
            "main.srcx": (
                W + "#import uno\n#import dos\n"
                "fn main() -> int {\n"
                f"    var {lib}.Node n = {lib}.haz();\n"
                '    __write__(f"{len(n)}\\n");\n'
                "    return 0;\n};\n"),
        }, esperado + "\n")


def test_dos_tipos_homonimos_no_unifican_entre_si():
    """La otra cara: si compartieran identidad, el checker dejaría pasar el
    valor de una librería donde se espera el de la otra — y ahí ya no hay
    hook que valga, son structs con campos distintos."""
    code, _out, err = run_project({
        **_HOMONIMOS,
        "main.srcx": (
            "#import uno\n#import dos\n"
            "fn main() -> int { var uno.Node n = dos.haz(); return 0; };\n"),
    })
    assert code != 0 and "AST006" in err, err
    # el diagnóstico tiene que nombrar las DOS unidades: 'no puedes poner un
    # Node en un Node' no le sirve a nadie
    assert "uno.Node" in err and "dos.Node" in err, err


def test_un_hook_sobre_un_tipo_de_otra_unidad_se_rechaza():
    """Los hooks de un tipo viven con el tipo.

    No es purismo: la tabla de despacho es una sola, así que dos librerías
    colgándole un ``__free__`` al mismo tipo ajeno dejarían la elección al
    orden de carga. Antes esto no fallaba — el hook se registraba bajo el
    nombre calificado, nadie lo buscaba ahí, y no corría NUNCA."""
    code, _out, err = run_project({
        "lib/a.libsrx": "public struct { int x; } P;\n#export as a\n",
        "lib/b.libsrx": ("#import a\n"
                         "public hook fn __len__(a.P ptr p) -> int { return p.x; }\n"
                         "#export as b\n"),
        "main.srcx": ("#import a\n#import b\n"
                      "fn main() -> int { var a.P p = a.P{ x: 4 }; return len(p); };\n"),
    })
    assert code != 0, (code, err)
    assert "otra unidad" in err, err


def test_un_tipo_responde_a_su_nombre_corto_dentro_de_su_libreria():
    """La identidad es ``a.Node``, pero dentro de ``a`` se sigue escribiendo
    ``Node``: los dos nombres tienen que llevar al mismo tipo. Sin esto, un
    campo tan común como ``self.datos`` dejaba de resolver DENTRO de la
    librería que lo declara."""
    assert_project_output({
        "lib/a.libsrx": (
            "public struct { int x; } Caja;\n"
            "public fn haz(int v) -> Caja { return Caja{ x: v }; }\n"
            "public fn saca(Caja ptr c) -> int { return c.x; }\n"
            "#export as a\n"),
        "main.srcx": (W + "#import a\n"
                      "fn main() -> int {\n"
                      "    var a.Caja c = a.haz(7);\n"
                      '    __write__(f"{a.saca(&c)}\\n");\n'
                      "    return 0;\n};\n"),
    }, "7\n")


def _con_la_lib_real(programa: str):
    """Ejecuta ``programa`` contra la ``lib/`` REAL del repositorio.

    Se copia junto al fuente porque la búsqueda de librerías se ancla al
    directorio del que importa: lo que se prueba son esos archivos, no dónde
    viven.
    """
    import shutil
    import subprocess
    import tempfile

    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    with tempfile.TemporaryDirectory(prefix="suriax-vec-") as tmp:
        shutil.copytree(os.path.join(repo, "lib"), os.path.join(tmp, "lib"))
        ruta = os.path.join(tmp, "prog.srcx")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(programa)
        return subprocess.run(
            [sys.executable, os.path.join(repo, "V0", "main.py"), ruta, "--run"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", cwd=tmp, timeout=120)


def test_el_vector_dinamico_crece_en_vez_de_lanzar():
    """``vec.dynamic<T>(n)``: 'n' es el primer bloque, no un límite.

    Duplicar es lo que hace que N ``push`` cuesten O(N) y no O(N²): desde 1,
    diez elementos llegan a 16 espacios con cuatro duplicaciones. Se comprueba
    la CAPACIDAD y no solo que quepan, porque un vector que reservara uno más
    en cada push también pasaría la prueba de que caben.
    """
    proc = _con_la_lib_real("""\
#import array.vector as vec
fn __write__(str s) -> void;
fn main() -> int {
    var vec.Vector<int> v = vec.dynamic<int>(1);
    var int i = 0;
    while (i < 10) { v.push(i * i); i = i + 1; };
    __write__(f"{v.cap()} {v.len()} {v.get(9)} {v.fixed()}\\n");
    return 0;
};
""")
    assert "16 10 81 false" in proc.stdout, (proc.stdout, proc.stderr)


def test_el_vector_de_capacidad_fija_sigue_lanzando():
    """``make`` NO crece, y eso es deliberado: es a donde baja la azúcar
    ``int vec.Vector v[n];``, donde el número que escribió el usuario es una
    reserva que pidió. Crecer en silencio haría falso el aviso que el
    compilador promete (SEM033 al verlo, ``throw`` cuando no puede verlo)."""
    proc = _con_la_lib_real("""\
#import array.vector as vec
fn main() -> int {
    var vec.Vector<int> v = vec.make<int>(1);
    var int i = 0;
    while (i < 3) { v.push(i); i = i + 1; };
    return 0;
};
""")
    assert proc.returncode == 70, (proc.returncode, proc.stdout)
    assert "capacidad fija" in proc.stderr, proc.stderr


def test_crecer_suelta_el_bloque_viejo():
    """Un contenedor que fugara en cada duplicación sería la contradicción más
    visible de un lenguaje cuyo modelo es la propiedad. Se comprueba sobre la
    primitiva: tras ``mem.release`` el bloque ya no se puede leer."""
    proc = _con_la_lib_real("""\
#import mem
fn main() -> int {
    var int ptr mutable b = mem.reserve<int>(4);
    b[0] = 7;
    mem.release<int>(b);
    return b[0];
};
""")
    assert proc.returncode == 70, (proc.returncode, proc.stdout)
    assert "RT003" in proc.stderr, proc.stderr


def test_copiar_antes_de_soltar_conserva_los_datos():
    """El orden que usa ``grow``: reservar, copiar y SOLO ENTONCES soltar.
    Al revés se copiaría de un bloque ya liberado."""
    proc = _con_la_lib_real("""\
#import mem
fn main() -> int {
    var int ptr mutable a = mem.reserve<int>(2);
    a[0] = 5;
    var int ptr mutable b = mem.reserve<int>(4);
    mem.copy<int>(b, a, 2);
    mem.release<int>(a);
    return b[0];
};
""")
    assert proc.returncode == 5, (proc.returncode, proc.stderr)


def test_el_vector_de_la_stdlib_guarda_cualquier_tipo():
    """``Vector<T>``: el mismo código sirve para 'int' y para 'str'.

    Era monomórfico ('int' cableado en la firma) porque no había genéricos de
    FUNCIÓN: sin ``fn make<T>(...)`` no se podía construir uno de otra cosa.
    Se ejecuta contra la ``lib/`` REAL del repositorio —no una copia— porque
    lo que se está comprobando es que esa librería sirva.
    """
    import shutil
    import subprocess
    import tempfile

    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    programa = (
        "#from io #import stdp\n"
        "#import array.vector as vec\n"
        "fn main() -> int {\n"
        "    var vec.Vector<int> nums = vec.make<int>(4);\n"
        "    nums.push(10);\n"
        "    nums.push(20);\n"
        "    var vec.Vector<str> textos = vec.make<str>(2);\n"
        "    textos.push(\"hola\");\n"
        "    textos[1] = \"mundo\";\n"
        "    stdp.println(f\"{nums.get(1)} {textos[0]} {textos[1]} {nums.len()}\");\n"
        "    return nums.pop();\n"
        "};\n")
    with tempfile.TemporaryDirectory(prefix="suriax-vec-") as tmp:
        # la busqueda de librerias se ancla al directorio del FUENTE, asi que
        # la lib real se copia junto a el: lo que se prueba son esos archivos,
        # no dónde viven.
        shutil.copytree(os.path.join(repo, "lib"), os.path.join(tmp, "lib"))
        ruta = os.path.join(tmp, "prog.srcx")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(programa)
        proc = subprocess.run(
            [sys.executable, os.path.join(repo, "V0", "main.py"), ruta, "--run"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", cwd=tmp, timeout=120)
    assert "20 hola mundo 2" in proc.stdout, (
        f"stdout: {proc.stdout!r}\nstderr: {proc.stderr!r}")
    assert proc.returncode == 20, (
        f"'pop()' debía devolver 20 y salir con ese código; salió "
        f"{proc.returncode}")


def test_la_stdlib_del_compilador_se_encuentra_sin_copiarla():
    """Un programa FUERA del repositorio compila usando solo la stdlib.

    Antes solo se buscaba en el directorio del fuente y en el './lib' del
    proyecto, así que 'io' no existía para nadie que no tuviera una copia del
    árbol al lado. Eran dos cosas distintas mezcladas: las librerías que trae
    el COMPILADOR y las que escribe el USUARIO.
    """
    import subprocess
    import tempfile

    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    programa = ('#from io #import stdp\n'
                'fn main() -> int { stdp.println("stdlib"); return 0; };\n')
    with tempfile.TemporaryDirectory(prefix="suriax-std-") as tmp:
        ruta = os.path.join(tmp, "prog.srcx")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(programa)
        proc = subprocess.run(
            [sys.executable, os.path.join(repo, "V0", "main.py"), ruta, "--run"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", cwd=tmp, timeout=120)
    assert "stdlib" in proc.stdout, (proc.stdout, proc.stderr)


def test_una_libreria_del_usuario_le_gana_a_la_del_compilador():
    """La stdlib va la ÚLTIMA a propósito: es un respaldo, no una prioridad.
    Un proyecto puede sustituir cualquier pieza sin tocar el compilador."""
    import subprocess
    import tempfile

    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    propia = ('fn __write__(str s) -> void;\n'
              'public fn grita(str s) -> void { __write__(s); '
              '__write__("!\\n"); };\n'
              '#export as io\n')
    programa = ('#import io\n'
                'fn main() -> int { io.grita("mia"); return 0; };\n')
    with tempfile.TemporaryDirectory(prefix="suriax-std-") as tmp:
        os.makedirs(os.path.join(tmp, "lib"))
        with open(os.path.join(tmp, "lib", "io.libsrx"), "w",
                  encoding="utf-8") as fh:
            fh.write(propia)
        ruta = os.path.join(tmp, "prog.srcx")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(programa)
        proc = subprocess.run(
            [sys.executable, os.path.join(repo, "V0", "main.py"), ruta, "--run"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", cwd=tmp, timeout=120)
    assert "mia!" in proc.stdout, (proc.stdout, proc.stderr)

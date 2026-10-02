"""e2e/libraries: submodulos que se importan entre si.

Parte de ``test_libraries.py`` (partido por tema); lo compartido esta en
``libraries_support.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import assert_project_output, run_project  # noqa: E402

# --------------------------------------------------------------------------- #
# submodulos que se importan entre si, y un fuente DENTRO de su paquete
# --------------------------------------------------------------------------- #

def _pk_hermanos() -> dict:
    return {
        "lib/pk/main.libsrx": "#export package as pk\n",
        "lib/pk/a.libsrx": "public fn uno() -> int { return 1; }\n#export as a\n",
        "lib/pk/b.libsrx": "#import pk.a\npublic fn dos() -> int { "
                           "return a.uno() + 1; }\n#export as b\n",
    }


_USA_B = ('#from io #import stdp\n#import pk.b\n'
          'fn main() -> int { stdp.println(f"{b.dos()}"); return 0; };\n')


def test_un_submodulo_importa_a_su_hermano():
    """Regresion: 'pk/b' con '#import pk.a' se reportaba como import
    circular (SEM010): cargar 'pk.b' marcaba el PAQUETE 'pk' como en carga,
    y pedir 'pk.a' volvia a entrar en el. Ahora se carga solo el hermano."""
    assert_project_output({**_pk_hermanos(), "main.srcx": _USA_B}, "2\n")


def test_un_ciclo_real_entre_submodulos_se_sigue_detectando():
    files = {
        "lib/ci/main.libsrx": "#export package as ci\n",
        "lib/ci/x.libsrx": "#import ci.y\npublic fn fx() -> int { return 1; }\n"
                           "#export as x\n",
        "lib/ci/y.libsrx": "#import ci.x\npublic fn fy() -> int { return 2; }\n"
                           "#export as y\n",
        "main.srcx": "#import ci.x\nfn main() -> int { return x.fx(); };\n",
    }
    err = run_project(files)[2]
    assert "SEM010" in err and "circular" in err, err


def test_un_fuente_dentro_de_su_paquete_importa_sus_submodulos():
    """Regresion: un '.srcx' guardado DENTRO de la carpeta del paquete (como
    'src/aritmetica/calc.srcx') no encontraba 'pk.b': se buscaba 'pk/' junto
    al fuente, y el fuente ya estaba dentro. El linker busca ahora tambien en
    la raiz que CONTIENE al paquete del fuente."""
    assert_project_output({**_pk_hermanos(), "lib/pk/app.srcx": _USA_B},
                          "2\n", main="lib/pk/app.srcx")


# --------------------------------------------------------------------------- #
# genericos, enums y campos de tipos de libreria (nombres canonicos)
# --------------------------------------------------------------------------- #

_CAJA = {
    "lib/cont/main.libsrx": "#export package as cont\n",
    "lib/cont/caja.libsrx": (
        "struct { T valor; } Caja<T>;\n"
        "public fn hace<T>(T x) -> Caja<T> { return Caja<T>{ valor: move x }; }\n"
        "#export as caja\n"),
}

#: la misma caja, pero su 'hace' COPIA el parametro en vez de moverlo
_CAJA_QUE_COPIA = {
    "lib/cont/main.libsrx": "#export package as cont\n",
    "lib/cont/caja.libsrx": (
        "struct { T valor; } Caja<T>;\n"
        "public fn hace<T>(T x) -> Caja<T> { return Caja<T>{ valor: x }; }\n"
        "#export as caja\n"),
}

_RECURSO = ('#from io #import stdp\n#import cont.caja as cj\n'
            'struct { str n; } R;\n'
            'hook fn __free__(R ptr r) -> void { stdp.println(f"libera {r.n}"); }\n')


def test_un_generico_de_libreria_se_queda_con_su_temporal():
    """Regresion: 'cj.hace<R>(R{...})' destruia el temporal al terminar la
    sentencia aunque la Caja lo hubiera guardado: la regla de transferencia
    miraba el parametro 'T' SIN sustituir. Y la Caja, tipo de libreria
    ('cj.Caja'), no destruia su campo al salir del bloque. Debe verse UNA
    liberacion, despues de 'dentro'."""
    files = {**_CAJA, "main.srcx": _RECURSO + (
        'fn main() -> int {\n'
        '    if (true) {\n'
        '        var cj.Caja<R> c = cj.hace<R>(R{ n: "en caja" });\n'
        '        stdp.println("dentro");\n'
        '    };\n'
        '    stdp.println("fuera");\n'
        '    return 0;\n};\n')}
    code, out, err = run_project(files, args=["--run"])
    assert out.count("libera en caja") == 1, (out, err)
    assert out.index("dentro") < out.index("libera en caja") < out.index("fuera"), out


def test_un_generico_de_libreria_que_copia_su_T_no_se_instancia_con_un_dueno():
    """SEM038: 'hace' COPIA su parametro al literal ('valor: x'). Con 'T=R'
    la copia y el parametro (que ahora se destruye al salir) serian dos
    dueños del mismo 'R'. El error sale en la LLAMADA —el generico no esta
    mal: con 'T=int' es correcto— y dice donde copia."""
    files = {**_CAJA_QUE_COPIA, "main.srcx": _RECURSO + (
        'fn main() -> int {\n'
        '    var cj.Caja<R> c = cj.hace<R>(R{ n: "x" });\n'
        '    var cj.Caja<int> d = cj.hace<int>(3);\n'
        '    return 0;\n};\n')}
    code, out, err = run_project(files, args=["--run"])
    assert code != 0
    salida = out + err
    assert salida.count("SEM038") == 1, salida
    assert "caja.libsrx:2" in salida and "'x'" in salida, salida


def test_pasar_por_nombre_a_un_T_con_destructor_exige_move():
    """El mismo SEM032 que un parametro 'R': con T=R el generico se vuelve
    dueno, y pasarlo por nombre dejaria dos duenos."""
    files = {**_CAJA, "main.srcx": _RECURSO + (
        'fn main() -> int {\n'
        '    var R r = R{ n: "x" };\n'
        '    var cj.Caja<R> c = cj.hace<R>(r);\n'
        '    return 0;\n};\n')}
    err = run_project(files)[2]
    assert "SEM032" in err, err


_FIG = {"lib/fig.libsrx": "enum Figura { Circulo(int), Cuadro(int), Nada };\n"
                          "#export as fig\n"}


def test_desestructurar_un_enum_de_libreria_por_su_ruta():
    """Regresion: 'case fig.Figura.Circulo(r)' no ligaba 'r' (SEM001): las
    variantes solo se reconocian con un identificador delante."""
    files = {**_FIG, "main.srcx": (
        '#from io #import stdp\n#import fig\n'
        'fn area(fig.Figura f) -> int {\n'
        '    match (f) {\n'
        '        case fig.Figura.Circulo(r): { return 3 * r * r; }\n'
        '        case fig.Figura.Cuadro(l): { return l * l; }\n'
        '        case fig.Figura.Nada: { return 0; }\n'
        '    }\n    return -1;\n}\n'
        'fn main() -> int {\n'
        '    stdp.println(f"{area(fig.Figura.Circulo(2))} {area(fig.Figura.Cuadro(3))}");\n'
        '    return 0;\n};\n')}
    assert_project_output(files, "12 9\n")


def test_un_match_incompleto_sobre_un_enum_de_libreria_se_reporta():
    """Regresion: SEM030 callaba SIEMPRE con enums de libreria (la rama se
    trataba como opaca y el match quedaba sin comprobar)."""
    files = {**_FIG, "main.srcx": (
        '#import fig\n'
        'fn area(fig.Figura f) -> int {\n'
        '    match (f) {\n'
        '        case fig.Figura.Circulo(r): { return r; }\n'
        '    }\n    return -1;\n}\n'
        'fn main() -> int { return area(fig.Figura.Nada); };\n')}
    err = run_project(files)[2]
    assert "SEM030" in err, err


def test_el_campo_de_un_struct_de_libreria_tiene_tipo():
    """Regresion: el campo de un struct de libreria ('e.msg' con 'e' de tipo
    'errs.Error') quedaba sin tipo, asi que 'len(e.msg)' fallaba EN EJECUCION
    (RT006) y un campo mal escrito no se reportaba al compilar."""
    files = {"lib/errs.libsrx": "struct { str msg; } Error;\n#export as errs\n",
             "main.srcx": (
                 '#from io #import stdp\n#import errs\n'
                 'fn main() -> int {\n'
                 '    var errs.Error e = errs.Error{ msg: "cinco" };\n'
                 '    stdp.println(f"{len(e.msg)}");\n'
                 '    return 0;\n};\n')}
    assert_project_output(files, "5\n")
    files["main.srcx"] = files["main.srcx"].replace("e.msg)", "e.mensaje)")
    err = run_project(files)[2]
    assert "SEM001" in err and "mensaje" in err, err


# --------------------------------------------------------------------------- #
# un submódulo que no compila
# --------------------------------------------------------------------------- #

def _pk_con_uno_roto(main: str) -> dict:
    return {
        "lib/pk/main.libsrx": "#export package as pk\n",
        "lib/pk/a.libsrx": "public fn uno() -> int { return 1; }\n#export as a\n",
        "lib/pk/b.libsrx": "// roto\npublic fn dos() -> int {\n"
                           "    return 2 $ 3;\n}\n#export as b\n",
        "main.srcx": main,
    }


def test_una_libreria_rota_dice_donde_esta_cada_error():
    """Regresion: el SEM010 juntaba los errores en un mensaje con el archivo
    de la librería y la línea del consumidor ('b.libsrx:2:1', una posición
    que no existía), y detrás venía un SEM011 falso: "el paquete no tiene un
    submódulo 'b'". Ahora cada error sale en SU sitio y el SEM010 en la
    línea del import."""
    err = run_project(_pk_con_uno_roto(
        "#import pk.a\n#import pk.b\nfn main() -> int { return a.uno(); };\n"))[2]
    assert "LEX001" in err and "b.libsrx:3:14" in err, err
    assert "SEM010" in err and "line 2, column 1" in err, err
    assert "no tiene un submódulo" not in err, err


def test_un_submodulo_roto_que_no_se_importa_no_impide_compilar():
    """El paquete se carga entero en su primer import, pero un submódulo
    roto solo es un error para quien lo IMPORTA (como en Python, donde
    'import pk.a' no carga 'pk.b'). '#import pk' entero sí lo reporta."""
    assert_project_output(_pk_con_uno_roto(
        '#from io #import stdp\n#import pk.a\n'
        'fn main() -> int { stdp.println(f"{a.uno()}"); return 0; };\n'), "1\n")
    err = run_project(_pk_con_uno_roto(
        "#import pk\nfn main() -> int { return 0; };\n"))[2]
    assert "LEX001" in err and "SEM010" in err, err


def test_toda_libreria_del_repositorio_es_un_paquete():
    """Cada librería de ``lib/`` es una CARPETA con su ``main.libsrx``
    (``#export package as ...``), aunque hoy tenga un solo archivo: así crecer
    es añadir un submódulo y no mover lo que ya existe ni cambiar sus rutas.
    Un ``.libsrx`` suelto en la raíz de ``lib/`` no se podría extender sin
    romper a quien lo importa."""
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    raiz = os.path.join(repo, "lib")
    sueltos = [n for n in os.listdir(raiz) if n.endswith(".libsrx")]
    assert not sueltos, f"librerías sueltas en lib/ (hazlas paquete): {sueltos}"
    sin_padre = []
    for nombre in sorted(os.listdir(raiz)):
        carpeta = os.path.join(raiz, nombre)
        if not os.path.isdir(carpeta) or nombre.startswith(("_", ".")):
            continue
        padre = os.path.join(carpeta, "main.libsrx")
        if not os.path.isfile(padre):
            sin_padre.append(f"{nombre}: falta main.libsrx")
            continue
        with open(padre, encoding="utf-8") as fh:
            if "#export package as" not in fh.read():
                sin_padre.append(f"{nombre}: main.libsrx no cierra con '#export package as'")
    assert not sin_padre, "\n".join(sin_padre)

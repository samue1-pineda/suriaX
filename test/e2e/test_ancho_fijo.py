"""Los tipos de ancho fijo de ``lib/d_types`` son REALES, no una etiqueta.

Antes, ``dt_variables.libsrx`` solo declaraba ``__sizeof__`` con constantes:
``int8`` decía medir 1 byte pero su valor seguía siendo un entero de Python
de ancho ilimitado, así que el tamaño era una promesa que nada respaldaba.
Ahora la librería declara ``__cast__`` como PROTOTIPO y el host aplica el
ancho de verdad (``runtime/interpreter/intrinsics.py``).

Lo que se comprueba, y en este orden: que la conversión trunca como C, que
los flotantes redondean al formato IEEE del ancho, y —lo que ata las dos
mitades— que el ``sizeof`` que declara la librería COINCIDE con el ancho que
aplica el host. Si divergen, el tipo vuelve a mentir sobre su tamaño.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import run_project  # noqa: E402

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _lib_d_types() -> dict:
    """La librería REAL del repositorio, copiada al proyecto temporal.

    Se lee de ``lib/`` en vez de escribir una copia aquí: lo que se prueba es
    lo que se publica, no una réplica que puede quedarse vieja."""
    archivos = {}
    for nombre in ("main.libsrx", "dt_variables.libsrx"):
        ruta = os.path.join(_REPO_ROOT, "lib", "d_types", nombre)
        with open(ruta, encoding="utf-8") as fh:
            archivos[f"lib/d_types/{nombre}"] = fh.read()
    for nombre in ("main.libsrx", "stdp.libsrx", "stdpf.libsrx"):
        ruta = os.path.join(_REPO_ROOT, "lib", "io", nombre)
        with open(ruta, encoding="utf-8") as fh:
            archivos[f"lib/io/{nombre}"] = fh.read()
    return archivos


def _ejecutar(cuerpo: str) -> str:
    archivos = _lib_d_types()
    archivos["main.srcx"] = (
        "#from io #import stdpf\n"
        "#from d_types #import dt_variables as dt\n\n"
        "fn main() -> int {\n" + cuerpo + "\n    return 0;\n}\n"
    )
    code, out, err = run_project(archivos, args=["--run"])
    assert "=== errores" not in err, f"no compiló:\n{err}"
    assert code != 70, f"falló en runtime:\n{err}"
    return out


def test_los_enteros_truncan_como_c():
    """Complemento a dos: se queda con los bits bajos y reinterpreta el signo."""
    salida = _ejecutar(
        '    stdpf.printf(f"{cast<int>(cast<dt.int8>(300))} ");\n'
        '    stdpf.printf(f"{cast<int>(cast<dt.int8>(128))} ");\n'
        '    stdpf.printf(f"{cast<int>(cast<dt.int8>(-1))} ");\n'
        '    stdpf.printf(f"{cast<int>(cast<dt.int16>(70000))}");\n'
    )
    assert "44 -128 -1 4464" in salida, salida


def test_el_ancho_aplicado_coincide_con_el_sizeof_declarado():
    """El amarre entre las dos mitades: un valor que desborda EXACTAMENTE el
    tamaño declarado tiene que envolver a cero. Si el host truncara a otro
    ancho, 'sizeof' estaría mintiendo."""
    salida = _ejecutar(
        '    stdpf.printf(f"{cast<int>(cast<dt.int8>(256))} ");\n'
        '    stdpf.printf(f"{cast<int>(cast<dt.int16>(65536))} ");\n'
        '    stdpf.printf(f"{cast<int>(cast<dt.int32>(4294967296))}");\n'
    )
    assert "0 0 0" in salida, (
        f"2^(8*sizeof(T)) debe envolver a 0 en cada tipo; salió: {salida!r}")


def test_los_flotantes_redondean_al_formato_ieee_del_ancho():
    """binary16 y binary32 tienen menos mantisa que un 'float': pi lo nota."""
    salida = _ejecutar(
        '    stdpf.printf(f"{cast<float>(cast<dt.float16>(3.14159265358979))} ");\n'
        '    stdpf.printf(f"{cast<float>(cast<dt.float32>(3.14159265358979))}");\n'
    )
    assert "3.140625" in salida, f"binary16 de pi es 3.140625; salió: {salida!r}"
    assert "3.1415927" in salida, f"binary32 de pi; salió: {salida!r}"


def test_el_sizeof_de_la_libreria_y_el_ancho_del_host_no_pueden_divergir():
    """Comparación directa de las dos fuentes, sin ejecutar un programa: la
    tabla del host contra lo que declara el .libsrx."""
    import re
    from runtime.interpreter.intrinsics import ANCHOS

    ruta = os.path.join(_REPO_ROOT, "lib", "d_types", "dt_variables.libsrx")
    with open(ruta, encoding="utf-8") as fh:
        fuente = fh.read()
    declarados = {
        nombre: int(tam) for nombre, tam in
        re.findall(r"__sizeof__\((\w+) ptr _\)\s*->\s*int\s*\{\s*return\s*(\d+)",
                   fuente)
    }
    assert declarados, "no se pudo leer ningún '__sizeof__' de la librería"
    for nombre, tam in declarados.items():
        assert nombre in ANCHOS, (
            f"'{nombre}' declara __sizeof__ pero el host no le aplica ancho: "
            "sería un tamaño sin respaldo (intrinsics.ANCHOS)")
        assert ANCHOS[nombre] == tam, (
            f"'{nombre}': la librería dice {tam} bytes y el host aplica "
            f"{ANCHOS[nombre]}")


def test_una_conversion_no_declarada_sigue_siendo_un_error():
    """El host trae el ancho, pero quien AUTORIZA la conversión es la
    librería: sin su '__cast__' declarado, sigue siendo SEM016."""
    archivos = _lib_d_types()
    archivos["main.srcx"] = (
        "const type int8;\n"          # tipo homónimo SIN conversiones
        "fn main() -> int {\n"
        "    const int8 x = cast<int8>(1);\n"
        "    return 0;\n}\n"
    )
    code, out, err = run_project(archivos, args=["--run"])
    assert "SEM016" in err, (
        f"un tipo sin '__cast__' declarado no puede convertirse aunque el "
        f"host sepa hacerlo; salió: {err!r}")


def test_un_cast_a_tipo_nominal_no_revienta_con_traceback():
    """Regresión: ``_expr_cast`` reconstruía el par (origen, destino) leyendo
    ``Expr.restype``, un campo que el pool de tipos dejó ``reserved``. Toda
    conversión a un tipo NOMINAL moría con un ``ValueError`` de protobuf —un
    traceback de Python, justo lo que esta fase no debe producir— y ningún
    test lo veía porque los que existían solo ejecutaban casts primitivos."""
    archivos = _lib_d_types()
    archivos["main.srcx"] = (
        "#from d_types #import dt_variables as dt\n"
        "fn main() -> int {\n"
        "    const dt.int8 x = cast<dt.int8>(7);\n"
        "    return cast<int>(x);\n}\n"
    )
    code, out, err = run_project(archivos, args=["--run"])
    assert "Traceback" not in err, f"la conversión reventó:\n{err}"
    assert code == 7, f"esperaba 7 (el valor convertido), salió {code}: {err}"


def test_las_conversiones_de_un_submodulo_llegan_al_consumidor():
    """Regresión: el padre de un paquete fusionaba 'hooks' y 'dunders' de sus
    submódulos pero NO 'casts', así que 'cast<dt.int8>(x)' era SEM016 en el
    consumidor aunque la librería lo declarara."""
    archivos = _lib_d_types()
    archivos["main.srcx"] = (
        "#from d_types #import dt_variables as dt\n"
        "fn main() -> int { return cast<int>(cast<dt.int8>(300)); }\n"
    )
    code, out, err = run_project(archivos, args=["--run"])
    assert "SEM016" not in err, (
        f"las conversiones del submódulo no llegaron al consumidor:\n{err}")
    assert code == 44, f"esperaba 44 (300 truncado a int8), salió {code}: {err}"


# --------------------------------------------------------------------------- #
# el tipo, usado FUERA de una anotación escrita
# --------------------------------------------------------------------------- #
# Las anotaciones (``dt.int8 x``) las canonicaliza ``TypeBinder`` al validarlas.
# Los tipos que llegan de la TABLA DE SÍMBOLOS —el retorno de una función, el
# tipo de un campo— se guardaron tal como se escribieron, y ahí la conversión
# buscaba el par ``dt.int8 -> int`` que nadie declara (la librería lo registró
# como ``int8 -> int``). El tipo funcionaba en un parámetro y no en un campo.

def test_el_retorno_de_una_funcion_conserva_su_conversion():
    archivos = _lib_d_types()
    archivos["main.srcx"] = (
        "#from d_types #import dt_variables as dt\n"
        "fn dame() -> dt.int8 { return cast<dt.int8>(9); }\n"
        "fn main() -> int { return cast<int>(dame()); }\n"
    )
    code, _out, err = run_project(archivos, args=["--run"])
    assert "SEM016" not in err, f"el retorno perdió su conversión:\n{err}"
    assert code == 9, f"esperaba 9, salió {code}: {err}"


def test_un_campo_de_ancho_fijo_conserva_su_conversion():
    archivos = _lib_d_types()
    archivos["main.srcx"] = (
        "#from d_types #import dt_variables as dt\n"
        "struct { dt.int8 v; } Caja;\n"
        "fn main() -> int {\n"
        "    var Caja c = Caja{ v: cast<dt.int8>(5) };\n"
        "    return cast<int>(c.v);\n}\n"
    )
    code, _out, err = run_project(archivos, args=["--run"])
    assert "SEM016" not in err, f"el campo perdió su conversión:\n{err}"
    assert code == 5, f"esperaba 5, salió {code}: {err}"


def test_sizeof_de_un_valor_da_el_de_su_tipo():
    """``sizeof(a)`` con ``a`` una VARIABLE: sin esto no había forma de
    preguntar el tamaño de algo sin saber ya su tipo — y por tanto ninguna de
    imprimirlo."""
    salida = _ejecutar(
        "    const dt.int8 a = cast<dt.int8>(1);\n"
        "    const dt.float64 b = cast<dt.float64>(1.0);\n"
        '    stdpf.printf(f"{sizeof(a)} {sizeof(b)}\\n");'
    )
    assert "1 8" in salida, salida


def test_sizeof_de_un_valor_GLOBAL_tambien():
    """Regresión: dentro de una función el tipo del binding ya está
    canonicalizado (``TypeBinder`` lo hizo al validar la anotación), pero el
    de un global sale de la TABLA tal como se escribió (``dt.int32``), y el
    hook está registrado bajo ``int32``. Funcionaba local y no global."""
    archivos = _lib_d_types()
    archivos["main.srcx"] = (
        "#from d_types #import dt_variables as dt\n"
        "const dt.int32 g = 0;\n"
        "fn main() -> int { return sizeof(g); }\n"
    )
    code, _out, err = run_project(archivos, args=["--run"])
    assert "RT011" not in err, f"el sizeof del global no encontró su hook:\n{err}"
    assert code == 4, f"esperaba 4, salió {code}: {err}"


def test_sizeof_de_un_tipo_y_de_un_valor_coinciden():
    salida = _ejecutar(
        "    const dt.int16 a = cast<dt.int16>(1);\n"
        '    stdpf.printf(f"{sizeof(dt.int16)} {sizeof(a)}\\n");'
    )
    assert "2 2" in salida, salida


# --------------------------------------------------------------------------- #
# rango declarado: un LITERAL escrito donde se espera el tipo
# --------------------------------------------------------------------------- #
# ``const dt.int8 a = 10;`` no compilaba: ``int8`` es un nominal opaco y ``10``
# es un ``int``. Con ``__min__``/``__max__`` la pregunta "¿cabe?" tiene
# respuesta en COMPILACIÓN y la conversión declarada se inserta sola. La
# asimetría con ``cast<T>(x)`` es deliberada: la implícita exige que quepa, la
# explícita trunca.

def test_un_literal_que_cabe_se_convierte_solo():
    archivos = _lib_d_types()
    archivos["main.srcx"] = (
        "#from d_types #import dt_variables as dt\n"
        "fn main() -> int { const dt.int8 a = 10; return cast<int>(a); }\n"
    )
    code, _out, err = run_project(archivos, args=["--run"])
    assert "AST006" not in err, f"el literal no se aceptó:\n{err}"
    assert code == 10, f"esperaba 10, salió {code}: {err}"


def test_un_literal_negativo_tambien():
    archivos = _lib_d_types()
    archivos["main.srcx"] = (
        "#from d_types #import dt_variables as dt\n"
        "fn main() -> int { const dt.int8 a = -128; return cast<int>(a) + 200; }\n"
    )
    code, _out, err = run_project(archivos, args=["--run"])
    assert code == 72, f"esperaba 72 (-128 + 200), salió {code}: {err}"


def test_un_literal_fuera_de_rango_dice_el_rango():
    archivos = _lib_d_types()
    archivos["main.srcx"] = (
        "#from d_types #import dt_variables as dt\n"
        "fn main() -> int { const dt.int8 a = 300; return 0; }\n"
    )
    code, _out, err = run_project(archivos)
    assert code != 0 and "AST006" in err, err
    assert "[-128, 127]" in err, f"el error no dice el rango:\n{err}"


def test_el_cast_explicito_sigue_truncando():
    """La otra mitad de la asimetría: escribir el cast es pedir el recorte."""
    archivos = _lib_d_types()
    archivos["main.srcx"] = (
        "#from d_types #import dt_variables as dt\n"
        "fn main() -> int { return cast<int>(cast<dt.int8>(300)); }\n"
    )
    code, _out, err = run_project(archivos, args=["--run"])
    assert code == 44, f"esperaba 44 (300 truncado), salió {code}: {err}"


def test_un_tipo_sin_rango_no_acepta_literales():
    """``float32`` no publica ``__min__``/``__max__``: sin rango no se
    inventa nada, y el diagnóstico nombra la conversión que sí existe."""
    archivos = _lib_d_types()
    archivos["main.srcx"] = (
        "#from d_types #import dt_variables as dt\n"
        "fn main() -> int { const dt.float32 x = 1.5; return 0; }\n"
    )
    code, _out, err = run_project(archivos)
    assert code != 0 and "AST006" in err, err
    assert "cast<dt.float32>" in err, (
        f"la sugerencia tiene que nombrar el tipo como se puede escribir "
        f"aquí, no el canónico:\n{err}")


def test_el_literal_se_acepta_en_las_cuatro_posiciones():
    archivos = _lib_d_types()
    archivos["main.srcx"] = (
        "#from d_types #import dt_variables as dt\n"
        "struct { dt.int8 v; } Caja;\n"
        "fn toma(dt.int8 v) -> int { return cast<int>(v); }\n"
        "fn main() -> int {\n"
        "    var dt.int8 a = 1;\n"          # init
        "    a = 2;\n"                       # asignación
        "    var Caja c = Caja{ v: 4 };\n"   # campo de un literal
        "    return cast<int>(a) + cast<int>(c.v) + toma(8);\n}\n"  # argumento
    )
    code, _out, err = run_project(archivos, args=["--run"])
    assert "AST006" not in err, err
    assert code == 14, f"esperaba 14 (2+4+8), salió {code}: {err}"

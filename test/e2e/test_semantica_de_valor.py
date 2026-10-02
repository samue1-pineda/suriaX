"""e2e/semántica de valor — lo que los ejercicios reales destaparon.

Ninguno de estos fallos lo levantó una prueba unitaria: salieron de escribir
programas que alguien escribiría de verdad **sin librerías** (una máquina de
estados, recorrer una cadena, sumar enteros grandes). Es el mismo motivo por
el que existen los ejercicios: las pruebas unitarias encuentran lo que ya
sospechabas.

Lo que se fija aquí:

 - un ``struct`` es un VALOR: ligarlo a otro nombre lo copia, y mutar la copia
   no toca el original. Sin esto la regla de punteros no significaba nada —
   escribir por un ``ptr`` de solo lectura es ``SEM015``, pero bastaba pasar
   el struct por valor y mutarlo;
 - un parámetro declarado ``ptr`` NO se copia: es un préstamo, y es lo que
   permite que un hook o un método muten el receptor;
 - ``move`` como expresión transfiere de verdad: un solo destructor;
 - el ``int`` es de 64 bits y envuelve, igual que en el target web;
 - dividir por cero y caerse por el final de una función son diagnósticos
   con posición, no un traceback de Python ni un ``null`` silencioso.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import assert_output, run_program, run_source  # noqa: E402

_W = "fn __write__(str s) -> void;\n"


# --------------------------------------------------------------------------- #
# un struct es un valor
# --------------------------------------------------------------------------- #

def test_ligar_un_struct_lo_copia():
    """``var b = a`` daba DOS nombres al mismo valor: ``b.v = 99`` cambiaba
    también ``a``."""
    assert_output(
        _W + "struct { int v; } Caja;\n"
        "fn main() -> int {\n"
        "    var Caja a = Caja{ v: 1 };\n"
        "    var Caja b = a;\n"
        "    b.v = 99;\n"
        '    __write__(f"{a.v} {b.v}\\n");\n'
        "    return 0;\n"
        "};", "1 99\n")


def test_asignar_un_struct_lo_copia():
    """``b = a`` (y ``e.dentro = c``) tampoco pueden dejar dos dueños del
    mismo objeto: antes solo copiaba la declaración, y la asignación
    compartía."""
    assert_output(
        _W + "struct { int v; } Caja;\n"
        "struct { Caja dentro; } Par;\n"
        "fn main() -> int {\n"
        "    var Caja a = Caja{ v: 1 };\n"
        "    var Caja b = Caja{ v: 0 };\n"
        "    b = a;\n"
        "    b.v = 99;\n"
        "    var Par e = Par{ dentro: Caja{ v: 0 } };\n"
        "    e.dentro = a;\n"
        "    e.dentro.v = 7;\n"
        '    __write__(f"{a.v} {b.v} {e.dentro.v}\\n");\n'
        "    return 0;\n"
        "};", "1 99 7\n")


def test_un_parametro_por_valor_no_muta_al_llamador():
    """Si mutar un parámetro por valor tocara al llamador, ``ptr mutable`` no
    tendría sentido: bastaría pasar el struct para escribir donde no se debe."""
    assert_output(
        _W + "struct { int v; } Caja;\n"
        "fn modifica(Caja c) -> void { c.v = 99; }\n"
        "fn main() -> int {\n"
        "    var Caja k = Caja{ v: 1 };\n"
        "    modifica(k);\n"
        '    __write__(f"{k.v}\\n");\n'
        "    return 0;\n"
        "};", "1\n")


def test_un_parametro_puntero_si_muta_al_llamador():
    """El otro lado del contrato: un ``ptr`` es un préstamo y NO se copia.
    Es lo que hace que un hook o un método puedan mutar su receptor."""
    assert_output(
        _W + "struct { int v; } Caja;\n"
        "fn modifica(Caja ptr mutable c) -> void { c.v = 99; }\n"
        "fn main() -> int {\n"
        "    var Caja k = Caja{ v: 1 };\n"
        "    modifica(&k);\n"
        '    __write__(f"{k.v}\\n");\n'
        "    return 0;\n"
        "};", "99\n")


def test_move_como_expresion_transfiere_una_sola_vez():
    """``var R b = move a;`` ejecuta el destructor UNA vez. Antes no existía
    la forma —``move`` solo era sentencia— así que ligar era la única opción
    y dejaba dos dueños del mismo recurso."""
    assert_output(
        _W + "struct { int id; } R;\n"
        "hook fn __free__(R ptr r) -> void { __write__(f\"drop {r.id}\\n\"); };\n"
        "fn main() -> int {\n"
        "    var R a = R{ id: 1 };\n"
        "    var R b = move a;\n"
        '    __write__("fin\\n");\n'
        "    return 0;\n"
        "};", "fin\ndrop 1\n")


# --------------------------------------------------------------------------- #
# aritmética y fallos que antes eran tracebacks
# --------------------------------------------------------------------------- #

def test_el_int_envuelve_a_64_bits():
    """Python no tiene el límite; el target web sí. Sin envolver, los dos
    consumidores del MISMO programa daban números distintos — y guardar el
    valor reventaba el backend nativo de memoria con un error de pybind11."""
    assert_output(
        _W + "fn main() -> int {\n"
        "    var int grande = 9223372036854775807;\n"
        "    var int suma = grande + 1;\n"
        '    __write__(f"{suma}\\n");\n'
        "    return 0;\n"
        "};", "-9223372036854775808\n")


def test_dividir_por_cero_es_un_diagnostico():
    """Salía como un ``ZeroDivisionError`` de Python: un traceback del
    intérprete en vez de un error del programa, sin posición."""
    code, out, err = run_source(
        _W + "fn main() -> int {\n"
        "    var int cero = 0;\n"
        '    __write__(f"{10 / cero}\\n");\n'
        "    return 0;\n"
        "};", args=["--run"])
    assert "EXC001" in err, err   # antes RT016: ahora se puede atrapar
    assert "Traceback" not in err, err


def test_caerse_por_el_final_no_devuelve_null():
    """Una ``fn f() -> int`` que no devolvía entregaba ``null`` en silencio —
    un valor que no es un ``int`` en un lenguaje sin coerciones."""
    code, out, err = run_source(
        _W + "fn sin_return(int x) -> int {\n"
        "    if (x > 0) { return 1; }\n"
        "}\n"
        "fn main() -> int {\n"
        '    __write__(f"{sin_return(-5)}\\n");\n'
        "    return 0;\n"
        "};", args=["--run"])
    assert "RT017" in err, err
    assert "null" not in out, out


def test_una_funcion_void_puede_no_devolver():
    """El otro lado: sin tipo de retorno no falta nada."""
    assert_output(
        _W + 'fn saluda() -> void { __write__("hola\\n"); }\n'
        "fn main() -> int { saluda(); return 0; };", "hola\n")


# --------------------------------------------------------------------------- #
# genéricos: la sustitución también gobierna la DESTRUCCIÓN
# --------------------------------------------------------------------------- #

def test_un_generico_destruye_lo_que_su_argumento_posee():
    """``Caja<R>`` ejecuta el ``__free__`` de ``R``. El campo se declara como
    ``T`` y sin sustituir 'Caja<R>' no poseía nada: el destructor no corría y
    el recurso se perdía en silencio."""
    assert_output(
        _W + "struct { int id; } R;\n"
        "hook fn __free__(R ptr r) -> void { __write__(f\"drop {r.id}\\n\"); };\n"
        "struct { T dentro; } Caja<T>;\n"
        "fn main() -> int {\n"
        "    var Caja<R> c = Caja<R>{ dentro: R{ id: 5 } };\n"
        '    __write__("fin\\n");\n'
        "    return 0;\n"
        "};", "fin\ndrop 5\n")


def test_un_generico_anidado_tambien_destruye():
    """``Caja<Caja<R>>``: la guarda contra recursión infinita se lleva por el
    TIPO y no por su nombre — si no, el nivel de fuera cortaba el recorrido y
    el destructor de dentro se perdía."""
    assert_output(
        _W + "struct { int id; } R;\n"
        "hook fn __free__(R ptr r) -> void { __write__(f\"drop {r.id}\\n\"); };\n"
        "struct { T dentro; } Caja<T>;\n"
        "fn main() -> int {\n"
        "    var Caja<Caja<R>> a = "
        "Caja<Caja<R>>{ dentro: Caja<R>{ dentro: R{ id: 9 } } };\n"
        '    __write__("fin\\n");\n'
        "    return 0;\n"
        "};", "fin\ndrop 9\n")


def test_un_campo_prestado_de_un_generico_no_se_destruye():
    """El otro lado: ``Vista<R>`` guarda un ``T ptr``, que es un préstamo. Su
    dueño real lo destruye UNA vez."""
    assert_output(
        _W + "struct { int id; } R;\n"
        "hook fn __free__(R ptr r) -> void { __write__(f\"drop {r.id}\\n\"); };\n"
        "struct { T ptr prestado; } Vista<T>;\n"
        "fn main() -> int {\n"
        "    var R dueno = R{ id: 3 };\n"
        "    var Vista<R> v = Vista<R>{ prestado: &dueno };\n"
        '    __write__("fin\\n");\n'
        "    return 0;\n"
        "};", "fin\ndrop 3\n")


# --------------------------------------------------------------------------- #
# la división entera TRUNCA HACIA CERO (como C y como 'i64.div_s')
# --------------------------------------------------------------------------- #
# El intérprete usaba el '//' de Python, que redondea HACIA ABAJO: '-7 / 2'
# daba -4 donde el target web daba -3. El mismo programa contestaba distinto
# según quién lo ejecutara — y el resto ('%') ya estaba deliberadamente a la C
# justo al lado, así que las dos operaciones se contradecían entre ellas.

def test_la_division_entera_trunca_hacia_cero():
    assert_output(
        _W + "fn main() -> int {\n"
        '    __write__(f"{7 / 2}\\n");\n'
        '    __write__(f"{-7 / 2}\\n");\n'
        '    __write__(f"{7 / -2}\\n");\n'
        '    __write__(f"{-7 / -2}\\n");\n'
        "    return 0;\n"
        "};", "3\n-3\n-3\n3\n")


def test_el_cociente_y_el_resto_se_sostienen_mutuamente():
    """``(a/b)*b + a%b == a`` es la identidad que liga las dos operaciones.

    Con el cociente hacia abajo y el resto con el signo del dividendo NO se
    cumplía: ``-7`` daba ``-9``. Cualquiera de las dos convenciones es
    defendible por separado; mezclarlas no.
    """
    assert_output(
        _W + "fn main() -> int {\n"
        '    __write__(f"{-7 / 2 * 2 + -7 % 2}\\n");\n'
        '    __write__(f"{7 / -2 * -2 + 7 % -2}\\n");\n'
        "    return 0;\n"
        "};", "-7\n7\n")


def test_dividir_por_un_cero_LITERAL_no_compila():
    """'x / 0' escrito: el texto ya dice que no hay resultado (SEM035). Lo
    que se atrapa (EXC001) es el divisor que vale cero AL EJECUTAR. Un
    '0.0' no cuenta: entre float, IEEE-754 si tiene respuesta."""
    code, out, err = run_program(
        _W + "fn main() -> int {\n"
        "    var int a = 7 / 0;\n"
        "    var int b = 7 % 0;\n"
        "    var float f = 1.0 / 0.0;\n"
        "    return 0;\n"
        "};")
    assert code != 0 and err.count("SEM035") == 2, (out, err)


def test_dividir_por_cero_entre_FLOTANTES_no_es_un_error():
    """IEEE-754 sí tiene respuesta: ``1.0 / 0.0`` es ``+inf``.

    El intérprete lanzaba el error (hoy EXC001) mirando solo si el divisor valía cero, sin
    mirar el TIPO, así que inventaba un error donde el target web —y cualquier
    FPU— daba un valor. Entre enteros no hay respuesta y el error se queda.
    """
    assert_output(
        _W + "fn main() -> int {\n"
        "    var float uno = 1.0;\n"
        "    var float menos = -1.0;\n"
        "    var float cero = 0.0;\n"
        '    __write__(f"{uno / cero}\\n");\n'
        '    __write__(f"{menos / cero}\\n");\n'
        '    __write__(f"{cero / cero}\\n");\n'
        "    return 0;\n"
        "};", "inf\n-inf\nnan\n")


def test_dividir_por_cero_entre_ENTEROS_sigue_siendo_un_error():
    """El otro lado: ahí no hay valor que devolver y la instrucción trapea."""
    code, out, err = run_program(
        _W + "fn main() -> int {\n"
        "    var int a = 1;\n"
        "    var int b = 0;\n"
        '    __write__(f"{a / b}\\n");\n'
        "    return 0;\n"
        "};")
    assert "EXC001" in err, (out, err)


# --------------------------------------------------------------------------- #
# los límites de 'int': el rango de 64 bits con signo NO es simétrico
# --------------------------------------------------------------------------- #

def test_el_minimo_de_int_se_puede_escribir():
    """El mínimo existe pero su opuesto NO (+2^63 no cabe), así que leer
    '-9223372036854775808' como "menos el literal 9223372036854775808" obliga
    a pasar por un valor irrepresentable. El '-' pegado a un literal produce
    el literal negativo, que es lo que hace cualquier compilador con signo.

    Antes de esto, escribirlo reventaba el compilador con un 'ValueError' de
    protobuf: sin posición, sin código y sin mensaje del lenguaje.
    """
    assert_output(
        _W + "fn main() -> int {\n"
        "    var int min = -9223372036854775808;\n"
        "    var int max = 9223372036854775807;\n"
        '    __write__(f"{min} {max}\\n");\n'
        "    return 0;\n"
        "};", "-9223372036854775808 9223372036854775807\n")


def test_un_literal_que_no_cabe_en_int_es_un_error_con_su_posicion():
    code, out, err = run_program(
        _W + "fn main() -> int { var int x = 9223372036854775808; "
             "return 0; };")
    assert "AST006" in err, (out, err)
    assert "no cabe en 'int'" in err


def test_una_recursion_sin_caso_base_es_RT019_y_no_un_error_interno():
    """Agotaba la pila de Python y salía como ICE000 ("no es un fallo de tu
    programa") cuando la causa estaba en el programa."""
    code, out, err = run_source(
        _W + "fn sin_fin(int n) -> int { return sin_fin(n + 1); };\n"
        "fn main() -> int { return sin_fin(0); };", args=["--run"])
    assert code == 70, (code, err)
    assert "RT019" in err, err
    assert "sin_fin" in err, err
    assert "Traceback" not in err and "ICE000" not in err, err


def test_el_desbordamiento_se_reporta_aunque_el_cuerpo_anide_mucho():
    """Un cuerpo con bloques anidados gasta más pila de Python por llamada:
    el límite llega antes, pero el error tiene que ser el mismo."""
    code, _out, err = run_source(
        _W + "fn g(int n) -> int {\n"
        "    var int i = 0;\n"
        "    while (i < 1) {\n"
        "        if (n >= 0) { return g(n + 1) + 1; };\n"
        "    };\n"
        "    return 0;\n"
        "};\n"
        "fn main() -> int { return g(0); };", args=["--run"])
    assert code == 70, (code, err)
    assert "RT019" in err, err


def test_una_recursion_profunda_pero_finita_sigue_funcionando():
    """El otro lado: la guarda no puede cortar recursiones legítimas."""
    assert_output(
        _W + "fn suma(int n) -> int {\n"
        "    if (n == 0) { return 0; };\n"
        "    return n + suma(n - 1);\n"
        "};\n"
        'fn main() -> int { __write__(f"{suma(200)}\\n"); return 0; };',
        "20100\n")

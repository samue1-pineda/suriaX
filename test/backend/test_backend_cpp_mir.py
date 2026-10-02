"""backend/backend_cpp: el MIR completo (globales, enums, structs, hooks, excepciones).

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
# el MIR COMPLETO: lo que la etapa tiene que cubrir para no quedarse desnuda
# --------------------------------------------------------------------------- #
# Cada prueba de aquí abajo es el mismo diferencial —el intérprete como
# oráculo— sobre una construcción que la aritmética no toca. La lista junta
# es el inventario de lo que el MIR sabe bajar; una construcción que no
# aparezca aquí es una que nadie está comprobando.

def _salida_del_programa(corrida) -> list:
    """Lo que imprimió el PROGRAMA, sin lo que dice el COMPILADOR.

    El compilador escribe en stdout lo que emite ('HIR ... generado', una
    línea por unidad de librería); comparar eso contra la salida de la VM
    —que solo ejecuta— haría fallar todo programa con un ``#import``.
    """
    def es_del_compilador(linea: str) -> bool:
        if linea.startswith(("frontend OK", "HIR ", "[exit]")):
            return True
        # '  unidad 'mem': 900 bytes -> /ruta/mem.phir'
        return linea.lstrip().startswith("unidad '") and " -> " in linea

    return [l for l in corrida.stdout.splitlines() if not es_del_compilador(l)]


def _diferencial(fuente: str, esperado: int) -> None:
    """El .phir corrido por los dos: mismo valor de vuelta y misma salida."""
    def comprobar(binario, phir, corrida):
        obtenido = _vm(binario, phir)
        assert obtenido == esperado, (obtenido, esperado)
        assert corrida.returncode == _codigo_de_proceso(esperado), (
            f"la VM dio {obtenido} y el intérprete salió con "
            f"{corrida.returncode}")
        salida = _cpp(binario, phir, "--run").stdout.splitlines()
        salida = [l for l in salida if not l.startswith("[vm] main() -> ")]
        assert salida == _salida_del_programa(corrida), (
            salida, _salida_del_programa(corrida))
    _con_programa(fuente, comprobar)


def test_una_global_calculada_vale_lo_mismo_en_los_dos():
    """Registrar la global no basta: su inicializador es CÓDIGO y alguien
    tiene que ejecutarlo antes que 'main'. Sin eso valía cero."""
    _diferencial("""\
const int BASE = 7;
const int DOBLE = BASE * 2;
fn main() -> int { return BASE + DOBLE; };
""", 21)


def test_un_enum_es_un_entero_con_nombre():
    _diferencial("""\
enum E { A = 1, B = 10, C };
fn main() -> int {
    var E e = E.B;
    match (e) { case E.A: { return 0; }; case E.B: { return cast<int>(e) + cast<int>(E.C); }; };
    return 0;
};
""", 21)


def test_un_struct_viaja_como_handle_y_sus_campos_por_indice():
    """Los nombres de campo no llegan al MIR: el literal escribe en ORDEN DE
    DECLARACIÓN aunque se escriba desordenado, y el acceso lee por índice."""
    _diferencial("""\
struct { int v; } A;
struct { A dentro; int k; } B;
fn main() -> int {
    var B b = B{ k: 7, dentro: A{ v: 6 } };
    b.k = b.k - 1;
    return b.dentro.v * b.k;
};
""", 36)


def test_un_enum_con_payload_lleva_su_etiqueta_y_se_destructura():
    """Un enum SUMA no puede ser un entero: lleva valores dentro. Viaja como
    un objeto ``[etiqueta, campos...]``, el ``match`` compara la etiqueta y
    liga el payload en la rama. Que las variantes SIN payload del mismo enum
    también sean objetos no es desperdicio: el ``match`` lee siempre el campo
    0, y no puede depender de con cuál se construyó el valor."""
    _diferencial("""\
enum Dato { Vacio, Numero(int), Par(int, int) };
fn saca(Dato d) -> int {
    match (d) {
        case Dato.Vacio: { return 0; };
        case Dato.Numero(n): { return n; };
        case Dato.Par(a, b): { return a * b; };
    };
    return -1;
};
fn main() -> int {
    return saca(Dato.Numero(6)) + saca(Dato.Par(4, 5)) + saca(Dato.Vacio);
};
""", 26)


def test_un_puntero_a_un_valor_con_nombre_es_un_alias_de_verdad():
    """'&p' no copia: quien lo recibe escribe en el MISMO objeto. Es lo que
    hace el intérprete con sus celdas, y sin ello 'toca' no se vería."""
    _diferencial("""\
struct { int x; } P;
fn toca(P ptr mutable q) -> void { q.x = 99; };
fn main() -> int { var P p = P{ x: 1 }; toca(&p); return p.x; };
""", 99)


def test_las_cadenas_calculadas_existen_y_se_comparan_por_texto():
    """Una 'str' es el índice de su texto, y la tabla CRECE en ejecución:
    concatenar produce una cadena que no estaba en el fuente. Compararlas
    por índice habría dado falso para dos textos iguales."""
    _diferencial("""\
fn __write__(str s) -> void;
fn main() -> int {
    var str a = "ho";
    var str b = a + "la";
    __write__(f"{b} {len(b)} {b == \"hola\"}\\n");
    return len(b);
};
""", 4)


def test_los_hooks_del_vocabulario_fijo_se_llaman_como_funciones():
    _diferencial("""\
struct { int n; } C;
hook fn __len__(C ptr c) -> int { return c.n; };
hook fn __index__(C ptr c, int i) -> int { return c.n + i; };
hook fn __sizeof__(C ptr c) -> int { return 8; };
fn main() -> int { var C c = C{ n: 5 }; return len(c) + c[3] + sizeof(C); };
""", 21)


def test_el_destructor_corre_una_vez_por_valor_y_por_vuelta():
    """La lista de drops es estática pero el drop NO es incondicional: cada
    local destruible lleva una BANDERA de vivo, y el bucle la enciende en
    cada vuelta. Se comprueba por su efecto, que es lo único que prueba que
    corrió."""
    _diferencial("""\
struct { int id; } R;
fn __write__(str s) -> void;
hook fn __free__(R ptr r) -> void { __write__("drop\\n"); };
fn main() -> int {
    var int i = 0;
    while (i < 3) { var R a = R{ id: i }; i = i + 1; };
    return i;
};
""", 3)


def test_un_return_temprano_tambien_destruye():
    """Un bloque se cierra por 'return' igual que por caerse del final: en un
    CFG eso son dos aristas, y las dos tienen que pasar por el destructor.
    Uno que solo corriera al final sería una fuga."""
    _diferencial("""\
struct { int id; } R;
fn __write__(str s) -> void;
hook fn __free__(R ptr r) -> void { __write__("drop\\n"); };
fn main() -> int { var R a = R{ id: 3 }; if (a.id > 1) { return 1; }; return 0; };
""", 1)


def test_move_cede_el_destructor_y_por_eso_no_se_destruye_dos_veces():
    _diferencial("""\
struct { int id; } R;
fn __write__(str s) -> void;
hook fn __free__(R ptr r) -> void { __write__("drop\\n"); };
fn toma(R r) -> int { return r.id; };
fn main() -> int { var R a = R{ id: 4 }; return toma(move a); };
""", 4)


def test_un_throw_cruza_las_llamadas_y_lo_atrapa_la_rama_de_su_tipo():
    """El filtro del 'catch' es dinámico en el intérprete —pregunta de qué es
    el valor—; en el MIR el tipo lanzado viaja como una ETIQUETA, así que
    decidir la rama es comparar dos enteros. Tiene que dar lo mismo."""
    _diferencial("""\
fn falla() -> int { throw 9; return 0; };
fn medio() -> int { try { return falla(); } catch (str s) { return 1; }; return 0; };
fn main() -> int { try { return medio(); } catch (int n) { return 4; }; return 0; };
""", 4)


def test_una_excepcion_que_escapa_de_todo_sale_como_en_el_interprete():
    """No es un fallo de la VM: es el programa terminando mal, y los dos
    ejecutores tienen que decir lo mismo (código 70)."""
    def comprobar(binario, phir, corrida):
        assert corrida.returncode == 70, corrida.returncode
        resultado = _cpp(binario, phir, "--run")
        assert resultado.returncode == 70, (resultado.returncode,
                                            resultado.stderr)
        assert "no capturado" in resultado.stderr, resultado.stderr
    _con_programa("""\
fn main() -> int { throw 1; return 0; };
""", comprobar)


def test_el_indexado_crudo_de_un_bloque_no_es_el_de_una_cadena():
    """``buf[i]`` sobre un puntero es memoria; ``s[i]`` sobre una ``str`` es
    un carácter. Se escriben igual y no son lo mismo: bajar el primero como
    el segundo leería la tabla de constantes en vez del montón. El índice es
    un VALOR, así que tampoco puede ser el acceso a campo de un struct, cuyo
    índice se resuelve al compilar."""
    _diferencial("""\
#import mem
fn main() -> int {
    var int ptr mutable b = mem.reserve<int>(4);
    var int i = 0;
    while (i < 4) { b[i] = i * 10; i = i + 1; };
    return b[3] - b[1];
};
""", 20)


def test_el_vector_de_la_stdlib_corre_igual_en_la_vm():
    """El diferencial sobre la librería REAL, que es lo que ejercita a la vez
    los genéricos, los métodos ``@impl``, los hooks de índice, las primitivas
    de memoria del host y el crecimiento. Si la VM y el intérprete discrepan
    aquí, discrepan en todo lo que se construya encima."""
    _diferencial("""\
#import array.vector as vec
fn __write__(str s) -> void;
fn main() -> int {
    var vec.Vector<int> v = vec.dynamic<int>(1);
    var int i = 0;
    while (i < 10) { v.push(i * i); i = i + 1; };
    v[0] = 100;
    __write__(f"{v.cap()} {v.len()} {v[0]} {v.get(9)}\\n");
    return v.pop();
};
""", 81)

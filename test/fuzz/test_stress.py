"""fuzz/stress — entradas que ponen a sudar al compilador.

Dos objetivos distintos:

 1. **Robustez**: entradas adversariales (anidamiento extremo, cadenas
    enormes, basura aleatoria) no deben *colgar* ni lanzar excepciones sin
    controlar — o fallan con un diagnóstico limpio, o compilan. Nunca un
    traceback de Python.
 2. **Escala**: programas grandes (miles de símbolos/sentencias) deben
    compilar en tiempo razonable — cada pasada es O(n) por diseño, así que
    un cambio que introduzca cuadraticidad se nota aquí.

Los umbrales de tiempo son GENEROSOS a propósito (buscan detectar un salto
de complejidad, no medir la máquina).
"""

from __future__ import annotations

import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import analyze, assert_output, lex, omitir, parse  # noqa: E402

WRITE = "fn __write__(str s) -> void;\n"


def _timed(fn, *args, **kwargs):
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    return result, time.perf_counter() - t0


# --------------------------------------------------------------------------- #
# 1. robustez ante entradas adversariales
# --------------------------------------------------------------------------- #

def test_parentesis_muy_anidados_no_revientan():
    """500 niveles de anidamiento: o parsea, o da ExpressionTooDeep — pero
    NUNCA un RecursionError sin controlar (ver grammar/program.py)."""
    depth = 500
    src = f"fn f() -> void {{ var int a = {'(' * depth}1{')' * depth}; }};"
    program, errors, _ = parse(src)
    codes = [e.code for e in errors]
    assert all(c.startswith("PAR") for c in codes), (
        f"solo se admiten diagnósticos PARxxx controlados, hubo: {codes}"
    )


def test_anidamiento_extremo_da_error_controlado():
    """5000 niveles: debe reportar ExpressionTooDeep, no matar el proceso."""
    depth = 5000
    src = f"fn f() -> void {{ var int a = {'(' * depth}1{')' * depth}; }};"
    _, errors, _ = parse(src)
    assert errors, "un anidamiento extremo debe reportarse"
    assert all(e.code.startswith("PAR") for e in errors), [e.code for e in errors]


def test_bloques_anidados_profundos():
    """200 'if' anidados: el walker es iterativo, no debe desbordar. Caben
    en el límite de anidamiento del lenguaje (500 niveles, ~247 'if')."""
    depth = 200
    src = ("fn f() -> void {\n" + "".join(
        f"{'  ' * i}if (true) {{\n" for i in range(depth)
    ) + "".join(f"{'  ' * (depth - i - 1)}}};\n" for i in range(depth)) + "};")
    _, _, errors = analyze(src)
    assert not errors, f"bloques anidados válidos no deben fallar: {errors[:3]}"


def test_cadena_muy_larga():
    """Una cadena de 100k caracteres pasa por el lexer sin degradarse."""
    literal = "x" * 100_000
    (tokens, errs), elapsed = _timed(lex, f'fn f() -> void {{ var str s = "{literal}"; }};')
    assert not errs, errs
    assert elapsed < 5.0, f"lexer tardó {elapsed:.2f}s en una cadena de 100k"


def test_muchas_interpolaciones_en_una_fstring():
    parts = "".join(f"{{a}}" for _ in range(500))
    src = f'fn f() -> void {{ var int a = 1; var str s = f"{parts}"; }};'
    _, _, errors = analyze(src)
    assert not errors, errors[:3]


def test_basura_aleatoria_no_produce_traceback():
    """Fuzz: 300 entradas aleatorias — el compilador SIEMPRE termina con
    diagnósticos, nunca con una excepción no controlada."""
    rng = random.Random(20240720)  # semilla fija: fallo reproducible
    alfabeto = list("{}()[];:,.<>=+-*/&?!|@#\"'\\ \tabcXY019_") + [
        "fn", "int", "if", "while", "return", "struct", "error", "try",
        "catch", "throw", "cast", "test", "ptr", "var", "const", "move",
    ]
    for i in range(300):
        n = rng.randint(1, 60)
        src = "".join(rng.choice(alfabeto) for _ in range(n))
        try:
            analyze(src)
        except RecursionError:
            raise AssertionError(f"RecursionError sin controlar con: {src!r}")
        except Exception as exc:  # noqa: BLE001 - eso es justo lo que se caza
            raise AssertionError(
                f"excepción no controlada ({type(exc).__name__}: {exc}) "
                f"en la entrada #{i}: {src!r}"
            )


def test_archivo_vacio_y_solo_comentarios():
    for src in ("", "\n\n", "// solo un comentario\n", "/- bloque -/\n"):
        program, errors, _ = parse(src)
        assert not errors, f"{src!r} -> {errors}"
        assert program.items == [], f"{src!r} no debería producir items"


def test_utf8_e_identificadores_unicode():
    """Comentarios y cadenas con no-ASCII no rompen posiciones ni decodificación."""
    src = WRITE + ('// ácentos, ñ, 中文, emoji 🎉\n'
                   'fn main() -> int { __write__("añ中🎉\\n"); return 0; };')
    _, _, errors = analyze(src)
    assert not errors, errors


# --------------------------------------------------------------------------- #
# 2. escala: el pipeline es O(n), no cuadrático
# --------------------------------------------------------------------------- #

def test_mil_funciones():
    src = "".join(f"fn f{i}(int a) -> int {{ return a + {i}; }};\n" for i in range(1000))
    (result, elapsed) = _timed(analyze, src)
    _, table, errors = result
    assert not errors, errors[:3]
    assert len(table.global_scope.values) == 1000
    assert elapsed < 20.0, f"1000 funciones tardaron {elapsed:.2f}s"


def test_mil_variables_en_una_funcion():
    cuerpo = "".join(f"    var int v{i} = {i};\n" for i in range(1000))
    src = f"fn f() -> void {{\n{cuerpo}}};"
    (result, elapsed) = _timed(analyze, src)
    _, _, errors = result
    assert not errors, errors[:3]
    assert elapsed < 20.0, f"1000 variables tardaron {elapsed:.2f}s"


def test_struct_con_muchos_campos():
    campos = "".join(f"    int c{i};\n" for i in range(500))
    src = f"struct {{\n{campos}}} Grande;"
    _, table, errors = analyze(src)
    assert not errors, errors[:3]
    assert len(table.global_scope.types["Grande"].members) == 500


def _cadenas(n):
    """Programas cuyo árbol anida ``n`` niveles SIN anidar al escribirse (o
    anidando, en los dos últimos): una forma por cada sitio donde el parser
    encadena nodos."""
    return {
        "suma": "fn main() -> int { return " + "1 + " * n + "1; }\n",
        "concatenación": 'fn main() -> int { var str s = '
                         + '"a" + ' * n + '"a"; return 0; }\n',
        # cada '.nx' es un 'P ptr' (se lee a traves del puntero) y el ultimo
        # '.x' un 'int'. Antes era 'p.x.x.x...' sobre un 'int', que compilaba
        # solo porque un miembro de un primitivo no se comprobaba (H04: ahora
        # es SEM042); la forma que se mide es la misma, una cadena de miembros.
        # 'main' va en la linea de la cadena: es como la localiza el PAR025
        "miembros": "struct { P ptr nx; int x; } P;\nfn main() -> int "
                    "{ return 0; } fn f(P ptr p) -> int { return p"
                    + ".nx" * n + ".x; }\n",
        "llamadas": "fn f(int a) -> int { return a; }\nfn main() -> int "
                    "{ return " + "f(" * n + "1" + ")" * n + "; }\n",
        "else if": "fn main() -> int { var int a = 1; if (a == 0) "
                   "{ return 0; } " + "else if (a == 1) { return 1; } " * n
                   + "return 2; }\n",
        "bloques": "fn main() -> int { var int t = 0; "
                   + "if (t == 0) { " * n + "t = 1; " + "} " * n
                   + "return t; }\n",
    }


def test_lo_que_anida_de_mas_es_PAR025_en_cualquier_forma():
    """El límite es DEL LENGUAJE (``MAX_NESTING``), no de la pila de quien
    compila. Antes una suma larga —que no anida al escribirse, pero sí al
    recorrerse— pasaba el parser y tumbaba al emisor del HIR: fallo interno
    con 3000 términos en la terminal y con 300 desde el playground, que
    corre con el límite de recursión por defecto.

    Se comprueba con el límite POR DEFECTO de Python a propósito: el
    resultado no puede depender de cuánto margen trajo quien llama."""
    from src.frontend.parser.grammar.program import MAX_NESTING

    previo = sys.getrecursionlimit()
    sys.setrecursionlimit(1_000)
    try:
        for forma, src in _cadenas(MAX_NESTING + 50).items():
            _, errores, _ = parse(src)
            codigos = [e.code for e in errores]
            assert codigos == ["PAR025"], (forma, codigos)
            # y dice DÓNDE: en la línea de la cadena, no al principio
            assert errores[0].line == src.count("\n", 0, src.index("main")) + 1, \
                (forma, errores[0].line)
    finally:
        sys.setrecursionlimit(previo)


def test_una_declaracion_que_anida_de_mas_no_llega_a_las_demas_fases():
    """Se descarta ENTERA: dejar pasar un árbol que las pasadas siguientes no
    pueden recorrer cambiaría un diagnóstico por un fallo interno. Las demás
    declaraciones del archivo se conservan."""
    from src.frontend.parser.grammar.program import MAX_NESTING

    src = ("fn antes() -> int { return 1; }\n"
           "fn honda() -> int { return " + "1 + " * (MAX_NESTING + 50) + "1; }\n"
           "fn despues() -> int { return 2; }\n")
    programa, errores, _ = parse(src)
    assert [e.code for e in errores] == ["PAR025"]
    assert errores[0].line == 2
    assert [d.name for d in programa.items] == ["antes", "despues"]


def test_lo_mas_hondo_que_se_acepta_recorre_todas_las_fases():
    """La otra mitad del contrato: lo que el parser ACEPTA tiene que poder
    con todo lo que viene después —semántica, emisor del HIR, sus dos vistas
    y el volcado del árbol—, que es donde antes reventaba. Se busca el mayor
    programa de cada forma en vez de escribir un número: el margen exacto
    depende de cuántos nodos envuelven a la cadena."""
    from driver.artifacts import collect
    from src.frontend.parser.grammar.program import MAX_NESTING

    for forma in _cadenas(1):
        menor, mayor = 1, MAX_NESTING
        while menor < mayor:
            medio = (menor + mayor + 1) // 2
            _, errores, _ = parse(_cadenas(medio)[forma])
            if errores:
                mayor = medio - 1
            else:
                menor = medio
        assert menor > MAX_NESTING // 3, (forma, menor)
        datos = collect(_cadenas(menor)[forma], path="hondo.srcx")
        assert not datos["diagnostics"], (forma, menor, datos["diagnostics"][:2])
        for fase in ("ast", "typed_ast", "symbols", "hir", "link"):
            assert datos["phases"][fase]["ok"], (forma, fase)
        assert datos["phir"], forma


def test_quien_usa_el_compilador_como_libreria_tiene_el_margen_de_la_cli():
    """``V0/main.py`` subía el límite de recursión y ``driver`` no: el mismo
    programa compilaba en la terminal y era un fallo interno en el
    playground. Ahora lo fija ``driver``, que es por donde entran los dos."""
    import subprocess

    orden = ("import sys; sys.path[:0] = ['V0', '.']; import driver; "
             "from driver.artifacts import collect; "
             "d = collect('fn main() -> int { return ' + '1 + ' * 300 + '1; }', "
             "path='x.srcx'); "
             "print(sys.getrecursionlimit(), len(d['diagnostics']), 'phir' in d)")
    raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sale = subprocess.run([sys.executable, "-c", orden], capture_output=True,
                          text=True, cwd=raiz, timeout=120)
    assert sale.stdout.split() == ["10000", "0", "True"], (sale.stdout,
                                                           sale.stderr[-400:])


def test_una_suma_larga_que_cabe_compila_y_CORRE():
    """Hasta el final: 400 términos se suman en el intérprete."""
    from helpers import run_source

    src = ("#from io #import stdp\n"
           "fn main() -> int {\n"
           "    var int total = " + " + ".join(["1"] * 400) + ";\n"
           '    stdp.println(f"{total}");\n'
           "    return 0;\n"
           "}\n")
    codigo, salida, error = run_source(src, args=["--run", "interpreter"])
    assert codigo == 0 and salida.strip().splitlines()[-1] == "400", \
        (codigo, salida[-200:], error[-300:])


def test_anidamiento_semantico_degrada_a_diagnostico():
    """Sin margen de pila, la Semántica reporta SEM017 en vez de reventar.

    Con el límite de anidamiento del parser esto ya no lo alcanza un programa
    (lo que anida de más es ``PAR025`` antes de llegar aquí); la red sigue
    puesta para quien le pase a la Semántica un árbol hecho a mano, y se
    prueba así: con un árbol que el parser no habría entregado."""
    from include import ast_nodes as ast
    from src.frontend.parser.typed_ast import resolve_types
    from src.frontend.semantic import analyze as semantic_analyze

    programa, errores, _ = parse("fn f() -> void { var int a = 1 + 2; };")
    assert not errores
    declaracion = programa.items[0].body.statements[0]
    suma = declaracion.value
    for _ in range(4000):
        suma = type(suma)(ln=suma.ln, col=suma.col, operator=suma.operator,
                          left=suma, right=declaracion.value.right)
    declaracion.value = suma
    previo = sys.getrecursionlimit()
    sys.setrecursionlimit(1_000)  # margen deliberadamente insuficiente
    try:
        resolve_types(programa)
        _, sem_errors = semantic_analyze(programa)
    except RecursionError:
        raise AssertionError("la Semántica lanzó RecursionError en vez de degradar")
    finally:
        sys.setrecursionlimit(previo)
    codes = [e.code for e in sem_errors]
    assert "SEM017" in codes, f"esperaba SEM017 (too deep); códigos: {codes}"


def test_escalado_lineal_del_frontend():
    """El tiempo debe crecer ~linealmente con el tamaño, no al cuadrado.

    Se compara 200 vs 800 funciones (4x el tamaño): un pipeline O(n) tarda
    ~4x; uno cuadrático tardaría ~16x. El umbral (10x) deja margen de sobra
    para el ruido de medición pero atrapa un salto de complejidad real.
    """
    def gen(n):
        return "".join(f"fn f{i}(int a) -> int {{ return a + {i}; }};\n"
                       for i in range(n))

    _, t_small = _timed(analyze, gen(200))
    _, t_large = _timed(analyze, gen(800))
    if t_small < 0.01:
        # por debajo de 10 ms el ruido del reloj domina la razón: comparar
        # dos medidas así no probaría el escalado, solo el azar.
        omitir(f"medición no fiable: 200 funciones tardaron "
               f"{t_small * 1000:.1f} ms (< 10 ms)")
    ratio = t_large / t_small
    assert ratio < 10.0, (
        f"escalado sospechoso: 4x el tamaño costó {ratio:.1f}x el tiempo "
        "(¿se introdujo una pasada cuadrática?)"
    )


# --------------------------------------------------------------------------- #
# 3. escala del intérprete (end-to-end)
# --------------------------------------------------------------------------- #

def test_bucle_de_cien_mil_iteraciones():
    """El tree-walk sostiene 100k iteraciones sin degradarse ni desbordar."""
    src = WRITE + """
fn main() -> int {
    var int i = 0;
    var int suma = 0;
    while (i < 100000) {
        suma = suma + i;
        i = i + 1;
    };
    __write__(f"{suma}\\n");
    return 0;
};
"""
    assert_output(src, "4999950000")


def test_recursion_profunda_en_el_interprete():
    """1000 niveles de recursión: el evaluator usa la pila de Python, así que
    'V0/main.py' sube el recursionlimit — esto verifica que alcance."""
    src = WRITE + """
fn cuenta(int n) -> int {
    if (n <= 0) { return 0; };
    return 1 + cuenta(n - 1);
};
fn main() -> int { __write__(f"{cuenta(1000)}\\n"); return 0; };
"""
    assert_output(src, "1000")


def test_muchas_asignaciones_a_campos_por_puntero():
    src = WRITE + """
struct { int x; } C;
fn main() -> int {
    var C c = C{ x: 0 };
    var C ptr mutable p = &c;
    var int i = 0;
    while (i < 10000) {
        p.x = p.x + 1;
        i = i + 1;
    };
    __write__(f"{c.x}\\n");
    return 0;
};
"""
    assert_output(src, "10000")

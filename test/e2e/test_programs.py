"""e2e — programas reales: compilan, EJECUTAN y su salida se compara.

Estos son los que demuestran capacidad: cada uno pasa por el pipeline
completo (lexer -> parser -> AST-tipado -> Semántica -> HIR protobuf ->
module linker -> tree-walk) en un subproceso aislado, como lo haría un
usuario. Si alguno falla, algo se rompió de punta a punta.

Todos son AUTOCONTENIDOS: declaran el prototipo del host ``__write__`` (que
el intérprete liga a un intrínseco) en vez de depender de una librería, así
la suite no depende del estado de ``lib/``.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import assert_output, run_program  # noqa: E402

WRITE = "fn __write__(str s) -> void;\n"


def test_hola_mundo():
    assert_output(WRITE + 'fn main() -> int { __write__("hola\\n"); return 0; };',
                  "hola")


def test_aritmetica_y_precedencia():
    assert_output(
        WRITE + 'fn main() -> int { var int x = 1 + 2 * 3 - 4 / 2; '
                '__write__(f"{x}\\n"); return 0; };',
        "5",  # 1 + 6 - 2
    )


def test_control_de_flujo_fizzbuzz():
    src = WRITE + """
fn main() -> int {
    var int i = 1;
    while (i <= 15) {
        if (i / 15 * 15 == i) {
            __write__("FizzBuzz ");
        }; else {
            if (i / 3 * 3 == i) {
                __write__("Fizz ");
            }; else {
                if (i / 5 * 5 == i) {
                    __write__("Buzz ");
                }; else {
                    __write__(f"{i} ");
                };
            };
        };
        i = i + 1;
    };
    __write__("\\n");
    return 0;
};
"""
    assert_output(src, "1 2 Fizz 4 Buzz Fizz 7 8 Fizz Buzz 11 Fizz 13 14 FizzBuzz")


def test_recursion_factorial():
    src = WRITE + """
fn fact(int n) -> int {
    if (n <= 1) { return 1; };
    return n * fact(n - 1);
};
fn main() -> int { __write__(f"{fact(10)}\\n"); return 0; };
"""
    assert_output(src, "3628800")


def test_recursion_fibonacci():
    src = WRITE + """
fn fib(int n) -> int {
    if (n < 2) { return n; };
    return fib(n - 1) + fib(n - 2);
};
fn main() -> int { __write__(f"{fib(20)}\\n"); return 0; };
"""
    assert_output(src, "6765")


def test_structs_y_punteros():
    src = WRITE + """
struct { int x; int y; } Punto;

fn suma_coords(Punto ptr p) -> int {
    return p.x + p.y;
};

fn main() -> int {
    var Punto p = Punto{ x: 3, y: 4 };
    __write__(f"{suma_coords(&p)}\\n");
    return 0;
};
"""
    assert_output(src, "7")


def test_escritura_a_traves_de_puntero_mutable():
    src = WRITE + """
struct { int x; } Caja;

fn incrementa(Caja ptr mutable c) -> void { c.x = c.x + 1; };

fn main() -> int {
    var Caja c = Caja{ x: 41 };
    incrementa(&c);
    __write__(f"{c.x}\\n");
    return 0;
};
"""
    assert_output(src, "42")


def test_lista_enlazada_recorrido():
    """Una lista enlazada en una ARENA: los nodos en un vector y el enlace es
    un indice (-1 = fin). 'return &n' de un local seria un puntero colgante
    (SEM037)."""
    src = WRITE + """
#import array.vector as vec
struct { int v; int sig; } Nodo;

fn cons(vec.Vector<Nodo> ptr mutable arena, int v, int resto) -> int {
    arena.push(Nodo{ v: v, sig: resto });
    return arena.len() - 1;
};

fn suma(vec.Vector<Nodo> ptr arena, int n) -> int {
    if (n < 0) { return 0; };
    var Nodo nodo = arena.get(n);
    return nodo.v + suma(arena, nodo.sig);
};

fn main() -> int {
    var vec.Vector<Nodo> arena = vec.dynamic<Nodo>(4);
    var int lista = cons(&arena, 1, cons(&arena, 2, cons(&arena, 3, -1)));
    __write__(f"{suma(&arena, lista)}\\n");
    return 0;
};
"""
    assert_output(src, "6")


def test_enum_y_match():
    src = WRITE + """
enum Estado { Inactivo, Activo, Pausado };

fn describir(int s) -> void {
    match (s) {
        case 0: __write__("inactivo ");
        case 1: __write__("activo ");
        case 2: __write__("pausado ");
    };
};

fn main() -> int {
    describir(Inactivo);
    describir(Activo);
    describir(Pausado);
    __write__("\\n");
    return 0;
};
"""
    assert_output(src, "inactivo activo pausado")


def test_try_catch_captura_throw_propagado():
    """El throw atraviesa DOS niveles de llamada hasta el catch."""
    src = WRITE + """
fn hondo(int x) -> error int { throw x; };
fn medio(int x) -> error int { return hondo(x); };

fn main() -> int {
    try {
        var int v = medio(7);
        __write__("no llega\\n");
    } catch (e) {
        __write__(f"capturado {e}\\n");
    };
    return 0;
};
"""
    assert_output(src, "capturado 7")


def test_throw_no_capturado_falla_con_codigo_70():
    src = WRITE + """
fn boom() -> error int { throw 1; };
fn main() -> int { var int x = boom(); return x; };
"""
    code, out, err = run_program(src)
    assert code == 70, f"un throw no capturado debe salir con 70, salió {code}"
    assert "no capturado" in err, err


def test_use_after_move_en_runtime():
    """El move de una iteración anterior lo atrapa el RUNTIME (RT001), no
    el análisis estático lineal (falso negativo deliberado)."""
    src = WRITE + """
fn main() -> int {
    var int x = 5;
    var int i = 0;
    while (i < 2) {
        if (i == 1) { var int y = x; };
        move x;
        i = i + 1;
    };
    return 0;
};
"""
    code, out, err = run_program(src)
    assert code == 70, f"esperaba fallo de runtime, salió {code}"
    assert "RT001" in err, err


def test_use_after_free_en_runtime():
    src = WRITE + """
fn main() -> int {
    var int a = 42;
    var int ptr mutable p = &a;
    free p;
    var int b = a;
    return b;
};
"""
    code, out, err = run_program(src)
    assert code == 70, f"esperaba fallo de runtime, salió {code}"
    assert "RT003" in err, err


def test_cast_nativo_y_por_hook():
    src = WRITE + """
const type Celsius;
hook fn __cast__(int x) -> Celsius;
hook fn __cast__(Celsius c) -> int;

fn main() -> int {
    var float f = cast<float>(7);
    var int n = cast<int>(f);
    __write__(f"{n}\\n");
    return 0;
};
"""
    assert_output(src, "7")


def test_bloques_test_se_ejecutan_con_el_runner():
    """'test \"...\" { }' corre con el runner del intérprete, no con --run."""
    src = WRITE + """
fn doble(int n) -> int { return n * 2; };
fn main() -> int { return 0; };

test "doble de 21" {
    var int r = doble(21);
    expect (r == 42);
    __write__("ok\\n");
};
"""
    import subprocess
    import tempfile
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    with tempfile.TemporaryDirectory(prefix="suriax-tests-") as tmp:
        path = os.path.join(tmp, "t.srcx")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(src)
        subprocess.run([sys.executable, os.path.join(repo, "V0", "main.py"),
                        path, "--emit-hir"], capture_output=True, cwd=tmp,
                       timeout=120)
        phir = os.path.join(tmp, "dumps", "t.srcx.phir")
        assert os.path.isfile(phir), "no se emitió el .phir"
        proc = subprocess.run(
            [sys.executable, os.path.join(repo, "runtime", "interpreter", "main.py"),
             phir, "--test"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=tmp, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        assert "PASS" in proc.stdout, proc.stdout
        assert "1 pasaron" in proc.stdout, proc.stdout


def test_arbol_binario_completo():
    """La prueba de fuego: BST con inserción, recorrido y búsqueda.

    Los nodos viven en una ARENA (un vector) y se enlazan por índice (-1 =
    ninguno), que es como suriaX guarda un árbol: no hay tipos recursivos por
    valor, y devolver '&n' de un local era un puntero a algo que muere al
    salir de la función (ahora es SEM037, ver el test de abajo)."""
    src = WRITE + """
#import array.vector as vec
struct { int value; int left; int right; } Node;

fn insert(vec.Vector<Node> ptr mutable arena, int root, int v) -> int {
    if (root < 0) {
        arena.push(Node{ value: v, left: -1, right: -1 });
        return arena.len() - 1;
    };
    var Node n = arena.get(root);
    if (v < n.value) {
        n.left = insert(arena, n.left, v);
    } else {
        n.right = insert(arena, n.right, v);
    };
    arena[root] = n;
    return root;
};

fn inorder(vec.Vector<Node> ptr arena, int node) -> void {
    if (node < 0) { return; };
    var Node n = arena.get(node);
    inorder(arena, n.left);
    __write__(f"{n.value} ");
    inorder(arena, n.right);
};

fn main() -> int {
    var vec.Vector<Node> arena = vec.dynamic<Node>(4);
    var int root = -1;
    root = insert(&arena, root, 5);
    root = insert(&arena, root, 3);
    root = insert(&arena, root, 8);
    root = insert(&arena, root, 1);
    root = insert(&arena, root, 9);
    inorder(&arena, root);
    __write__("\\n");
    return 0;
};
"""
    assert_output(src, "1 3 5 8 9")


def test_devolver_la_direccion_de_un_local_es_SEM037():
    """'return &n' con 'n' local: el llamador recibiria un puntero a algo que
    ya no existe. Con un puntero de base (lo apuntado es de otro), no."""
    from helpers import assert_has_code, assert_ok
    assert_has_code("struct { int v; } N;\n"
                    "fn f() -> N ptr { var N n = N{ v: 1 }; return &n; };", "SEM037")
    assert_has_code("struct { int v; } N;\n"
                    "fn f(N n) -> int ptr { return &n.v; };", "SEM037")
    assert_ok("struct { int v; } N;\n"
              "fn f(N ptr mutable p) -> int ptr { return &p.v; };")


def test_metodos_dunder_se_ejecutan_y_mutan():
    """Un 'dunder fn __m__(T ptr mutable self, ...)' se EJECUTA como método
    'x.__m__(...)' en el intérprete, con el receptor por referencia (mutar el
    receptor se propaga al llamante). Foundational de V.0.0.3 (dunders/traits).
    """
    src = WRITE + """
struct { int cur; int max; } Counter;
dunder fn __next__(Counter ptr mutable c) -> int  { c.cur = c.cur + 1; return c.cur; }
dunder fn __done__(Counter ptr c)         -> bool { return c.cur >= c.max; }
fn main() -> int {
    var Counter c = Counter{ cur: 0, max: 3 };
    var int a = c.__next__();
    var int b = c.__next__();
    __write__(f"{a} {b} done={c.__done__()} cur={c.cur}\\n");
    return 0;
};
"""
    assert_output(src, "1 2 done=false cur=2")


def test_metodos_dunder_overload_por_tipo():
    """Dos tipos con un método del MISMO nombre no colisionan: cada dunder se
    despacha por el tipo del receptor (indexado por (owner, nombre))."""
    src = WRITE + """
struct { int x; int y; } Point;
struct { int n; } Box;
dunder fn __sum__(Point ptr p) -> int { return p.x + p.y; }
dunder fn __sum__(Box ptr b)   -> int { return b.n; }
fn main() -> int {
    var Point p = Point{ x: 4, y: 5 };
    var Box b = Box{ n: 99 };
    __write__(f"{p.__sum__()} {b.__sum__()}\\n");
    return 0;
};
"""
    assert_output(src, "9 99")


def test_metodo_impl_sobre_un_campo():
    """Un método '@impl' llamado sobre un CAMPO ('self.buf.push(x)'), no solo
    sobre una variable. Regresión: el owner del receptor (tipo del campo) debe
    canonicalizarse igual que el de una variable para hallar el método."""
    src = WRITE + """
struct { int cur; } Inner;
@impl Inner {
    fn bump(Inner ptr mutable self) -> void { self.cur = self.cur + 1; }
    fn get(Inner ptr self) -> int { return self.cur; }
}
struct { Inner it; } Outer;
@impl Outer {
    fn tick(Outer ptr mutable self) -> void { self.it.bump(); }
    fn read(Outer ptr self) -> int { return self.it.get(); }
}
fn main() -> int {
    var Outer o = Outer{ it: Inner{ cur: 0 } };
    o.tick(); o.tick(); o.tick();
    __write__(f"read={o.read()}\\n");
    return 0;
};
"""
    assert_output(src, "read=3")


def test_impl_metodos_de_nombre_llano():
    """Los métodos de un bloque '@impl' se llaman por su nombre LLANO
    ('c.next()'), no con forma '__x__'."""
    src = WRITE + """
struct { int n; } Cell;
@impl Cell {
    fn set(Cell ptr mutable self, int v) -> void { self.n = v; }
    fn get(Cell ptr self) -> int { return self.n; }
}
fn main() -> int {
    var Cell c = Cell{ n: 0 };
    c.set(42);
    __write__(f"{c.get()}\\n");
    return 0;
};
"""
    assert_output(src, "42")


def test_hook_index_v_de_i():
    """'v[i]' sobre un tipo nominal con hook '__index__' despacha al hook
    (lectura). Funciona sobre una variable y sobre un campo."""
    src = WRITE + """
struct { int base; } Seq;
hook fn __index__(Seq ptr self, int i) -> int { return self.base + i; }
struct { Seq s; } Wrap;
fn main() -> int {
    var Seq q = Seq{ base: 100 };
    var Wrap w = Wrap{ s: q };
    __write__(f"{q[2]} {q[5]} {w.s[3]}\\n");
    return 0;
};
"""
    assert_output(src, "102 105 103")


def test_emit_hir_con_ruta_explicita_crea_su_carpeta():
    """``--emit-hir <ruta>`` escribe aunque el destino no exista todavía.

    Regresión: el volcado con ruta EXPLÍCITA no creaba su directorio (solo lo
    hacía el implícito, ``<dumps_dir>/...``). Como ``dumps/`` no se versiona,
    un clon recién hecho no lo tiene, y compilar así un programa que importa
    una librería reventaba con un ``FileNotFoundError`` sin diagnóstico: el
    emisor de unidades escribe cada ``.libsrx`` en ``<dumps_dir>/<alias>.phir``,
    una ruta explícita, dentro de una carpeta que nadie había creado.
    """
    import subprocess
    import tempfile
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    fuente = 'fn __write__(str s) -> void;\nfn main() -> int { return 0; };\n'
    with tempfile.TemporaryDirectory(prefix="suriax-tests-") as tmp:
        path = os.path.join(tmp, "t.srcx")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(fuente)
        # dos niveles que NO existen: si se creara solo el último seguiría roto
        destino = os.path.join(tmp, "sin", "crear", "t.phir")
        proc = subprocess.run(
            [sys.executable, os.path.join(repo, "V0", "main.py"),
             path, "--emit-hir", destino],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", cwd=tmp, timeout=120,
        )
        assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
        assert os.path.isfile(destino), (
            f"no se escribió el .phir en la ruta pedida:\n{proc.stdout}\n{proc.stderr}")

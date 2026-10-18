"""backend/backend_cpp: cotas, deducción y métodos genéricos en la VM (paso 4).

Lo nuevo del paso 4 es casi todo del frontend: la deducción, las cotas que
se comprueban (``<T: Ord>``) y los métodos genéricos no cambian el HIR —el
genérico se instancia igual—, y la VM los ejecuta como antes.

Lo único que el HIR lleva de nuevo es una llamada que la Semántica comprobó
contra una COTA y no contra un tipo: ``print(x)`` con ``T: Print`` o
``x.area()`` con ``T: Forma``. Viaja como un ``HookRef`` cuyo dueño es el
PARÁMETRO (``T``), igual que ``hash(x)``, y el destino depende de la
instancia. El intérprete la despacha con el tipo del valor; la VM la
RECHAZA al bajar a MIR con ``VM003`` y su posición (antes salía como una
llamada "SIN RESOLVER", sin código), y nunca ejecuta otra cosa.

Se corren con ``SURIAX_HIR_BIN`` apuntando a una VM compilada del
repositorio; sin VM, se omiten diciéndolo.
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
)


def _vm003(phir: str, owner: str) -> str:
    return (f"VM003: '{_cargar(phir).source_file}' llama a algo que promete una "
            f"cota de '{owner}' (un 'print' de 'Print' o un metodo de un "
            "trait): la VM todavia no despacha por el tipo de la instancia. "
            "Ejecutalo con el interprete: python V0/main.py <fuente>.srcx "
            "--run interpreter")


def _rejects(source: str, position: str, owner: str, expected: int) -> None:
    def check(binary, phir, run):
        # el intérprete sí lo ejecuta: el rechazo es de la VM
        assert run.returncode == _codigo_de_proceso(expected), (
            run.stdout, run.stderr)
        checked = _cpp(binary, phir, "--check-mir")
        assert checked.returncode == 1, (checked.stdout, checked.stderr)
        assert f"{position}  {_vm003(phir, owner)}\n" in checked.stderr, checked.stderr
        ran = _cpp(binary, phir, "--run")
        assert ran.returncode == 1, (ran.stdout, ran.stderr)
        assert ran.stdout == "", ran.stdout
    _con_programa(source, check)


def test_vm_rejects_a_trait_method_on_a_bounded_parameter():
    _rejects("@trait struct { fn area(self ptr s) -> int; } Shape;\n"
             "@impl(Shape) struct { int r; } Circle;\n"
             "@impl Circle { fn area(Circle ptr self) -> int { return self.r * 3; } }\n"
             "fn total<T: Shape>(T ptr x) -> int { return x.area(); }\n"
             "fn main() -> int {\n"
             "    var Circle c = Circle{ r: 14 };\n"
             "    return total(&c);\n"
             "}\n",
             "4:45", "T", 42)


def test_vm_rejects_print_on_a_print_bound():
    _rejects("struct { int n; } P;\n"
             "hook fn __print__(P ptr p) -> void { }\n"
             "fn show<T: Print>(T x) -> int { print(x); return 42; }\n"
             "fn main() -> int { return show(P{ n: 1 }); }\n",
             "3:33", "T", 42)


def test_vm_runs_deduction_bounds_and_generic_methods_like_the_interpreter():
    """Lo que no despacha por la instancia corre en la VM igual que en el
    intérprete: una cota ``Ord`` sobre enteros, un argumento de tipo
    deducido y un método genérico con su propio parámetro."""
    source = ("fn smaller<T: Ord>(T a, T b) -> T { if (a < b) { return a; } return b; }\n"
              "struct { int v; } Box<T>;\n"
              "@impl Box<T> {\n"
              "    fn pick<U>(Box<T> ptr self, U other) -> U { return other; }\n"
              "}\n"
              "fn main() -> int {\n"
              "    var Box<int> b = Box<int>{ v: 1 };\n"
              "    return smaller(40, 50) + b.pick(2) + b.pick<int>(0);\n"
              "}\n")

    def check(binary, phir, run):
        assert run.returncode == _codigo_de_proceso(42), (run.stdout, run.stderr)
        ran = _cpp(binary, phir, "--run")
        assert ran.returncode == _codigo_de_proceso(42), (ran.stdout, ran.stderr)
    _con_programa(source, check)

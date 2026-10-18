"""backend/backend_cpp: lambdas (``LambdaExpr``, campo 27 del ``oneof`` de
``Expr``) y ``print(x)`` de un primitivo.

Hoy las dos cosas solo las ejecuta el intérprete. La VM las RECHAZA al bajar
a MIR, con su posición y un código estable, y nunca ejecuta otra cosa:

- una lambda, con ``VM004`` (antes que ``VM001``: su tipo es un
  ``fn(A) -> R``, pero lo que falta es también el marco que lee);
- ``print(5)``, con ``VM005`` (antes salía sin código: "el único nativo que
  baja al MIR es 'len' de una cadena").

Las VISTAS (``--pretty``, ``--summary``, ``--verify``) leen la lambda —su
firma en la línea, su cuerpo debajo con lo que lee— byte-idénticas a las de
Python, que es lo que exige el diferencial entre consumidores.

Lo compartido está en ``backend_cpp_support.py``.
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
    _en_el_path,
)

_LAMBDAS = """\
fn apply(fn(int) -> int f, int v) -> int { return f(v); }

fn main() -> int {
    var int k = 2;
    var int r = apply(lambda (int x) -> int {
        var int y = apply(lambda (int z) -> int: z + k, x);
        return y;
    }, 19);
    return apply(lambda (int x) -> int: x * k, r + 2);
}
"""

_TAIL = ("' usa una lambda: la VM todavia no las ejecuta (ni el valor funcion ni "
         "lo que lee de su entorno). Ejecutalo con el interprete: python "
         "V0/main.py <fuente>.srcx --run interpreter")


def test_the_vm_rejects_a_lambda_with_vm004_at_its_position():
    def check(binary, phir, run):
        # el intérprete sí lo ejecuta: ((19 + 2) + 2) * 2 = 46
        assert run.returncode == _codigo_de_proceso(46), (
            run.stdout, run.stderr)
        source = _cargar(phir).source_file
        checked = _cpp(binary, phir, "--check-mir")
        assert checked.returncode == 1, (checked.stdout, checked.stderr)
        lines = checked.stderr.splitlines()
        # 'apply' recibe un valor funcion (VM001, como siempre); la PRIMERA
        # lambda de 'main' es VM004 y 'main' no sigue bajando
        assert lines[0].startswith("1:1  VM001: "), lines
        assert lines[1] == f"5:23  VM004: '{source}{_TAIL}", lines
        assert len(lines) == 2, lines
        executed = _cpp(binary, phir, "--run")
        assert executed.returncode == 1, (executed.stdout, executed.stderr)
        assert executed.stdout == "", executed.stdout
        assert f"5:23  VM004: '{source}" in executed.stderr, executed.stderr
    _con_programa(_LAMBDAS, check)


def test_the_views_read_a_lambda_like_python():
    def check(binary, phir, _run):
        _en_el_path()
        from src.HIR.pretty import pretty
        from runtime.interpreter.loader import summarize
        module = _cargar(phir)
        view = _cpp(binary, phir, "--pretty")
        assert view.returncode == 0, view.stderr
        assert view.stdout == pretty(module), (
            f"--- Python ---\n{pretty(module)}\n--- C++ ---\n{view.stdout}")
        # que la prueba mire de verdad: la firma en linea, el cuerpo debajo
        # con lo que lee, y la anidada dentro del cuerpo de la otra
        assert "apply(lambda(int x) -> int, 19):int" in view.stdout, view.stdout
        assert "    cuerpo de la lambda  ⟨lee: k⟩" in view.stdout, view.stdout
        assert "        cuerpo de la lambda  ⟨lee: k⟩" in view.stdout, view.stdout
        summary = _cpp(binary, phir, "--summary")
        assert summary.returncode == 0, summary.stderr
        assert summary.stdout == summarize(module) + "\n", summary.stdout
        verified = _cpp(binary, phir, "--verify")
        assert verified.returncode == 0, verified.stderr
    _con_programa(_LAMBDAS, check)


def test_the_vm_rejects_print_of_a_primitive_with_vm005():
    source = ("fn main() -> int {\n"
              "    print(42);\n"
              "    return 7;\n"
              "}\n")

    def check(binary, phir, run):
        # el intérprete escribe '42' (sin salto de línea) y devuelve 7
        assert run.returncode == _codigo_de_proceso(7), (run.stdout, run.stderr)
        assert "42" in run.stdout, run.stdout
        unit = _cargar(phir).source_file
        checked = _cpp(binary, phir, "--check-mir")
        assert checked.returncode == 1, (checked.stdout, checked.stderr)
        assert checked.stderr == (
            f"2:5  VM005: '{unit}' escribe un 'int' con 'print(x)': la VM "
            "todavia no lo ejecuta. Usa un f-string ('stdp.print(f\"{x}\")') o "
            "ejecutalo con el interprete: python V0/main.py <fuente>.srcx --run "
            "interpreter\n"), checked.stderr
        verified = _cpp(binary, phir, "--verify")
        assert verified.returncode == 0, verified.stderr
    _con_programa(source, check)

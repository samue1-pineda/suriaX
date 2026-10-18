"""e2e/element_borrows — el préstamo de un elemento de un contenedor.

``Vector.at``/``at_mut`` prestan el ELEMENTO (``&self.datos[i]``), no la
celda. Si el contenedor lo reemplaza (``set``) o lo saca (``take``), el
préstamo murió con él: es ``RT003``, como en la VM. Antes el intérprete leía
el elemento NUEVO de la misma celda, en silencio.

Si el contenedor crece, reubica su almacenamiento: el mensaje lo dice, en vez
de "se usa después de 'free'" (el programa no escribió ningún ``free``).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import run_source  # noqa: E402

_PROGRESS = ("frontend OK", "HIR (", "  unidad '")


def _run(source: str) -> tuple:
    code, out, err = run_source(source, args=["--run", "interpreter"])
    return code, "".join(l + "\n" for l in out.splitlines()
                         if not l.startswith(_PROGRESS)), err


_HEAD = ("#from io #import stdp\n"
         "#import array.vector as vec\n"
         "struct { int id; } S;\n")


def test_a_borrow_dies_when_set_replaces_its_element():
    code, out, err = _run(_HEAD + """\
fn main() -> int {
    var vec.Vector<S> v = vec.dynamic<S>(2);
    v.push(S{ id: 1 });
    var S ptr p = v.at(0);
    v.set(0, S{ id: 2 });
    stdp.println(f"{p.id}");
    return 0;
}
""")
    assert code == 70, (code, out, err)
    assert out == "", out
    assert "RT003" in err and "(9:21)" in err and "ya no existe" in err, err


def test_a_borrow_dies_when_set_replaces_an_element_with_destructor():
    """El caso de ``c_errorstfix.md``: un elemento con ``__free__``."""
    code, out, err = _run(_HEAD + """\
struct { int id; } R;
hook fn __free__(R ptr r) -> void { stdp.println(f"drop {r.id}"); }
fn main() -> int {
    var vec.Vector<R> v = vec.dynamic<R>(2);
    v.push(R{ id: 1 });
    var R ptr p = v.at(0);
    v.set(0, R{ id: 2 });
    stdp.println(f"{p.id}");
    return 0;
}
""")
    assert code == 70, (code, out, err)
    assert out.startswith("drop 1\n") and "\n2\n" not in "\n" + out, out
    assert "RT003" in err, err


def test_a_borrow_dies_when_take_shifts_the_elements():
    code, out, err = _run(_HEAD + """\
fn main() -> int {
    var vec.Vector<S> v = vec.dynamic<S>(4);
    v.push(S{ id: 1 });
    v.push(S{ id: 2 });
    var S ptr p = v.at(0);
    var S fuera = v.take(0);
    stdp.println(f"{p.id}");
    return 0;
}
""")
    assert code == 70, (code, out, err)
    assert "RT003" in err, err


def test_a_borrow_survives_changes_inside_its_element():
    """Lo que NO cambia: modificar el elemento prestado (sus campos, o el
    vector que es el elemento) no lo reemplaza, y el préstamo sigue vivo."""
    code, out, err = _run(_HEAD + """\
fn main() -> int {
    var vec.Vector<S> v = vec.dynamic<S>(2);
    v.push(S{ id: 1 });
    var S ptr mutable p = v.at_mut(0);
    p.id = 5;
    v.at_mut(0).id = 6;
    stdp.println(f"{p.id} {v[0].id}");
    var int x = 1;
    var int ptr mutable q = &x;
    x = 7;
    stdp.println(f"{q[0]}");
    return 0;
}
""")
    assert code == 0, (code, out, err)
    assert out == "6 6\n7\n", out


def test_a_dangling_borrow_after_growth_says_the_container_moved():
    code, out, err = _run(_HEAD + """\
fn main() -> int {
    var vec.Vector<S> v = vec.dynamic<S>(1);
    v.push(S{ id: 1 });
    var S ptr mutable p = v.at_mut(0);
    v.push(S{ id: 2 });
    p.id = 6;
    return 0;
}
""")
    assert code == 70, (code, out, err)
    assert "RT003" in err and "(9:5)" in err, err
    assert "reubicara su almacenamiento" in err and "después de 'free'" not in err, err


def test_a_real_free_keeps_its_message():
    code, out, err = _run("""\
fn main() -> int {
    var int a = 1;
    var int ptr mutable p = &a;
    free p;
    var int b = a;
    return b;
}
""")
    assert code == 70, (code, out, err)
    assert "RT003" in err and "después de 'free'" in err, err

"""backend/backend_cpp: desenvolver un ``T?`` y los enums genéricos (paso 3).

Hoy solo los ejecuta el intérprete. La VM los RECHAZA con ``VM002`` al bajar
a MIR, con su posición, y nunca ejecuta otra cosa:

- ``case v`` sobre un ``T?`` (``CaseArm.binds``): leído sin el campo sería
  comparar con un slot ``v`` sin valor, y la rama no entraría nunca;
- una variante (``case E.A(x)``, ``case E.Nada`` de un enum suma) sobre un
  sujeto ``E?``: tendría que saltarse el null antes de leer la etiqueta;
- ``x ?? d`` (``BinaryOp`` con ``op == "??"``);
- un enum GENÉRICO (``EnumDecl.type_params``): su payload ``T`` se bajaría
  sin sustituir. Se rechaza donde se declara, en cualquier unidad cargada.

``suri --run compiler`` consulta ``--check-mir`` y entonces lo ejecuta el
intérprete (con un aviso), que es el oráculo de estas pruebas.

NOTA: estas pruebas se escribieron SIN compilar la VM (carril S3: "no
compiles la VM"); el código C++ del rechazo (``backend/src/mir.cpp``) no se
ejecutó nunca. Lo compartido está en ``backend_cpp_support.py``.
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

_TAIL = (": la VM todavia no lo ejecuta. Ejecutalo con el interprete: "
         "python V0/main.py <fuente>.srcx --run interpreter")


def _vm002(phir: str, what: str) -> str:
    return f"VM002: '{_cargar(phir).source_file}' {what}" + _TAIL


def _rechaza(fuente: str, linea: str, what: str, esperado: int) -> None:
    def comprobar(binario, phir, corrida):
        # el intérprete sí lo ejecuta: el rechazo es de la VM
        assert corrida.returncode == _codigo_de_proceso(esperado), (
            corrida.stdout, corrida.stderr)
        comprobado = _cpp(binario, phir, "--check-mir")
        assert comprobado.returncode == 1, (comprobado.stdout, comprobado.stderr)
        assert f"{linea}  {_vm002(phir, what)}\n" in comprobado.stderr, comprobado.stderr
        corrido = _cpp(binario, phir, "--run")
        assert corrido.returncode == 1, (corrido.stdout, corrido.stderr)
        assert corrido.stdout == "", corrido.stdout
    _con_programa(fuente, comprobar)


def test_la_vm_rechaza_case_v_sobre_un_opcional():
    _rechaza("struct { int n; } S;\n"
             "fn f(S? x) -> int {\n"
             "    match (x) {\n"
             "        case null { return 0; }\n"
             "        case v { return v.n; }\n"
             "    };\n"
             "    return 1;\n"
             "}\n"
             "fn main() -> int { return f(S{ n: 42 }); }\n",
             "5:14", "desenvuelve un 'T?' con 'case v'", 42)


def test_la_vm_rechaza_una_variante_sobre_un_enum_opcional():
    _rechaza("enum Forma { Circulo(int), Nada };\n"
             "fn f(Forma? x) -> int {\n"
             "    match (x) {\n"
             "        case null { return 0; }\n"
             "        case Forma.Circulo(r) { return r; }\n"
             "        case Forma.Nada { return 1; }\n"
             "    };\n"
             "    return 2;\n"
             "}\n"
             "fn main() -> int { return f(Forma.Circulo(42)); }\n",
             "5:14", "compara una variante con un sujeto 'E?'", 42)


def test_la_vm_rechaza_el_operador_null_coalesce():
    _rechaza("struct { int n; } S;\n"
             "fn f(S? x) -> int {\n"
             "    var S d = S{ n: 42 };\n"
             "    var S r = x ?? d;\n"
             "    return r.n;\n"
             "}\n"
             "fn main() -> int { return f(null); }\n",
             "4:15", "desenvuelve un 'T?' con '??'", 42)


def test_la_vm_rechaza_un_enum_generico_donde_se_declara():
    _rechaza("enum Res<T, E> { Ok(T), Err(E) };\n"
             "fn main() -> int {\n"
             "    var Res<int, str> r = Res<int, str>.Ok(42);\n"
             "    match (r) {\n"
             "        case Res<int, str>.Ok(v) { return v; }\n"
             "        case Res<int, str>.Err(m) { return 1; }\n"
             "    };\n"
             "    return 2;\n"
             "}\n",
             "1:1", "declara el enum generico 'Res'", 42)


def test_un_match_sobre_un_opcional_con_case_null_sigue_corriendo():
    """Lo que ya bajaba (comparar un ``S?`` con ``null``) no se rechaza."""
    fuente = ("struct { int n; } S;\n"
              "fn f(S? x) -> int {\n"
              "    match (x) {\n"
              "        case null { return 42; }\n"
              "    };\n"
              "    return 1;\n"
              "}\n"
              "fn main() -> int { return f(null); }\n")

    def comprobar(binario, phir, corrida):
        assert corrida.returncode == _codigo_de_proceso(42), corrida.stderr
        comprobado = _cpp(binario, phir, "--check-mir")
        assert "VM002" not in comprobado.stderr, comprobado.stderr
    _con_programa(fuente, comprobar)

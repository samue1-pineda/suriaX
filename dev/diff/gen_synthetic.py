#!/usr/bin/env python3
"""Genera los programas SINTÉTICOS del diferencial (dev/diff).

Escribe ``programs/06_sintetico_<N>.srcx`` para N = 10, 1000 y 10000
sentencias (o las que se pidan con ``--sizes``). Es DETERMINISTA: la misma
semilla y el mismo N dan el mismo archivo byte a byte, en cualquier máquina
(``random.Random`` con semilla entera es estable entre versiones de Python 3).

Qué cuenta como "sentencia": cada sentencia que el generador escribe en
``main`` y en las funciones ``block_<k>`` (declaración, asignación, llamada
suelta, ``println``, ``if``, ``while``, ``match`` y ``return``; un ``if``,
``while`` o ``match`` cuenta 1 más las sentencias de su cuerpo). Las
funciones auxiliares fijas de la cabecera (``mix``, ``half``, ``label``,
``letter``, ``pick``, ``color_code``, ``is_small``) NO cuentan: son las
mismas en los tres tamaños y su número se escribe en el comentario de
cabecera del programa.

Qué varía: tipos (int, float, bool, str, char y un enum sin datos),
aritmética (+ - * / %), comparaciones, ``and``/``not``, ``if``/``else``,
``while``, llamadas, ``match`` sobre el enum y ``println`` con f-strings de
los cinco tipos (para que comparar salidas signifique algo).

Qué NO usa, a propósito (medido: el target web lo rechaza hoy):
  - structs: WEB100/WEB101 ("un struct o un puntero, no");
  - comparar dos valores de enum con '==' (WEB101 "el operando es de tipo
    'Color'"); se usa 'match' en su lugar;
  - 'cast<int>' de un float (fuera de rango es UB en C++ y trap en wasm: no
    sería determinista entre targets).
Los divisores son siempre constantes positivas (2..9): nunca hay división por
cero ni 'MIN / -1' (que en wasm atrapa; ver el programa 08).

Uso:
    python dev/diff/gen_synthetic.py                 # 10, 1000 y 10000
    python dev/diff/gen_synthetic.py --sizes 50 --seed 7 --out /tmp/x
"""

from __future__ import annotations

import argparse
import os
import random

DEFAULT_SEED = 20261017
DEFAULT_SIZES = (10, 1000, 10000)
#: sentencias por función 'block_<k>' (aprox.): repartir evita una sola
#: función gigante, que no es lo que escribe nadie y castiga a los backends
#: por una razón que no interesa aquí.
STATEMENTS_PER_BLOCK = 40

HEADER = """\
// Programa SINTÉTICO generado por dev/diff/gen_synthetic.py — NO editar a mano.
// semilla={seed}  sentencias={n}  (más {helpers} sentencias de las funciones
// auxiliares fijas, que no cuentan). Regenerar:
//   python dev/diff/gen_synthetic.py --seed {seed} --sizes {n}
#from io #import stdp

enum Color {{ ROJO, VERDE, AZUL, NEGRO }};

fn mix(int a, int b) -> int {{
    return (a * 31 + b) % 1000003;
}}

fn half(float x) -> float {{
    return x / 2.0;
}}

fn label(int n) -> str {{
    if (n % 2 == 0) {{
        return "par";
    }}
    return "impar";
}}

fn letter(int n) -> char {{
    if (n % 3 == 0) {{
        return 'x';
    }}
    return 'y';
}}

fn pick(int n) -> Color {{
    var int r = n % 4;
    if (r < 0) {{
        r = 0 - r;
    }}
    if (r == 0) {{
        return Color.ROJO;
    }}
    if (r == 1) {{
        return Color.VERDE;
    }}
    if (r == 2) {{
        return Color.AZUL;
    }}
    return Color.NEGRO;
}}

fn color_code(Color c) -> int {{
    match (c) {{
        case Color.ROJO: {{ return 10; }}
        case Color.VERDE: {{ return 20; }}
        case Color.AZUL: {{ return 30; }}
        case Color.NEGRO: {{ return 40; }}
    }}
    return 0;
}}

fn is_small(int n) -> bool {{
    return n < 500 and n > -500;
}}
"""

COLORS = ("ROJO", "VERDE", "AZUL", "NEGRO")
LETTERS = "abcdefghijklmnopqrstuvwxyz"
WORDS = ("alfa", "beta", "gamma", "delta", "eps", "zeta", "eta", "theta")


class Block:
    """Genera el cuerpo de una función 'block_<k>' con un presupuesto exacto
    de sentencias. Lleva las variables vivas por tipo para que cada
    expresión use solo lo que ya está declarado."""

    def __init__(self, rng: random.Random, index: int, budget: int) -> None:
        self.rng = rng
        self.k = index
        self.budget = budget          # sentencias que quedan por escribir
        self.lines: list[str] = []
        self.vars: dict[str, list[str]] = {
            "int": [], "float": [], "bool": [], "str": [], "char": [], "Color": []}
        self.counter = 0

    # --- utilidades --------------------------------------------------------
    def fresh(self, kind: str) -> str:
        prefix = {"int": "i", "float": "f", "bool": "b", "str": "s",
                  "char": "c", "Color": "k"}[kind]
        name = f"{prefix}{self.counter}"
        self.counter += 1
        return name

    def emit(self, text: str, indent: int = 1) -> None:
        self.lines.append("    " * indent + text)

    def some(self, kind: str) -> str:
        return self.rng.choice(self.vars[kind])

    def int_atom(self) -> str:
        if self.vars["int"] and self.rng.random() < 0.75:
            return self.some("int")
        value = self.rng.randint(-50, 99)
        return str(value) if value >= 0 else f"({value})"

    def int_expr(self) -> str:
        r = self.rng
        a, b = self.int_atom(), self.int_atom()
        shape = r.randrange(6)
        if shape == 0:
            return f"{a} + {b} * {r.randint(2, 9)}"
        if shape == 1:
            return f"({a} - {b}) * {r.randint(2, 9)}"
        if shape == 2:
            return f"{a} / {r.randint(2, 9)} + {b}"
        if shape == 3:
            return f"({a} + {b}) % {r.randint(2, 9)}"
        if shape == 4:
            return f"mix({a}, {b})"
        return f"{a} * {b} - {r.randint(0, 99)}"

    def float_atom(self) -> str:
        r = self.rng
        if self.vars["float"] and r.random() < 0.6:
            return self.some("float")
        if self.vars["int"] and r.random() < 0.5:
            return f"cast<float>({self.some('int')} % 1000)"
        return f"{r.randint(0, 99)}.{r.choice(('0', '25', '5', '75', '1', '3'))}"

    def float_expr(self) -> str:
        r = self.rng
        a, b = self.float_atom(), self.float_atom()
        shape = r.randrange(4)
        if shape == 0:
            return f"{a} + {b}"
        if shape == 1:
            return f"{a} * 0.5 - {b}"
        if shape == 2:
            return f"{a} / {r.randint(2, 9)}.0"
        return f"half({a}) + 1.25"

    def bool_expr(self) -> str:
        r = self.rng
        shape = r.randrange(5)
        if shape == 0 or not self.vars["float"]:
            return f"{self.int_atom()} < {self.int_atom()}"
        if shape == 1:
            return f"{self.float_atom()} >= {self.float_atom()}"
        if shape == 2:
            return f"is_small({self.int_atom()})"
        if shape == 3 and self.vars["bool"]:
            return f"{self.some('bool')} and not ({self.int_atom()} == {self.int_atom()})"
        if self.vars["char"]:
            return f"{self.some('char')} < '{r.choice(LETTERS)}'"
        return f"{self.int_atom()} != {self.int_atom()}"

    # --- sentencias --------------------------------------------------------
    def declare(self, kind: str, indent: int = 1) -> None:
        r = self.rng
        name = self.fresh(kind)
        if kind == "int":
            value = self.int_expr()
        elif kind == "float":
            value = self.float_expr()
        elif kind == "bool":
            value = self.bool_expr()
        elif kind == "str":
            value = (f"label({self.int_atom()})" if r.random() < 0.5
                     else f'"{r.choice(WORDS)}"')
        elif kind == "char":
            value = (f"letter({self.int_atom()})" if r.random() < 0.5
                     else f"'{r.choice(LETTERS)}'")
        else:
            value = (f"pick({self.int_atom()})" if r.random() < 0.6
                     else f"Color.{r.choice(COLORS)}")
        self.emit(f"var {kind} {name} = {value};", indent)
        if indent == 1:          # lo declarado dentro de un bloque no sale de él
            self.vars[kind].append(name)
        self.budget -= 1

    def assign(self, indent: int = 1) -> None:
        r = self.rng
        if self.vars["float"] and r.random() < 0.3:
            name = self.some("float")
            self.emit(f"{name} = {self.float_expr()};", indent)
        else:
            name = self.some("int")
            self.emit(f"{name} = {name} % {r.randint(50, 997)} + {self.int_atom()};", indent)
        self.budget -= 1

    def println(self, indent: int = 1) -> None:
        r = self.rng
        parts = []
        alive = [k for k in ("int", "float", "bool", "str", "char") if self.vars[k]]
        for kind in r.sample(alive, min(3, len(alive))):
            name = self.some(kind)
            parts.append(f"{name}={{{name}}}")
        if not parts:
            parts.append(f"i={{{self.int_atom()}}}")
        self.emit(f'stdp.println(f"b{self.k} ' + " ".join(parts) + '");', indent)
        self.budget -= 1

    def if_stmt(self) -> None:
        # 1 (el if) + 1 en el then + 1 en el else = 3
        target = self.some("int")
        self.emit(f"if ({self.bool_expr()}) {{")
        self.emit(f"{target} = {target} + {self.int_atom()};", 2)
        self.emit("} else {")
        self.emit(f"{target} = {target} - {self.rng.randint(1, 9)};", 2)
        self.emit("}")
        self.budget -= 3

    def while_stmt(self) -> None:
        # var del contador (1) + while (1) + 2 dentro = 4
        r = self.rng
        counter = self.fresh("int")
        acc = self.some("int")
        self.emit(f"var int {counter} = 0;")
        self.emit(f"while ({counter} < {r.randint(2, 8)}) {{")
        self.emit(f"{acc} = {acc} + {counter} * {r.randint(1, 9)};", 2)
        self.emit(f"{counter} = {counter} + 1;", 2)
        self.emit("}")
        self.vars["int"].append(counter)
        self.budget -= 4

    def match_stmt(self) -> None:
        # match (1) + 4 casos con una sentencia cada uno = 5
        if not self.vars["Color"]:
            self.declare("Color")
            return
        color = self.some("Color")
        target = self.some("int")
        self.emit(f"match ({color}) {{")
        for name in COLORS:
            self.emit(f"case Color.{name}: {{ {target} = {target} + "
                      f"color_code(Color.{name}) + {self.rng.randint(0, 9)}; }}", 2)
        self.emit("}")
        self.budget -= 5

    def call_stmt(self) -> None:
        name = self.fresh("int")
        self.emit(f"var int {name} = mix({self.int_atom()}, {self.int_atom()}) + "
                  f"color_code(pick({self.int_atom()}));")
        self.vars["int"].append(name)
        self.budget -= 1

    def generate(self) -> list[str]:
        r = self.rng
        # siempre: la primera variable (de la semilla) y, al final, un
        # println y el return. Son 3 sentencias del presupuesto.
        self.emit(f"var int i{self.counter} = seed % 1000 + {r.randint(1, 99)};")
        self.vars["int"].append(f"i{self.counter}")
        self.counter += 1
        self.budget -= 1
        reserve = 2
        while self.budget > reserve:
            room = self.budget - reserve
            choices = [("decl", 30), ("assign", 12), ("print", 14), ("call", 8)]
            if room >= 3:
                choices.append(("if", 12))
            if room >= 4:
                choices.append(("while", 8))
            if room >= 5:
                choices.append(("match", 8))
            kind = r.choices([c for c, _ in choices], [w for _, w in choices])[0]
            if kind == "decl":
                self.declare(r.choice(("int", "int", "float", "bool", "str", "char", "Color")))
            elif kind == "assign":
                self.assign()
            elif kind == "print":
                self.println()
            elif kind == "call":
                self.call_stmt()
            elif kind == "if":
                self.if_stmt()
            elif kind == "while":
                self.while_stmt()
            else:
                self.match_stmt()
        self.println()
        result = self.vars["int"][-1]
        self.emit(f"return {result};")
        self.budget -= 1
        assert self.budget == 0, self.budget
        return [f"fn block_{self.k}(int seed) -> int {{", *self.lines, "}", ""]


def generate(n: int, seed: int) -> str:
    """El programa de ``n`` sentencias (exactas) para la semilla ``seed``."""
    if n < 7:
        raise ValueError("hace falta n >= 7 (main 4 + un bloque de 3)")
    rng = random.Random(seed * 1_000_003 + n)
    blocks = max(1, round(n / (STATEMENTS_PER_BLOCK + 1)))
    main_statements = blocks + 3          # var total, B llamadas, println, return
    rest = n - main_statements
    sizes = [rest // blocks] * blocks
    for i in range(rest % blocks):
        sizes[i] += 1
    out = [HEADER.format(seed=seed, n=n, helpers=helper_statements())]
    for k, size in enumerate(sizes):
        out.extend(Block(rng, k, size).generate())
    out.append("fn main() -> int {")
    out.append("    var int total = 0;")
    for k in range(blocks):
        out.append(f"    total = mix(total, block_{k}(total));")
    out.append('    stdp.println(f"total = {total}");')
    out.append("    return 0;")
    out.append("}")
    return "\n".join(out) + "\n"


def helper_statements() -> int:
    """Sentencias de las funciones auxiliares fijas de HEADER, contadas con
    la misma regla que :func:`count_statements`."""
    return count_statements(HEADER.format(seed=0, n=0, helpers=0), prefixes=("fn ",))


def count_statements(source: str, prefixes: tuple = ("fn block_", "fn main")) -> int:
    """Cuenta las sentencias de 'main' y de los 'block_<k>' de un programa
    generado (verificación independiente del presupuesto): cada línea que
    termina en ';' o abre un if/while/match, más un caso 'case ...: { ...; }'
    por línea. Solo vale para el formato que escribe este generador."""
    count = 0
    inside = False
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefixes):
            inside = True
            continue
        if stripped.startswith("fn "):
            inside = False
            continue
        if not inside or not stripped or stripped in ("}", "} else {"):
            continue
        count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--sizes", type=int, nargs="+", default=list(DEFAULT_SIZES))
    parser.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "programs"))
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for n in args.sizes:
        source = generate(n, args.seed)
        counted = count_statements(source)
        assert counted == n, f"N={n}: el contador independiente da {counted}"
        path = os.path.join(args.out, f"06_sintetico_{n}.srcx")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(source)
        print(f"{path}: {n} sentencias, {len(source.encode())} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

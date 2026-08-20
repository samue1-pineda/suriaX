#!/usr/bin/env python3
"""Banco de medida del HIR: tiempo, tamaño y desglose de bytes.

No es un test (no falla ni pasa): es el instrumento con el que se decide si
una optimización del emisor sirve. Existe porque la primera ronda de la
etapa 1 (``docs/plan_hir_v2.md``) llegó a la conclusión CONTRARIA a la del
perfil — ``cProfile`` penaliza el código con muchas llamadas diminutas, que
es exactamente lo que hace el emisor, y tres optimizaciones "obvias"
resultaron ser pérdidas de entre el 5 % y el 14 % al medirlas con reloj.

Uso::

    python dev/bench_hir.py                  # corpus del repo + sintéticos
    python dev/bench_hir.py archivo.srcx     # un archivo concreto

Lo que imprime, por unidad: tiempo de emisión, de serialización, de
re-parseo (lo que paga el lector) y de la vista de texto, el tamaño del
``.phir`` y en qué se van sus bytes (tipos, cadenas, posiciones), con el
factor de repetición de cada partida — que es lo que justifica o descarta un
*pool* en el esquema.
"""
from __future__ import annotations

import os
import sys
import time

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path[:0] = [os.path.join(_REPO, "V0"), _REPO]

from google.protobuf.descriptor import FieldDescriptor as FD  # noqa: E402
from src.frontend.lexer import source_reader  # noqa: E402
from src.frontend.lexer.lexer import Lexer  # noqa: E402
from src.frontend.parser.parser import Parser  # noqa: E402
from src.frontend.parser.typed_ast import resolve_types  # noqa: E402
from src.frontend.semantic import analyze  # noqa: E402
from src.HIR.emmit_IR import build_module, module_to_text, serialize  # noqa: E402
from src.HIR.stubs import load_hir_pb2  # noqa: E402

pb = load_hir_pb2()


# --------------------------------------------------------------------------- #
# programas sintéticos: el repo no tiene fuentes grandes, y el coste del
# emisor solo se ve cuando el árbol es grande (es lineal en nodos).
# --------------------------------------------------------------------------- #
def generate(n_structs: int, n_funcs: int, *, imports: bool = False) -> str:
    out = ["#from io #import stdp", ""] if imports else []
    for i in range(n_structs):
        out.append(f"struct {{ int x; int y; float peso; bool activo; }} T{i};")
    out.append("")
    for i in range(n_funcs):
        prev = f"f{i - 1}(a, b)" if i else "a + b"
        owner = i % max(n_structs, 1)
        out.append(f"""
fn f{i}(int a, int b) -> int {{
    var int acc = 0;
    var int j = 0;
    while (j < b) {{
        acc = acc + a * j - (b / 2);
        if (acc > 100) {{ acc = acc - 100; }} else {{ acc = acc + 1; }}
        j = j + 1;
    }}
    var T{owner} p = T{owner}{{ x: acc, y: b, peso: 1.5, activo: true }};
    return acc + p.x + ({prev});
}}""")
    out.append("\nfn main() -> int {")
    out.append("    var int total = 0;")
    for i in range(min(n_funcs, 50)):
        out.append(f"    total = total + f{i}(2, 3);")
    if imports:
        out.append('    stdp.println("listo");')
    out.append("    return 0;\n}")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# desglose: en qué se van los bytes del artefacto
# --------------------------------------------------------------------------- #
def _is_repeated(val) -> bool:
    return hasattr(val, "__len__") and not hasattr(val, "ListFields")


def breakdown(module) -> dict:
    tipos = [0, 0]
    cadenas = [0, 0]
    posiciones = [0, 0]
    uniq_tipos: set[bytes] = set()
    uniq_cadenas: set[str] = set()

    def walk_type(t) -> None:
        tipos[0] += 1
        # + 2 del tag y la longitud que paga el contenedor en cada aparición
        tipos[1] += t.ByteSize() + 2
        uniq_tipos.add(t.SerializeToString())
        if t.HasField("inner"):
            walk_type(t.inner)

    def rec(msg) -> None:
        for fd, val in msg.ListFields():
            if fd.type == FD.TYPE_STRING:
                for s in (val if _is_repeated(val) else [val]):
                    uniq_cadenas.add(s)
                    cadenas[0] += 1
                    cadenas[1] += len(s.encode()) + 2
                continue
            if fd.type == FD.TYPE_UINT32 and fd.name in ("ln", "col"):
                posiciones[0] += 1
                posiciones[1] += 1 + max(1, (val.bit_length() + 6) // 7)
                continue
            if fd.type != FD.TYPE_MESSAGE:
                continue
            if fd.message_type.GetOptions().map_entry:
                if fd.message_type.fields_by_name["value"].type != FD.TYPE_MESSAGE:
                    continue
                items = list(val.values())
            else:
                items = list(val) if _is_repeated(val) else [val]
            for it in items:
                walk_type(it) if fd.message_type.name == "Type" else rec(it)

    rec(module)
    return {"tipos": tipos, "tipos_uniq": len(uniq_tipos),
            "cadenas": cadenas, "cadenas_uniq": len(uniq_cadenas),
            "pos": posiciones}


# --------------------------------------------------------------------------- #
# una medición
# --------------------------------------------------------------------------- #
def measure(label: str, path: str, *, repeats: int = 5) -> None:
    source = source_reader.read_file(path)
    tokens = Lexer(source, file=path).tokenize()
    program = Parser(tokens).parse()
    resolve_types(program)
    libraries: dict = {}
    table, errors = analyze(program, source_path=path, config=None,
                            libraries=libraries)
    if errors:
        print(f"\n=== {label}: errores del frontend {[e.code for e in errors][:3]}")
        return

    mejor_emit = mejor_ser = mejor_parse = float("inf")
    data = b""
    for _ in range(repeats):
        t = time.perf_counter()
        module, hir_errors = build_module(program, table, source_file=path,
                                          libraries=libraries)
        mejor_emit = min(mejor_emit, time.perf_counter() - t)
        if hir_errors:
            print(f"\n=== {label}: errores HIR {[e.code for e in hir_errors][:3]}")
            return
        t = time.perf_counter()
        data = serialize(module)
        mejor_ser = min(mejor_ser, time.perf_counter() - t)
        t = time.perf_counter()
        pb.Module().ParseFromString(data)
        mejor_parse = min(mejor_parse, time.perf_counter() - t)

    t = time.perf_counter()
    text = module_to_text(module)
    t_text = time.perf_counter() - t

    b = breakdown(module)
    total = len(data)
    pct = lambda n: 100 * n / total  # noqa: E731
    print(f"\n=== {label}  ({len(tokens)} tokens, {len(program.items)} items) ===")
    print(f"  emitir        {mejor_emit * 1000:8.2f} ms")
    print(f"  serializar    {mejor_ser * 1000:8.2f} ms")
    print(f"  re-parsear    {mejor_parse * 1000:8.2f} ms   (lo que paga el lector)")
    print(f"  texto         {t_text * 1000:8.2f} ms   ({len(text)} chars)")
    print(f"  .phir         {total} bytes")
    print(f"     symbols    {module.symbols.ByteSize():8d} B ({pct(module.symbols.ByteSize()):5.1f}%)")
    print(f"     Type       {b['tipos'][1]:8d} B ({pct(b['tipos'][1]):5.1f}%)  "
          f"{b['tipos'][0]} msgs / {b['tipos_uniq']} distintos "
          f"= {b['tipos'][0] / max(b['tipos_uniq'], 1):.0f}x")
    print(f"     cadenas    {b['cadenas'][1]:8d} B ({pct(b['cadenas'][1]):5.1f}%)  "
          f"{b['cadenas'][0]} campos / {b['cadenas_uniq']} distintas "
          f"= {b['cadenas'][0] / max(b['cadenas_uniq'], 1):.0f}x")
    print(f"     ln/col     {b['pos'][1]:8d} B ({pct(b['pos'][1]):5.1f}%)  "
          f"{b['pos'][0]} campos")


def main(argv: list[str]) -> int:
    import tempfile

    if len(argv) > 1:
        for path in argv[1:]:
            measure(os.path.basename(path), os.path.abspath(path))
        return 0

    for rel in ("a.srcx", "test/web/fixtures/prog.srcx", "lib/io/stdp.libsrx"):
        path = os.path.join(_REPO, rel)
        if os.path.isfile(path):
            measure(rel, path)

    with tempfile.TemporaryDirectory(prefix="suriax-bench-") as tmp:
        for structs, funcs in ((10, 50), (40, 400)):
            path = os.path.join(tmp, f"gen_{structs}_{funcs}.srcx")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(generate(structs, funcs))
            measure(f"sintetico {structs} structs / {funcs} fns", path, repeats=3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

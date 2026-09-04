"""El PROTOTIPO C++ que ``logic_dir`` tendrá que implementar.

Un hook declarado con ``@signature_extends(cxx=True, logic="win_open_cpp")``
promete que existirá un símbolo nativo llamado ``win_open_cpp``. Este módulo
escribe su declaración en C++ a partir de la firma del lenguaje, para que el
contrato exista **en un solo sitio**: si la firma cambia, el prototipo se
regenera y el compilador de C++ se queja donde toca — en la implementación —
en vez de fallar al ligar.

Alcance deliberado: **solo la declaración**. No genera marshalling, ni
registro, ni glue de build. Ligar el símbolo al despacho pertenece a la
VM+JIT, que todavía no existe (ver ``htims/readme.md``, *Qué falta*);
adelantar esa infraestructura sería construir contra un consumidor imaginario.

``extern "C"`` no es cosmético: quien busque el símbolo lo hará por su
nombre, y el mangling de C++ lo cambia según la firma.

    python -m htims.utils.cxx extensions/calls/ > extensions/logic/hooks.h
"""

from __future__ import annotations

import sys
from typing import List, Optional, Sequence, Tuple

from ..declarations import HookDecl

#: Tipo del lenguaje -> tipo de C++.
#:
#: ``char`` es ``char32_t`` porque un ``char`` de suriaX es UN code point
#: Unicode, no un byte; ``int`` es de 64 bits por definición del lenguaje.
#: ``str`` NO está: su representación en C++ todavía no se ha decidido (el
#: intérprete usa una cadena de Python, el target web un índice de constante)
#: y elegirla aquí sería fijar por la puerta de atrás una decisión del
#: lenguaje. Mientras no se decida, se reporta.
_PRIMITIVOS = {
    "int": "int64_t",
    "float": "double",
    "bool": "bool",
    "char": "char32_t",
    "void": "void",
}


def cxx_type(tipo: str) -> Tuple[Optional[str], Optional[str]]:
    """Un tipo del lenguaje -> ``(tipo C++, None)`` o ``(None, motivo)``.

    Devuelve el motivo en vez de lanzar, y en vez de inventar: un tipo sin
    representación decidida tiene que verse, no convertirse en algo plausible.
    """
    texto = tipo.strip()
    if not texto:
        return None, "tipo vacío"

    # POSTFIJO, como se escribe en el lenguaje: 'Body ptr mutable'.
    if texto.endswith(" ptr mutable"):
        base, motivo = cxx_type(texto[: -len(" ptr mutable")])
        return (None, motivo) if base is None else (f"{base}*", None)
    if texto.endswith(" ptr"):
        base, motivo = cxx_type(texto[: -len(" ptr")])
        # sin 'mutable' el hook solo puede LEER: el 'const' lo hace cumplir
        # también del lado de C++, que es la mitad que el compilador de
        # suriaX no puede vigilar.
        return (None, motivo) if base is None else (f"const {base}*", None)

    if texto == "str":
        return None, ("'str' no tiene todavía una representación decidida en "
                      "C++; pásalo como puntero a un tipo tuyo o espera a que "
                      "el lenguaje la fije")
    if texto.endswith("?"):
        return None, ("'" + texto + "' es nullable: su representación en C++ "
                      "depende de cómo viaje el nulo, que aún no está fijado")
    if texto.startswith("error"):
        return None, ("'" + texto + "' es un retorno que puede fallar; el "
                      "acarreo del error a C++ aún no está fijado")
    if "<" in texto:
        return None, ("'" + texto + "' es genérico: C++ necesitaría una "
                      "instanciación concreta")

    if texto in _PRIMITIVOS:
        return _PRIMITIVOS[texto], None
    if texto.isidentifier():
        # nominal del usuario: es SU tipo, y lo declara él en logic_dir.
        return texto, None
    return None, f"'{texto}' no es un tipo del lenguaje que se pueda traducir"


def prototype(decl: HookDecl) -> Tuple[Optional[str], List[str]]:
    """La línea C++ de un hook, o los motivos por los que no se puede."""
    problemas: List[str] = []
    retorno, motivo = cxx_type(decl.returns)
    if motivo is not None:
        problemas.append(f"retorno de '{decl.name}': {motivo}")
    params: List[str] = []
    for indice, tipo in enumerate(decl.params, start=1):
        rendido, motivo = cxx_type(tipo)
        if motivo is not None:
            problemas.append(f"parámetro {indice} de '{decl.name}': {motivo}")
        else:
            params.append(f"{rendido} arg{indice}")
    if problemas:
        return None, problemas
    firma = ", ".join(params) if params else "void"
    return f"{retorno} {decl.logic}({firma});", []


def header(decls: Sequence[HookDecl], *, guard: str = "SURIAX_HOOKS_H"
           ) -> Tuple[str, List[str]]:
    """La cabecera completa, y los hooks que no se pudieron traducir.

    Solo entran los declarados con ``cxx=True``: los demás se resuelven
    dentro del lenguaje y no tienen símbolo nativo que declarar.
    """
    problemas: List[str] = []
    cuerpo: List[str] = []
    for decl in sorted(decls, key=lambda d: (d.owner, d.name)):
        if not decl.cxx:
            continue
        linea, fallos = prototype(decl)
        problemas.extend(fallos)
        if linea is None:
            continue
        cuerpo.append(f"    // {decl.owner}.{decl.name}  "
                      f"({decl.module}.py:{decl.line})")
        cuerpo.append(f"    {linea}")

    texto = [
        "// Generado por suriaX (htims.utils.cxx): los hooks que tu proyecto",
        "// declara con '@signature_extends(cxx=True)'.",
        "//",
        "// No se edita a mano: la firma vive en el .py que la declara, y este",
        "// archivo se regenera desde ella.",
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        "#include <cstdint>",
        "",
        'extern "C" {',
        "",
    ]
    texto.extend(cuerpo if cuerpo else
                 ["    // (ninguna firma declara cxx=True)"])
    texto.extend(["", "}  // extern \"C\"", "", f"#endif  // {guard}", ""])
    return "\n".join(texto), problemas


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m htims.utils.cxx <ruta>...`` -> la cabecera por stdout."""
    from .check import check

    rutas = list(argv if argv is not None else sys.argv[1:])
    if not rutas:
        print("uso: python -m htims.utils.cxx <ruta>...", file=sys.stderr)
        return 2
    decls, errores = check(*rutas)
    for problema in errores:
        print(f"{problema.code} {problema.loc.strformat()} {problema.message}",
              file=sys.stderr)
    if errores:
        return 1
    texto, problemas = header(decls)
    for motivo in problemas:
        print(f"sin prototipo: {motivo}", file=sys.stderr)
    print(texto)
    return 1 if problemas else 0


if __name__ == "__main__":  # pragma: no cover - entrada de la CLI
    raise SystemExit(main())


__all__ = ["cxx_type", "prototype", "header", "main"]

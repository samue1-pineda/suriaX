"""El decorador ``@hook`` que el usuario escribe en ``calls_dir``.

Existe para que un archivo de declaraciones sea Python **legítimo**:
importable, comprobable por un linter y ejecutable por un test del propio
usuario. El compilador NO lo usa — lee el archivo con ``ast.parse``
(``declarations.py``) y jamás lo importa.

Por eso el decorador no registra nada en ninguna tabla global ni tiene
efectos: solo anota la función con su metadato y la devuelve intacta. El
registro de verdad —ligar esta función Python, o su lógica C++ en
``logic_dir``, al despacho— pertenece a la VM+JIT, y este objeto es el dato
que esa capa consumirá cuando exista::

    from htims import hook

    PROJECT = "MiJuego"

    @hook("__gravity__", owner="Body",
          params=["Body ptr mutable", "float"], returns="void",
          logic="gravity_cpp")
    def gravity(body, dt):
        body.vy = body.vy - 9.8 * dt
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

#: atributo donde queda el metadato en la función decorada.
ATTRIBUTE = "__suriax_hook__"


class HookSpec:
    """Metadato de un ``@hook``, adjunto a la función que lo declara.

    Es el espejo en runtime de ``declarations.HookDecl`` (lo que el escaneo
    estático deduce sin ejecutar). Deliberadamente tonto: guardar y exponer.
    """

    __slots__ = ("name", "owner", "params", "returns", "logic", "fn")

    def __init__(self, name: str, owner: str, params: Sequence[str],
                 returns: str, logic: str, fn: Callable[..., Any]):
        self.name = name
        self.owner = owner
        self.params = tuple(params)
        self.returns = returns
        self.logic = logic
        self.fn = fn

    def __repr__(self) -> str:
        return f"<HookSpec {self.owner}.{self.name} -> {self.returns}>"


def hook(name: str, *, owner: str, returns: str,
         params: Sequence[str] = (), logic: str = ""
         ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Declara ``name`` como hook del tipo ``owner``.

    ``params``/``returns`` se escriben en tipos del LENGUAJE (``"Body ptr
    mutable"``, ``"float"``, ``"void"``), no de Python: su destinatario es la
    Semántica de suriaX. ``logic`` nombra el símbolo de la implementación C++
    en ``logic_dir`` cuando la haya; sin él, el cuerpo Python queda como
    implementación de referencia.
    """
    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        setattr(fn, ATTRIBUTE, HookSpec(name, owner, params, returns, logic, fn))
        return fn
    return decorate


__all__ = ["ATTRIBUTE", "HookSpec", "hook"]

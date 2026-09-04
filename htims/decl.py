"""Los decoradores que el usuario escribe en ``calls_dir``.

Existen para que un archivo de declaraciones sea Python **legítimo**:
importable, comprobable por un linter y ejecutable por un test del propio
usuario. El compilador NO los usa — lee el archivo con ``ast.parse``
(``declarations.py``) y jamás lo importa.

Por eso no registran nada en ninguna tabla global ni tienen efectos: solo
anotan la función con su metadato y la devuelven intacta. El registro de
verdad —ligar esta función Python, o su lógica C++ en ``logic_dir``, al
despacho— pertenece a la VM+JIT, y este objeto es el dato que esa capa
consumirá cuando exista.

**Dos decoradores, y la línea que los separa es una sola pregunta: ¿el hook
necesita salir del proceso?**

``@signature`` declara un hook que se resuelve **dentro del lenguaje**: opera
sobre valores de suriaX y su cuerpo Python es la implementación de
referencia. No puede pedir C++ (``EXT028``).

``@signature_extends`` declara el que **sí** necesita lógica nativa —una
ventana, un descriptor del sistema, memoria cruda— y exige decirlo:
``cxx=True`` no tiene valor por defecto. Un hook que baja a C++ deja de ser
verificable por el compilador solo (su cuerpo vive fuera), así que pedirlo
tiene que ser una decisión escrita, no lo que ocurre por omisión::

    from htims import signature, signature_extends

    PROJECT = "MiJuego"

    @signature("__gravity__", owner="Body",
               params=["Body ptr mutable", "float"], returns="void")
    def gravity(body, dt):
        body.vy = body.vy - 9.8 * dt

    @signature_extends("__win_open__", owner="Ventana",
                       params=["int", "int"], returns="Ventana ptr mutable",
                       cxx=True, logic="win_open_cpp")
    def win_open(w, h):
        raise NotImplementedError("lo implementa logic_dir/win_open.cpp")
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

#: atributo donde queda el metadato en la función decorada.
ATTRIBUTE = "__suriax_hook__"


class HookSpec:
    """Metadato de una firma, adjunto a la función que la declara.

    Es el espejo en runtime de ``declarations.HookDecl`` (lo que el escaneo
    estático deduce sin ejecutar). Deliberadamente tonto: guardar y exponer.
    """

    __slots__ = ("name", "owner", "params", "returns", "logic", "cxx", "fn")

    def __init__(self, name: str, owner: str, params: Sequence[str],
                 returns: str, logic: str, cxx: bool,
                 fn: Callable[..., Any]):
        self.name = name
        self.owner = owner
        self.params = tuple(params)
        self.returns = returns
        self.logic = logic
        #: ¿su implementación vive en ``logic_dir`` (C++)? Nunca por defecto.
        self.cxx = cxx
        self.fn = fn

    def __repr__(self) -> str:
        destino = " (cxx)" if self.cxx else ""
        return f"<HookSpec {self.owner}.{self.name} -> {self.returns}{destino}>"


def signature(name: str, *, owner: str, returns: str,
              params: Sequence[str] = ()
              ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Declara ``name`` como hook del tipo ``owner``, resuelto en el lenguaje.

    ``params``/``returns`` se escriben en tipos del LENGUAJE (``"Body ptr
    mutable"``, ``"float"``, ``"void"``), no de Python: su destinatario es la
    Semántica de suriaX, que los comparará contra el ``hook fn`` escrito en
    ``.srcx``.

    No acepta ``logic``: bajar a C++ se pide con :func:`signature_extends`.
    """
    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        setattr(fn, ATTRIBUTE,
                HookSpec(name, owner, params, returns, "", False, fn))
        return fn
    return decorate


def signature_extends(name: str, *, owner: str, returns: str,
                      params: Sequence[str] = (), cxx: bool = False,
                      logic: str = ""
                      ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Declara un hook cuya implementación vive en ``logic_dir`` (C++).

    ``cxx`` **no tiene valor por defecto útil**: sin ``cxx=True`` la
    declaración se rechaza (``EXT029``). Es intencional — el opt-in es la
    verificación: obliga a que quien saca un hook del lenguaje lo escriba, en
    vez de arrastrarlo sin darse cuenta al copiar una declaración.

    ``logic`` nombra el símbolo nativo que ``logic_dir`` tiene que
    implementar; sin él no hay nada que ligar.
    """
    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        setattr(fn, ATTRIBUTE,
                HookSpec(name, owner, params, returns, logic, cxx, fn))
        return fn
    return decorate


def hook(name: str, *, owner: str, returns: str,
         params: Sequence[str] = (), logic: str = ""
         ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """**Obsoleto**: el nombre anterior de :func:`signature`.

    Se mantiene para que las extensiones ya escritas sigan importando y
    corriendo. El escaneo lo acepta con las reglas nuevas —incluido el
    rechazo de ``logic`` sin ``cxx``—, así que no es una puerta trasera al
    C++ implícito.
    """
    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        setattr(fn, ATTRIBUTE,
                HookSpec(name, owner, params, returns, logic, bool(logic), fn))
        return fn
    return decorate


__all__ = ["ATTRIBUTE", "HookSpec", "signature", "signature_extends", "hook"]

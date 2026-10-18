"""Modelo de valores en runtime (secc. 5).

Los primitivos se representan con nativos de Python (``int``/``float``/
``bool``/``str``; ``char`` = ``str`` de 1 code point; ``null`` = ``None``):
cero envoltura en el camino caliente. Solo lo que Python no trae se
representa con clases propias (``__slots__``, comparación explícita):

 - :class:`FunctionValue` — una ``fn`` ligada a su unidad (sus globales).
 - :class:`Namespace` — un import ligado (``const IO = #import IO;``).
 - :class:`StructValue` — instancia de struct: campos como CELDAS (para
   que ``&p.x`` y la escritura a través de punteros tengan destino real).
 - :class:`TypeValue` — un valor del metatipo ``type`` (``const type int8;``).

Los punteros viven en :mod:`memory.pointer` (son instrucción de memoria,
no un valor más).
"""

from __future__ import annotations

from typing import Any, Dict

from .memory.pointer import Cell


class FunctionValue:
    """Una funcion con nombre usada como VALOR (``var fn(int) -> int g = doble``).

    No captura nada: es la declaracion y la unidad cuyos globales ve, y nada
    mas. Por eso se copia libremente y no tiene destructor.

    ``==`` es IDENTIDAD de la funcion (la misma declaracion), no del objeto de
    Python: ``lib.f`` crea un ``FunctionValue`` nuevo cada vez que se evalua,
    y dos lecturas de la misma funcion tienen que ser iguales.
    """

    __slots__ = ("unit_alias", "decl", "display_name")

    def __init__(self, unit_alias: str, decl: Any, *,
                 display_name: str = "") -> None:
        self.unit_alias = unit_alias
        self.decl = decl  # message FunctionDecl
        # como se ESCRIBE: el nombre declarado, o 'Tipo.metodo' para un
        # metodo (dos tipos pueden tener un metodo con el mismo nombre)
        self.display_name = display_name or decl.name

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FunctionValue) and other.decl is self.decl

    def __hash__(self) -> int:
        return id(self.decl)

    def __repr__(self) -> str:
        return f"<fn {self.display_name}>"


class LambdaValue:
    """Una ``lambda`` evaluada: su cuerpo y el MARCO donde se escribio.

    A diferencia de :class:`FunctionValue`, lee su entorno: los locales y
    parametros de quien la escribio (sus capturas) se resuelven subiendo por
    ``frame``, el mismo marco vivo, sin copiarlos. Es seguro porque no escapa
    (lo garantiza la Semantica): solo existe como argumento de una llamada, y
    muere antes de que esa llamada termine, cuando ``frame`` sigue vivo.

    ``unit`` es la unidad donde se escribio: los tipos de su cuerpo son
    indices en el pool de ESA unidad, aunque la llame una libreria
    (``Vector.filter``).
    """

    __slots__ = ("unit", "node", "frame", "ln", "col")

    def __init__(self, unit: Any, node: Any, frame: Any, ln: int, col: int) -> None:
        self.unit = unit
        self.node = node    # message LambdaExpr
        self.frame = frame
        self.ln = ln
        self.col = col

    @property
    def name(self) -> str:
        """Como se nombra en una traza o en la pila del depurador."""
        return f"lambda@{self.ln}:{self.col}"

    def __repr__(self) -> str:
        return f"<lambda {self.ln}:{self.col}>"


class Namespace:
    """Un módulo importado, ligado a su unidad HIR."""

    __slots__ = ("alias",)

    def __init__(self, alias: str) -> None:
        self.alias = alias

    def __repr__(self) -> str:
        return f"<module {self.alias}>"


class StructValue:
    __slots__ = ("type_name", "fields")

    def __init__(self, type_name: str, fields: Dict[str, Cell]) -> None:
        self.type_name = type_name
        self.fields = fields

    def __repr__(self) -> str:
        # la forma del LENGUAJE ('P{x: 3, s: "hi"}'), no la de Python
        # ('P{x=3, s='hi'}'): es la que sale en una traza o en un 'throw' sin
        # atrapar. Sin el tipo de cada campo, un 'char' sale con comillas
        # dobles; un f-string usa '_texto', que sí lo sabe.
        inner = ", ".join(f"{k}: {_field_repr(c.value)}"
                          for k, c in self.fields.items())
        short = self.type_name.rsplit(".", 1)[-1]
        return f"{short}{{{inner}}}"


def _field_repr(value: Any) -> str:
    """Un campo dentro de la representación de un struct: una cadena entre
    comillas, lo demás como en un f-string."""
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') \
            .replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r") \
            .replace("\0", "\\0") + '"'
    return format_value(value)


def copy_on_bind(value: Any) -> Any:
    """El valor que se liga a un nombre nuevo, con semántica de VALOR.

    Un ``struct`` es un valor, no una referencia: el único tipo del lenguaje
    que refiere a otro sitio es ``ptr``. Sin esta copia, ``var Caja b = a;``
    dejaba a los dos nombres apuntando al MISMO ``StructValue``, así que
    ``b.v = 99`` cambiaba también ``a`` — y con eso la regla de punteros
    quedaba sin sentido: escribir por un ``ptr`` de solo lectura es
    ``SEM015``, pero bastaba pasar el struct por valor y mutarlo.

    La copia es **superficial en los punteros y profunda en los campos**: se
    crean celdas nuevas para cada campo (por eso mutar la copia no toca al
    original) pero un ``ptr`` guardado en un campo sigue apuntando a lo mismo,
    que es lo que significa un préstamo. Un enum con payload se copia igual
    (su payload también son celdas). Los demás valores del intérprete son
    inmutables (int, float, bool, str, char) o son referencias a propósito
    (punteros, bloques, namespaces): se devuelven tal cual.
    """
    if isinstance(value, StructValue):
        return StructValue(
            value.type_name,
            {name: Cell(_copia_de_campo(cell.value), name=name)
             for name, cell in value.fields.items()},
        )
    if isinstance(value, EnumValue) and value.fields:
        # un enum con payload es un valor igual que un struct: su payload va
        # en celdas, y sin esta copia 'var Forma g = f;' compartia esas
        # celdas — cambiar el payload de 'g' (en un 'case') cambiaba 'f'
        return EnumValue(value.enum_name, value.variant,
                         [Cell(_copia_de_campo(c.value), name=c.name)
                          for c in value.fields])
    return value


def _copia_de_campo(value: Any) -> Any:
    """La copia de lo que guarda un CAMPO de un struct que se copia.

    Un bloque de ``mem`` en un campo (el almacenamiento de un ``Vector``) es
    DEL struct, como el buffer de un ``std::vector``: copiar el struct copia
    el bloque, celda a celda y en profundidad. Antes los dos structs
    compartían el mismo bloque y un ``push`` sobre la copia escribía en los
    datos del original. Un bloque ligado a una variable ``ptr`` NO pasa por
    aquí: ahí sí es un puntero, y copiarlo sería otra cosa."""
    from .memory.block import Block
    if isinstance(value, Block):
        copia = Block(len(value.cells))
        for origen, destino in zip(value.cells, copia.cells):
            destino.value = copy_on_bind(origen.value)
            destino.state = origen.state
        return copia
    return copy_on_bind(value)


class TypeValue:
    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"<type {self.name}>"


class EnumNamespace:
    """El NOMBRE de un enum usado como valor (``Estado.Activo``): expone sus
    items (enteros auto-numerados estilo C, calculados por el loader) y, si el
    enum es un tipo SUMA, los constructores de sus variantes con payload."""

    __slots__ = ("name", "items")

    def __init__(self, name: str, items: Dict[str, Any]) -> None:
        self.name = name
        self.items = items

    def __repr__(self) -> str:
        return f"<enum {self.name}>"


class VariantCtor:
    """El CONSTRUCTOR de una variante con payload (``Nodo.Literal``).

    Se invoca como cualquier otra cosa invocable y produce un
    :class:`EnumValue`. Existe como valor propio —en vez de que el intérprete
    reconozca la forma ``Enum.Variante(...)`` en el árbol— porque la variante
    también se nombra PELADA (``Literal(5)``), y entonces no hay ninguna forma
    sintáctica que reconocer: hay un nombre que resuelve a algo invocable.
    """

    __slots__ = ("enum_name", "variant", "arity")

    def __init__(self, enum_name: str, variant: str, arity: int) -> None:
        self.enum_name = enum_name
        self.variant = variant
        self.arity = arity

    def __repr__(self) -> str:
        return f"<variante {self.enum_name}.{self.variant}/{self.arity}>"


class EnumItem(int):
    """Un item de un enum SIN datos (estilo C): un entero que sabe de qué enum
    es y cómo se llama.

    Sigue siendo un ``int`` para todo lo demás (comparar, ordenar, el hash
    splitmix64 que comparte con la VM, ``cast<int>``, guardarlo en un bloque):
    solo cambia lo que el entero solo no podía decir. Dentro de un genérico
    (``f"{x}"`` con ``x: T``) el tipo estático es ``T`` y no nombra el enum,
    así que el texto lo decide el VALOR (A08): ``VERDE`` y no ``1``.

    Sin ``__slots__``: Python no admite slots no vacíos en una subclase de
    ``int``. La aritmética devuelve un ``int`` llano, que es lo correcto (un
    ``ROJO + 1`` ya no es un item).
    """

    def __new__(cls, value: int, enum_of: str, variant: str) -> "EnumItem":
        item = super().__new__(cls, value)
        # 'enum_of' y no 'enum_name' a proposito: lo que despacha un hook por
        # 'getattr(valor, "enum_name")' (print con 'T: Print', '__hash__')
        # no debe tomar un item estilo C por un tipo con hooks (no puede
        # declararlos: SEM006).
        item.enum_of = enum_of
        item.variant = variant
        return item

    # 'repr' y 'str' siguen siendo los del entero: una traza o un 'cast<str>'
    # que antes escribían '1' no cambian por llevar el nombre.
    __repr__ = int.__repr__
    __str__ = int.__repr__


class EnumValue:
    """El valor de un enum SUMA: qué variante es, y lo que lleva.

    Los campos son :class:`Cell` como los de un struct, así que el payload
    participa del mismo modelo de memoria que todo lo demás (una variante que
    lleva un puntero lo comparte igual que un campo).

    Una variante SIN datos de un enum suma (``Forma.Punto``) también es un
    ``EnumValue``, con ``fields`` vacío: es un valor DEL ENUM como sus
    hermanas, y lo que despacha por el tipo del valor (``__eq__``,
    ``__hash__``, ``__cmp__``, ``&v[i]`` de ``Vector.at``, un f-string en un
    genérico) la reconoce. Antes era un entero y lo perdía (A10, A10b, A02).
    El loader crea UNA por variante; sin campos, no hay nada que copiar.
    """

    __slots__ = ("enum_name", "variant", "fields")

    def __init__(self, enum_name: str, variant: str, fields: list) -> None:
        self.enum_name = enum_name
        self.variant = variant
        self.fields = fields

    def __repr__(self) -> str:
        return f"{self.variant}({', '.join(repr(f) for f in self.fields)})"


def format_value(value: Any) -> str:
    """Representación para f-strings y trazas (estable, educativa)."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, EnumValue):
        # 'Literal(5)' — la misma forma con la que se escribe en el fuente.
        if not value.fields:
            return value.variant
        dentro = ", ".join(format_value(c.value) for c in value.fields)
        return f"{value.variant}({dentro})"
    return str(value)


__all__ = ["FunctionValue", "LambdaValue", "Namespace", "StructValue", "TypeValue",
           "copy_on_bind",
           "EnumNamespace", "VariantCtor", "EnumItem", "EnumValue", "format_value"]

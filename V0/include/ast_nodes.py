"""Nodos del AST de suriaX.

Contrato compartido entre el parser (que los construye) y las fases
posteriores (que los consumen). Sigue la gramatica formal en
``docs/gramar/grammar.ebnf``.

Convenciones:

 - Todas las clases son ``@dataclass(slots=True)``: **mutables** (a
   diferencia de ``Token``/``StringValue`` en ``t_types.py``, que son
   inmutables) porque la fase AST-tipado anota el mismo arbol en sitio
   (campos ``restype`` / ``return_restype``) en lugar de reconstruirlo --
   evita duplicar el arbol completo solo para adjuntar tipos.
 - Toda clase hereda ``ln``/``col`` de :class:`ASTNode`: ubican el primer
   token de la construccion, igual que ``Token.ln``/``Token.col``.
 - ``Expression`` / ``Statement`` / ``TypeExpr`` / ``Declaration`` son
   marcadores (``__slots__ = ()``) para que ``isinstance`` documente y valide
   la posicion gramatical sin reintroducir ``__dict__`` en la cadena de
   herencia.
 - El AST es la salida de la fase **Parser**; los campos ``restype`` /
   ``return_restype`` (``Optional[include.types_ast.Type]``) permanecen en
   ``None`` hasta que ``parser/typed_ast.py`` resuelve las anotaciones
   explicitas (fase AST-tipado). Ningun otro campo se toca en esa fase.
 - TODA ``Expression`` tiene ``restype``: la Semantica (``scope_resolver``)
   anota en sitio el tipo que su visitor ya calcula, para que el HIR
   serialice el arbol con su semantica completa (``None`` = tipo aun no
   inferible en esta version; los targets lo tratan como desconocido).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Union

try:
    from include.types_ast import Type
except ImportError:  # pragma: no cover - ejecucion directa
    from types_ast import Type  # type: ignore


# ============================================================================
# raiz y marcadores
# ============================================================================

@dataclass(slots=True)
class ASTNode:
    ln: int
    col: int


class Expression(ASTNode):
    """Nodo que produce un valor."""
    __slots__ = ()


class Statement(ASTNode):
    """Nodo que aparece dentro de un :class:`Block`."""
    __slots__ = ()


class Declaration(ASTNode):
    """Nodo de nivel superior (``top_level``): no aparece dentro de un bloque."""
    __slots__ = ()


class TypeExpr(ASTNode):
    """Anotacion de tipo tal como se escribio en el fuente (sin resolver).

    ``grammar/types.py`` construye estos nodos; ``parser/typed_ast.py`` los
    resuelve a un :class:`include.types_ast.Type` estructurado.
    """
    __slots__ = ()


# ============================================================================
# tipos (sintacticos, sin resolver)
# ============================================================================

@dataclass(slots=True)
class PrimitiveTypeExpr(TypeExpr):
    name: str  # 'int' | 'float' | 'bool' | 'char' | 'str' | 'void'


@dataclass(slots=True)
class NominalTypeExpr(TypeExpr):
    """Tipo definido por el usuario (struct/enum/``type``), sin resolucion.

    ``name`` puede venir CUALIFICADO con puntos (``dt.int8``) cuando el tipo
    lo publica una libreria importada. El parser solo transporta el nombre
    completo; recorrer los miembros hasta el simbolo es de la Semantica (ver
    ``semantic/type_service.lookup_type_path``).
    """
    name: str
    args: List["TypeExpr"] = field(default_factory=list)
    """ARGUMENTOS DE TIPO de un generico (``Vector<int>``). Vacio en un tipo
    corriente. Se transportan sin resolver: que es cada uno lo decide la
    Semantica, igual que con ``name``."""


@dataclass(slots=True)
class MetaTypeExpr(TypeExpr):
    """El token ``type`` usado como anotacion: el TIPO de un tipo.

    Aparece en las dos posiciones del metatipo: el binding de un
    ``type_decl`` (``const type int8;``) y el retorno de una funcion que
    produce tipos (``fn _block_def(int len) -> type``).
    """


@dataclass(slots=True)
class PointerTypeExpr(TypeExpr):
    """``ptr T`` (solo lectura a traves del puntero) o ``ptr mutable T``
    (permite escribir a traves de el — analogo a const-correctness de C).
    ``mutable`` califica al PUNTERO, no al binding (los bindings usan
    ``var``/``const``)."""
    inner: TypeExpr
    mutable: bool = False


@dataclass(slots=True)
class NullableTypeExpr(TypeExpr):
    inner: TypeExpr


@dataclass(slots=True)
class SelfTypeExpr(TypeExpr):
    """El placeholder ``self`` en una firma de trait: el tipo que hará
    ``@impl``. Se escribe como un tipo nominal de nombre ``self`` (no es
    keyword) y ``typed_ast`` lo resuelve a :data:`include.types_ast.SELF_TYPE`.
    Solo tiene sentido dentro de un prototipo de trait; usarlo en otra posición
    es un error semántico."""


@dataclass(slots=True)
class ErrorTypeExpr(TypeExpr):
    """``error T`` (union "T o error") o ``error`` a secas (solo error).

    Modelo de errores del lenguaje: un binding ``error T`` puede contener un
    valor de tipo ``T`` O un error propagado. ``try``/``catch`` interceptan
    la propagacion; ``throw`` la inicia (ver ``ThrowStmt``/``TryStmt``).
    ``inner`` es ``None`` para ``error`` sin tipo envuelto."""
    inner: Optional[TypeExpr] = None


# ============================================================================
# expresiones
# ============================================================================

@dataclass(slots=True)
class Literal(Expression):
    value: Any
    literal_kind: str  # 'int' | 'float' | 'str' | 'char' | 'bool' | 'null'
    restype: Optional[Type] = None


@dataclass(slots=True)
class InterpolatedString(Expression):
    """``f"texto{expr}texto"`` con al menos una interpolacion.

    Solo una f-string (prefijo explicito ``f``) puede producir este nodo:
    las cadenas planas ``"..."`` no interpolan (``{``/``}`` literales).
    ``parts`` alterna segmentos ``str`` (texto literal) y :class:`Expression`
    (cada ``{expr}`` ya analizado por el parser -- el lexer solo delimitaba
    el texto crudo, ver ``Interp`` en ``include/t_types.py``). Una f-string
    SIN interpolaciones toma el camino rapido y se representa como un
    :class:`Literal` plano (``literal_kind='str'``), evitando este nodo.
    """
    parts: List[Union[str, Expression]] = field(default_factory=list)
    restype: Optional[Type] = None


@dataclass(slots=True)
class Identifier(Expression):
    name: str
    restype: Optional[Type] = None


@dataclass(slots=True)
class UnaryOp(Expression):
    operator: str  # 'not' | '-'  ('&' tiene nodo propio: AddrOf)
    operand: Expression
    restype: Optional[Type] = None


@dataclass(slots=True)
class AddrOf(Expression):
    """``&expr`` -- direccion de un lvalue.

    Nodo propio en vez de un ``UnaryOp`` con operador string: los
    consumidores del HIR (LLVM, interprete) despachan por CLASE de nodo, y
    las reglas de punteros (lvalue obligatorio, mutabilidad heredada del
    binding) son semantica de este nodo, no de un operador generico.
    """
    operand: Expression
    restype: Optional[Type] = None
    mut: Optional[bool] = None
    """Mutabilidad del puntero resultante, resuelta por la Semantica:
    ``&x`` sobre un binding ``var`` -> ``True`` (``ptr mutable T``); sobre
    un ``const`` -> ``False`` (``ptr T``). ``None`` hasta esa fase."""


@dataclass(slots=True)
class BinaryOp(Expression):
    operator: str
    left: Expression
    right: Expression
    restype: Optional[Type] = None


@dataclass(slots=True)
class Assignment(Expression):
    """``target = value``. ``target`` debe ser un lvalue (Identifier /
    MemberAccess / Index); ``expressions/led.py`` lo valida al construirse."""
    target: Expression
    value: Expression
    restype: Optional[Type] = None


@dataclass(slots=True)
class Call(Expression):
    callee: Expression
    args: List[Expression] = field(default_factory=list)
    type_args: List[TypeExpr] = field(default_factory=list)
    """ARGUMENTOS DE TIPO escritos en la llamada: ``make<int>(4)`` -> el
    ``TypeExpr`` de ``int``. Vacio en una llamada corriente y tambien cuando
    el generico se resuelve por los argumentos (``primero(1)``): esto es lo
    que se ESCRIBIO, no lo que se dedujo."""
    restype: Optional[Type] = None
    valor_constante: Optional[int] = None
    """La llamada se RESOLVIO a un entero en compilacion (``min(dt.int8)`` ->
    ``-128``). Solo lo usan ``min``/``max``, cuyo resultado es el rango que el
    tipo declara con ``__min__``/``__max__`` — un dato que ya se conoce al
    compilar. El emisor pone un literal en vez de la llamada, asi que ningun
    consumidor del HIR se entera de que hubo una llamada."""
    hook: Optional[Any] = None
    temp_drop: Optional[Any] = None
    """``Symbol`` del ``__free__`` que destruye el resultado de esta expresion
    al terminar la sentencia, cuando el valor producido NO queda en manos de
    nadie (un temporal). ``None`` si lo recibe un binding, un ``return`` o una
    asignacion — en ese caso su nuevo dueno se encarga."""
    """Anotado en sitio por la Semantica (mismo patron que ``restype``):
    ``Symbol`` del hook de tipo al que despacha la llamada cuando el callee
    es un hook invocable por convencion (``print(x)`` -> ``__print__`` del
    tipo de ``x``, ``len(x)`` -> ``__len__``). ``None`` si es una llamada
    normal. Ver ``semantic/hooks.py``."""


@dataclass(slots=True)
class Index(Expression):
    obj: Expression
    index: Expression
    restype: Optional[Type] = None


@dataclass(slots=True)
class MemberAccess(Expression):
    obj: Expression
    member: str
    restype: Optional[Type] = None
    nombre_de_item: Optional[str] = None
    """``TType.PLUS.name`` -> ``"PLUS"``, resuelto al COMPILAR.

    El nombre de un item de enum se conoce sin ejecutar nada, asi que el
    emisor pone la cadena y ningun consumidor del HIR se entera de que hubo
    un acceso a miembro. Es el mismo trato que reciben ``min``/``max`` sobre
    un tipo de libreria (ver ``Call.valor_constante``). ``None`` en cualquier
    otro acceso."""


@dataclass(slots=True)
class StructLiteral(Expression):
    """``T{ campo: expr, ... }`` -- instancia un struct nominal ``T``.

    Unica forma NATIVA de construir un valor de struct (sin ``alloc``):
    produce el valor; ``&literal_en_una_var`` da el puntero.
    ``field_names`` y ``values`` son listas PARALELAS (mismo indice = mismo
    campo), en el orden escrito. Listas paralelas y no ``[(str, Expr)]``
    para que ``include/ast_walk`` recorra las expresiones (las tuplas serian
    hojas y sus valores no se anotarian/validarian)."""
    type_name: str
    field_names: List[str] = field(default_factory=list)
    values: List[Expression] = field(default_factory=list)
    type_args: List["TypeExpr"] = field(default_factory=list)
    """Argumentos de tipo de un generico (``Caja<int>{ ... }``). Vacio para
    un struct corriente. Van aqui y no en ``type_name`` porque son TIPOS que
    hay que resolver, no texto: participan de la identidad del resultado."""
    restype: Optional[Type] = None
    temp_drop: Optional[Any] = None
    """``Symbol`` del ``__free__`` que destruye el resultado de esta expresion
    al terminar la sentencia, cuando el valor producido NO queda en manos de
    nadie (un temporal). ``None`` si lo recibe un binding, un ``return`` o una
    asignacion — en ese caso su nuevo dueno se encarga."""


@dataclass(slots=True)
class CastExpr(Expression):
    """``cast<T>(expr)`` -- conversion EXPLICITA de tipo.

    Es la unica forma nativa que usa la posicion de argumentos de tipo
    ``<...>`` (``grammar/types.parse_type_args``); las librerias podran usar
    la misma posicion para genericos (``vec<int>``) a futuro.

    Nativamente convierte entre primitivos numericos; hacia un tipo NOMINAL
    despacha al hook ``__cast__`` del tipo destino (``semantic/hooks.py``).
    Sin coerciones implicitas en el lenguaje: todo cambio de tipo pasa por
    aqui (``int8 b = cast<int8>(10);``).
    """
    type: TypeExpr
    value: Expression
    restype: Optional[Type] = None
    hook: Optional[Any] = None
    """``Symbol`` del ``__cast__`` del tipo nominal destino, si existe
    (anotado por la Semantica -- ``type_resolver``)."""


@dataclass(slots=True)
class SizeofExpr(Expression):
    """``sizeof(X)`` -- el tamano de un TIPO, o el del tipo de un VALOR.

    ``X`` se escribe en posicion de tipo, asi que sintacticamente siempre es
    un ``TypeExpr``; que ``sizeof(a)`` mida "el tipo de la variable a" lo
    decide la Semantica, que es la unica que sabe si ese nombre esta en el
    namespace de tipos o en el de valores."""
    type: TypeExpr
    restype: Optional[Type] = None
    medido: Optional[Type] = None
    """El tipo que realmente se mide, ya resuelto y CANONICALIZADO. Distinto
    de ``restype`` (que es el ``int`` que produce la expresion) y de ``type``
    (que es lo ESCRITO: 'a' cuando se midio el tipo de la variable 'a')."""
    hook: Optional[Any] = None
    """``Symbol`` del ``__sizeof__`` de T si existe (anotado por la Semantica)."""


# ============================================================================
# sentencias
# ============================================================================

@dataclass(slots=True)
class Drop:
    """Una destruccion que el compilador insertara al cerrar un bloque.

    NO es un nodo de sintaxis: nadie la escribe. Es una ANOTACION que la
    Semantica cuelga del bloque —el punto de destruccion es la llave que
    cierra, y el modelo de memoria dice que ahi muere el valor— y que viaja al
    HIR para que el interprete y el backend nativo ejecuten exactamente lo
    mismo, sin volver a decidirlo cada uno.

    Por eso no hereda de ``ASTNode``: no tiene posicion propia ni hijos que
    recorrer (``ast_walk`` la salta por nombre de campo).
    """
    path: List[str] = field(default_factory=list)
    """Ruta del valor a destruir: ``["b"]`` para un local, ``["c", "b"]`` para
    el campo de un local. Se aplana AQUI —y no se resuelve en ejecucion—
    porque saber que campos poseen recursos es una pregunta sobre el TIPO, y
    esa la contesta el compilador."""
    hook: Optional[Any] = None
    """``Symbol`` del ``__free__`` que destruye lo que hay al final de ``path``."""


@dataclass(slots=True)
class Block(Statement):
    statements: List[Statement] = field(default_factory=list)
    drops: List[Drop] = field(default_factory=list)
    """Destrucciones al cerrar el bloque, en orden INVERSO al de declaracion
    (lo ultimo que nace es lo primero que muere). Las anota la Semantica."""


@dataclass(slots=True)
class VarDecl(Statement):
    qualifier: Optional[str]  # 'const' | 'var' | None (None equivale a 'var', estilo C)
    type: TypeExpr
    name: str
    value: Optional[Expression] = None
    restype: Optional[Type] = None
    visibility: Optional[str] = None
    """Reserva de visibilidad; solo aplica a un binding de NIVEL SUPERIOR
    (ver ``FunctionDecl.visibility``). En una variable local queda ``None``."""
    capacity: Optional[Expression] = None
    """Capacidad ESCRITA de un contenedor: la ``n`` de ``int vec.Vector v[n];``.

    La declaracion con corchetes es AZUCAR — el parser la convierte en el
    ``var`` y la llamada al constructor que ya existian—, pero la capacidad se
    conserva aqui para que la Semantica pueda avisar cuando un ``push`` se
    salga de lo reservado sin esperar a la ejecucion. Es informativa: ninguna
    fase la necesita para producir codigo."""


@dataclass(slots=True)
class TypeDecl(Statement):
    """``[qualifier] "type" IDENTIFIER [ "=" expression ] ";"``.

    Declara un TIPO NOMINAL OPACO: un tipo con nombre y sin representacion
    escrita en suriaX (no tiene campos como un ``struct``). Su layout lo
    aporta el backend o sus hooks (``__sizeof__``/``__make__``...). Es la
    forma en que una libreria publica tipos NO nativos del lenguaje::

        const type int8;      // dt_variables.libsrx: 'int8' es un tipo
        const type float16;

    y el consumidor los usa como cualquier otro tipo (``const dt.int8 x;``).

    ``value`` cubre la forma con inicializador: como ``type`` es un tipo de
    primera clase (:data:`include.types_ast.META_TYPE`), un tipo puede
    calcularse con una funcion que devuelva ``type``::

        const type Blk = _block_def(4, cursor);

    ``qualifier``: ``const`` = el nombre queda ligado a ESE tipo para
    siempre; ``var``/``None`` = redefinible (mismo modelo que las variables).

    Nodo propio en vez de un ``VarDecl`` con ``type=MetaTypeExpr`` porque lo
    que declara vive en el namespace de TIPOS, no en el de valores: fundirlo
    con ``VarDecl`` obligaria a cada pasada a mirar el ``restype`` para saber
    en que namespace registrar el nombre.
    """
    qualifier: Optional[str]  # 'const' | 'var' | None (None equivale a 'var')
    name: str
    value: Optional[Expression] = None
    restype: Optional[Type] = None
    """Siempre :data:`include.types_ast.META_TYPE` — el tipo del BINDING
    (``int8`` es un valor de tipo ``type``), no el tipo que declara."""
    visibility: Optional[str] = None
    """Reserva de visibilidad de nivel superior (ver ``FunctionDecl.visibility``)."""
    type_params: List[str] = field(default_factory=list)
    """PARAMETROS DE TIPO del generico: ``const type Caja<T>;`` -> ``["T"]``.
    Van con el NOMBRE, al final, que es donde el lenguaje pone siempre lo que
    identifica una declaracion. Vacio en un tipo corriente."""


@dataclass(slots=True)
class ImportBinding(Statement):
    """``[qualifier] IDENTIFIER "=" ( import_dir | from_dir )``.

    Forma real de TODOS los ejemplos del lenguaje (``const IO = #import IO;``)
    que ``var_decl`` no cubre: no lleva anotacion de tipo (el tipo de un
    modulo importado no es una anotacion sintactica, ver ``grammar.ebnf``
    secc. 1/2 -- ``var_decl`` exige ``type`` siempre). Se modela como nodo
    propio en vez de forzarlo dentro de ``VarDecl`` con ``type=None``.
    """
    qualifier: Optional[str]  # 'const' | 'mutable' | None
    name: str
    source: Union["ImportDirective", "FromDirective"]
    visibility: Optional[str] = None
    """Reserva de visibilidad de nivel superior (ver ``FunctionDecl.visibility``).
    El ``#import``/``#from`` en si es una directiva (sin visibilidad); lo que
    puede llevarla es el BINDING que le da nombre local."""


@dataclass(slots=True)
class IfStmt(Statement):
    condition: Expression
    then_block: Block
    else_branch: Optional[Union[Block, "IfStmt"]] = None


@dataclass(slots=True)
class WhileStmt(Statement):
    condition: Expression
    body: Block


@dataclass(slots=True)
class CaseArm(Statement):
    """``case <expression> : (statement | block)``. El patron es una
    expresion: la gramatica de suriaX no define un lenguaje de patrones aparte."""
    pattern: Expression
    body: Statement


@dataclass(slots=True)
class MatchStmt(Statement):
    subject: Expression
    cases: List[CaseArm] = field(default_factory=list)


@dataclass(slots=True)
class ReturnStmt(Statement):
    value: Optional[Expression] = None
    transfers: bool = False
    """El valor devuelto POSEE recursos y se entrega al llamador, asi que el
    ambito que lo tenia deja de ser su dueno y no debe destruirlo.

    Lo decide la Semantica y no el runtime porque "posee recursos" es una
    pregunta sobre el TIPO. Que sea condicional importa: devolver un 'int'
    —o el campo entero de un receptor PRESTADO— no transfiere nada, y
    marcarlo invalidaria un valor ajeno."""


@dataclass(slots=True)
class BreakStmt(Statement):
    pass


@dataclass(slots=True)
class ContinueStmt(Statement):
    pass


@dataclass(slots=True)
class MoveStmt(Statement):
    target: Expression


@dataclass(slots=True)
class MoveExpr(Expression):
    """``move x`` en posicion de EXPRESION: transfiere y DEVUELVE el valor.

    Es la forma con la que el modelo de memoria se escribe de verdad
    (``var Buffer b = move origen;``, ``consumir(move b)``): sin ella no habia
    manera de ligar un valor que POSEE recursos a otro nombre, porque ligarlo
    a secas deja dos duenos del mismo recurso y su destructor corre dos veces.
    La documentacion la usaba desde el principio; el parser no la tenia.

    ``MoveStmt`` sigue existiendo para la forma de sentencia (``move x;``),
    que invalida sin llevarse el valor a ningun sitio.
    """
    operand: Expression
    restype: Optional[Type] = None


@dataclass(slots=True)
class ThrowStmt(Statement):
    """``throw expression;`` -- inicia la propagacion de un error.

    El valor lanzado se propaga por la pila de llamadas hasta el ``catch``
    mas cercano (modelo de excepciones). Sin ``catch`` en el camino, aborta
    la ejecucion con un error de runtime."""
    value: Expression


@dataclass(slots=True)
class CatchClause(ASTNode):
    """Una rama ``catch``: a que valores atrapa y que hace con ellos.

    Con TIPO (``catch (Fallo e)``) atrapa solo los valores de ese tipo y liga
    ``e`` ya tipado; sin el (``catch (e)``) atrapa cualquiera y ``e`` es de
    tipo desconocido. La diferencia importa porque un valor capturado sin
    tipo hay que convertirlo a mano antes de poder usarlo para algo.
    """
    name: str
    block: Block
    type: Optional[TypeExpr] = None
    restype: Optional[Type] = None
    """``type`` ya resuelto (anotado por ``parser/typed_ast.py``); ``None`` en
    una rama sin tipo."""


@dataclass(slots=True)
class TryStmt(Statement):
    """``try block { catch "(" [type] IDENTIFIER ")" block }``.

    Ejecuta ``try_block``; si algo lanzado (``throw``) se propaga por el, se
    prueban las ramas EN ORDEN y gana la primera cuyo tipo encaje. Si ninguna
    encaja, el valor sigue propagandose — que es lo que hace util filtrar por
    tipo: una rama que no sabe manejar un fallo no se lo queda.

    El binding de cada rama vive solo en el scope de SU bloque."""
    try_block: Block
    catches: List[CatchClause] = field(default_factory=list)


@dataclass(slots=True)
class FreeStmt(Statement):
    target: Expression
    hook: Optional[Any] = None
    """``Symbol`` del ``__free__`` del tipo del target si existe (anotado
    por la Semantica en el mismo punto donde resuelve el simbolo del target)."""


@dataclass(slots=True)
class ExprStmt(Statement):
    expr: Expression


# ============================================================================
# declaraciones (top-level)
# ============================================================================

@dataclass(slots=True)
class Parameter(ASTNode):
    type: TypeExpr
    name: str
    restype: Optional[Type] = None


@dataclass(slots=True)
class FunctionDecl(Declaration):
    name: str
    params: List[Parameter]
    return_type: TypeExpr
    body: Optional[Block]
    """``None`` para un PROTOTIPO (``fn put_char(char c) -> void;``): la firma
    se declara pero la implementacion la aporta el backend / ``#extern``. Las
    pasadas que recorren el cuerpo (``scope_resolver``, ``memory_check``) lo
    saltan cuando es ``None``; la firma (params/retorno) se valida igual."""
    return_restype: Optional[Type] = None
    type_params: List[str] = field(default_factory=list)
    """PARAMETROS DE TIPO del generico: ``fn make<T>(int n) -> T ptr;`` ->
    ``["T"]``. Van tras el NOMBRE, igual que en un ``struct``/``type``: el
    lenguaje pone siempre junto al nombre lo que identifica la declaracion.
    Vacio en una funcion corriente."""
    dunder: Optional[str] = None
    """Nombre "dunder" SIN guiones (p. ej. ``"free"`` para ``fn __free__``)
    cuando ``name`` vino de un token ``DUNDER``; ``None`` para una funcion con
    nombre corriente. Puramente estructural: la FORMA ``__x__`` ya NO implica
    que sea un hook -- eso lo decide ``specifier`` (ver abajo)."""
    specifier: Optional[str] = None
    """Especificador explicito de metodo especial (el compilador ya NO adivina
    por la forma del nombre):

     - ``"hook"``: ``hook fn __free__(...)``. Debe ser uno del set FIJO
       reconocido por el compilador (``semantic/hooks.py::HOOK_SPECS``:
       free/make/sizeof/print/len/cast), con firma validada, y participa del
       despacho automatico (``free x;`` -> ``__free__``).
     - ``"dunder"``: ``dunder fn __xxx__(...)``. Metodo especial LIBRE del
       usuario: cualquier nombre ``__x__``. Se registra como funcion normal;
       el compilador NO le exige firma ni lo despacha por convencion.
     - ``None``: ``fn ...`` corriente. Incluso si el nombre tiene forma
       ``__x__`` es solo una funcion normal (el usuario puede usar ``__`` sin
       colisionar con el sistema de hooks)."""
    visibility: Optional[str] = None
    """``"public"`` | ``"private"`` | ``"internal"`` | ``None`` (== publico).
    Reserva de visibilidad (prefijo opcional). ``public`` = usable al importar
    el archivo/libreria; ``private`` = solo entre archivos del MISMO paquete;
    ``internal`` = exclusivo de ESTE archivo. El parser solo transporta el
    hecho; el enforcement es de la Semantica + ``linker_p``."""


@dataclass(slots=True)
class Field(ASTNode):
    type: TypeExpr
    name: str
    restype: Optional[Type] = None


@dataclass(slots=True)
class StructDecl(Declaration):
    fields: List[Field]
    name: str
    visibility: Optional[str] = None
    """Reserva de visibilidad (ver ``FunctionDecl.visibility``)."""
    type_params: List[str] = field(default_factory=list)
    """PARAMETROS DE TIPO del generico: ``... Vector<T>;`` -> ``["T"]``. Van
    con el NOMBRE, al final, que es donde el lenguaje pone siempre lo que
    identifica una declaracion. Vacio en un tipo corriente."""



@dataclass(slots=True)
class EnumItem(ASTNode):
    """Una variante de un ``enum``.

    Dos formas, excluyentes entre si:

    * ``ROJO`` / ``ROJO = 5`` -- variante UNIDAD, un entero (estilo C).
    * ``Literal(int)`` -- variante con PAYLOAD: lleva valores propios, y
      entonces el enum es un tipo SUMA ("es una de estas formas") en vez de
      un conjunto de enteros con nombre.
    """
    name: str
    value: Optional[Expression] = None
    payload: List["TypeExpr"] = field(default_factory=list)
    """Tipos que lleva la variante, en el orden escrito. Vacio en una variante
    unidad."""
    payload_restypes: List[Type] = field(default_factory=list)
    """``payload`` ya resuelto (anotado por ``parser/typed_ast.py``)."""


@dataclass(slots=True)
class EnumDecl(Declaration):
    name: str
    items: List[EnumItem] = field(default_factory=list)
    visibility: Optional[str] = None
    """Reserva de visibilidad (ver ``FunctionDecl.visibility``)."""

    @property
    def es_suma(self) -> bool:
        """¿Alguna variante lleva payload?

        Es lo que separa las dos clases de enum, y la separacion es TOTAL: un
        enum de solo variantes unidad son enteros con nombre (estilo C, se
        asignan a ``int`` y se comparan con ``==``); en cuanto UNA variante
        lleva payload el enum pasa a ser un tipo suma y sus valores dejan de
        ser enteros — incluidas las variantes unidad, que valen solo su
        discriminante. Mezclar las dos lecturas dentro del mismo tipo seria lo
        confuso; elegir por enum no lo es.
        """
        return any(item.payload for item in self.items)


@dataclass(slots=True)
class DecoratorDecl(Declaration):
    """``@name [ "(" args ")" ] decl`` -- decorador GENERALIZADO.

    ``target`` es la declaración decorada: una función (``@inline fn``), un
    ``struct`` (``@impl(iterable) struct``) o un ``enum``. ``args`` son los
    nombres entre paréntesis (``@impl(iterable)`` -> ``["iterable"]``); vacío
    para un decorador sin argumentos. El parser solo transporta el hecho; qué
    hace cada decorador es de la Semántica (``@impl`` verifica conformidad de
    trait, ver ``TraitDecl``). ``@trait`` NO produce un ``DecoratorDecl``: tiene
    cuerpo propio y produce un :class:`TraitDecl`."""
    name: str
    target: Union[FunctionDecl, "StructDecl", "EnumDecl"]
    args: List[str] = field(default_factory=list)
    visibility: Optional[str] = None
    """Reserva de visibilidad; se aplica a la declaración decorada
    (``target``). Ver ``FunctionDecl.visibility``."""


@dataclass(slots=True)
class ImplDecl(Declaration):
    """``@impl Tipo { fn m(...) ... }`` -- bloque de MÉTODOS de ``Tipo``.

    Azúcar de agrupación: cada ``fn`` del bloque es un método con RECEPTOR
    EXPLÍCITO (primer parámetro ``Tipo ptr [mutable] self``), registrado como
    un ``dunder`` de nombre LLANO (``(Tipo, "push")``) para despacharse como
    ``x.push(...)``. El parser lo APLANA en sus ``methods`` (cada uno un
    ``FunctionDecl`` con ``specifier="dunder"`` y ``dunder=name``): las fases
    posteriores nunca ven un ``ImplDecl``, solo los métodos ya marcados."""
    type_name: str
    methods: List[FunctionDecl] = field(default_factory=list)
    type_params: List[str] = field(default_factory=list)
    """``@impl Vector<T> { ... }``: los parametros del tipo, para que los
    metodos puedan nombrar ``T`` en su firma. Se declaran como tipos opacos
    igual que los del ``struct``, y por el mismo motivo."""


@dataclass(slots=True)
class TraitMethod(ASTNode):
    """Un método REQUERIDO por un trait: un prototipo (sin cuerpo) cuyos
    parámetros son solo TIPOS (sin nombre). ``self`` en un tipo representa el
    tipo que implementará el trait (:class:`SelfTypeExpr`)."""
    name: str
    params: List[TypeExpr] = field(default_factory=list)
    return_type: Optional[TypeExpr] = None
    param_restypes: Optional[List[Type]] = None
    return_restype: Optional[Type] = None


@dataclass(slots=True)
class TraitDecl(Declaration):
    """``@trait`` -> contrato con nombre = conjunto de firmas de método dunder.

    Dos formas (ambas producen este nodo):

     - **struct**: ``@trait [vis] struct { <trait_method>... } Nombre;`` --
       agrupa varios métodos bajo ``Nombre``.
     - **suelta**: ``@trait [vis] [dunder] fn __x__(<tipos>) -> T;`` -- un
       trait de UN método, cuyo nombre ES el del método (``__x__``).

    Un tipo declara que lo cumple con ``@impl(Nombre) struct { ... } T;``; la
    Semántica (``semantic/traits.py``) verifica que ``T`` provea cada método
    con la firma exacta (``self`` -> ``T``)."""
    name: str
    methods: List[TraitMethod] = field(default_factory=list)
    visibility: Optional[str] = None


@dataclass(slots=True)
class TestDecl(Declaration):
    """``test STRING_LIT block`` -- bloque de prueba nombrado (estilo Zig).

    Declaracion de primer nivel: el runner de pruebas ejecuta su cuerpo; la
    compilacion normal lo VALIDA (scope/tipos) pero no lo ejecuta. No es una
    funcion (no se invoca, no tiene firma): ``name`` es su etiqueta legible."""
    name: str
    body: Block


# ============================================================================
# directivas / interoperabilidad
# ============================================================================

@dataclass(slots=True)
class ImportDirective(Declaration):
    lib: str  # puede ser punteado: 'io' | 'io.string' (submodulo de un paquete)
    alias: Optional[str] = None
    # ANOTACIONES de la Semantica (el parser las deja vacias): 'unit' es la
    # unidad calificada que resolvio 'linker_p' ('IO.stdp') y 'binding' el
    # nombre local que quedo en el scope. Viajan al HIR para que ningun
    # consumidor tenga que re-resolver el import (ver hir.proto).
    unit: str = ""
    binding: str = ""


@dataclass(slots=True)
class ExportDirective(Declaration):
    alias: str
    package: bool = False
    """``#export package as <alias>``: este archivo es el PADRE de un
    paquete .libsrx (la carpeta entera se expone bajo <alias>, ver
    ``src/linker_p/``). ``False`` = export normal de un solo archivo."""


@dataclass(slots=True)
class FromDirective(Declaration):
    lib: str
    name: str
    alias: Optional[str] = None
    unit: str = ""  # unidad calificada resuelta (ver ImportDirective.unit)


@dataclass(slots=True)
class ExternBlock(Declaration):
    target: str  # hoy solo 'cpp'
    raw: str
    #: banderas que ESTA unidad necesita para compilar/enlazar su C++
    #: (``requires("-lX11")``). Las declara quien trae el C++ porque es quien
    #: sabe de qué depende; el linker las suma a las del proyecto, así que un
    #: consumidor no tiene que averiguar las dependencias de sus librerías.
    requires: List[str] = field(default_factory=list)


# ============================================================================
# raiz del programa
# ============================================================================

@dataclass(slots=True)
class Program(ASTNode):
    items: List[ASTNode] = field(default_factory=list)


__all__ = [
    "ASTNode", "Expression", "Statement", "Declaration", "TypeExpr",
    "PrimitiveTypeExpr", "NominalTypeExpr", "PointerTypeExpr", "NullableTypeExpr",
    "ErrorTypeExpr", "SelfTypeExpr",
    "Literal", "InterpolatedString", "Identifier", "UnaryOp", "AddrOf",
    "BinaryOp", "Assignment",
    "Call", "Index", "MemberAccess", "StructLiteral", "CastExpr", "SizeofExpr",
    "Block", "Drop", "VarDecl", "ImportBinding",
    "IfStmt", "WhileStmt", "CaseArm",
    "MatchStmt", "ReturnStmt", "BreakStmt", "ContinueStmt", "MoveStmt",
    "ThrowStmt", "TryStmt", "CatchClause", "FreeStmt", "ExprStmt",
    "Parameter", "FunctionDecl", "Field", "StructDecl", "EnumItem", "EnumDecl",
    "DecoratorDecl", "TraitMethod", "TraitDecl", "TestDecl",
    "ImportDirective", "ExportDirective", "FromDirective", "ExternBlock",
    "Program",
]

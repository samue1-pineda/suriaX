from __future__ import annotations

from typing import Any, Optional

try:
    from .error import CompilerError, Severity
except ImportError:  # pragma: no cover - compatibility for direct execution
    from error import CompilerError, Severity


class SemanticError(CompilerError):
    """Base para los errores de la fase semántica.

    Agrupa problemas de símbolos, mutabilidad, propiedad, hooks y llamadas.
    Los errores de tipo más específicos se representan con clases propias del
    AST o del subsistema de tipos para mantener el reporte más claro.
    """

    def __init__(
        self,
        message: Any,
        code: str = "SEM000",
        line: Optional[int] = None,
        column: Optional[int] = None,
        file: Optional[str] = None,
        loc: Any = None,
    ):
        super().__init__(
            message,
            code=code,
            line=line,
            column=column,
            file=file,
            phase="semantic",
            loc=loc,
        )


class UndefinedSymbolError(SemanticError):
    """Se referencia un nombre que no existe en ningún scope visible."""

    def __init__(self, message: Any = "símbolo no definido", **kwargs: Any):
        super().__init__(message, code="SEM001", **kwargs)


class DuplicateSymbolError(SemanticError):
    """Un nombre ya está declarado en el mismo scope y espacio de nombres
    (tipos o valores, ver ``symbol_table.py``)."""

    def __init__(self, message: Any = "símbolo duplicado", **kwargs: Any):
        super().__init__(message, code="SEM002", **kwargs)


class ImmutableAssignmentError(SemanticError):
    """Se reasigna un binding declarado ``const``."""

    def __init__(self, message: Any = "asignación a un binding 'const'", **kwargs: Any):
        super().__init__(message, code="SEM003", **kwargs)


class UseAfterMoveError(SemanticError):
    """Se usa un valor después de haberlo movido (``move x;``).

    Chequeo intra-función, conservador y de una sola pasada (ver
    ``semantic/ARQUITECTURA.md`` secc. 4); puede tener falsos negativos a
    propósito — el MIR (C++) hace la verificación definitiva.
    """

    severity = Severity.PANIC

    def __init__(self, message: Any = "uso de un valor tras 'move'", **kwargs: Any):
        super().__init__(message, code="SEM004", **kwargs)


class DoubleMoveError(SemanticError):
    """Se mueve (``move x;``) un valor que ya había sido movido."""

    severity = Severity.PANIC

    def __init__(self, message: Any = "'move' duplicado sobre el mismo valor", **kwargs: Any):
        super().__init__(message, code="SEM005", **kwargs)


class InvalidHookSignatureError(SemanticError):
    """Una función con nombre "dunder" reconocido como hook
    (``__free__``/``__make__``/``__sizeof__``, ver ``semantic/hooks.py``) no
    cumple la convención de firma que le corresponde: ``__free__``/
    ``__sizeof__`` deben tomar ``ptr T`` como primer parámetro; ``__make__``
    debe devolver ``ptr T``.
    """

    def __init__(self, message: Any = "firma de hook inválida", **kwargs: Any):
        super().__init__(message, code="SEM006", **kwargs)


class DuplicateHookError(SemanticError):
    """Ya existe un hook del mismo tipo (``__free__``/``__make__``/
    ``__sizeof__``/``__print__``/``__len__``) registrado para el mismo tipo
    nominal."""

    def __init__(self, message: Any = "hook duplicado para el mismo tipo", **kwargs: Any):
        super().__init__(message, code="SEM007", **kwargs)


class CallArityError(SemanticError):
    """Una llamada pasa un número de argumentos distinto al de los
    parámetros de la función resuelta."""

    def __init__(self, message: Any = "número de argumentos incorrecto", **kwargs: Any):
        super().__init__(message, code="SEM008", **kwargs)


class LibraryNotFoundError(SemanticError):
    """No se encontró el archivo ``<lib>.libsrx`` en ninguna ruta de
    búsqueda (directorio del fuente + ``libraries.libsrx_paths`` de la
    configuración)."""

    def __init__(self, message: Any = "librería .libsrx no encontrada", **kwargs: Any):
        super().__init__(message, code="SEM009", **kwargs)


class InvalidLibraryError(SemanticError):
    """La librería ``.libsrx`` existe pero es inválida: no termina en
    ``#export <alias>``, su alias no coincide con el nombre importado, o su
    contenido tiene errores léxicos/sintácticos."""

    def __init__(self, message: Any = "librería .libsrx inválida", **kwargs: Any):
        super().__init__(message, code="SEM010", **kwargs)


class UnknownLibraryMemberError(SemanticError):
    """Se accede a un miembro (``IO.foo``) que la librería importada no
    exporta."""

    def __init__(self, message: Any = "miembro no exportado por la librería", **kwargs: Any):
        super().__init__(message, code="SEM011", **kwargs)


class UseAfterFreeError(SemanticError):
    """Uso de un valor destruido con ``free``.

    Hermano de :class:`UseAfterMoveError`: en los dos casos el dueño ya soltó
    el valor, y lo único que cambia es POR QUÉ — ``move`` lo transfirió,
    ``free`` lo destruyó. Lo detecta la misma pasada lineal
    (``semantic/memory_check.py``), así que hereda sus garantías: cero falsos
    positivos, y los caminos que el análisis conservador no ve los cubre el
    intérprete en ejecución (``RT003``).
    """

    severity = Severity.PANIC

    def __init__(self, message: Any = "uso después de 'free'", **kwargs: Any):
        super().__init__(message, code="SEM023", **kwargs)


class DoubleFreeError(SemanticError):
    """``free`` sobre un valor que ya fue destruido.

    Hermano de :class:`DoubleMoveError`. Antes solo lo veía el intérprete
    (``RT005``); ahora el camino lineal lo rechaza al compilar.
    """

    severity = Severity.PANIC

    def __init__(self, message: Any = "'free' de un valor ya destruido", **kwargs: Any):
        super().__init__(message, code="SEM024", **kwargs)


class InvalidAddressOfError(SemanticError):
    """``&expr`` sobre algo que no es un lvalue (identificador, campo o
    índice): un temporal no tiene dirección estable que tomar."""

    severity = Severity.PANIC

    def __init__(self, message: Any = "'&' requiere un lvalue", **kwargs: Any):
        super().__init__(message, code="SEM013", **kwargs)


class InvalidFreeTargetError(SemanticError):
    """``free x;`` sobre un valor cuyo tipo NO es puntero (``ptr T``):
    solo la memoria referenciada por un puntero puede liberarse."""

    severity = Severity.PANIC

    def __init__(self, message: Any = "'free' requiere un puntero", **kwargs: Any):
        super().__init__(message, code="SEM014", **kwargs)


class ReadOnlyPointerWriteError(SemanticError):
    """Escritura a través de un ``ptr T`` de solo lectura. Para mutar el
    apuntado, el puntero debe declararse ``ptr mutable T``."""

    severity = Severity.PANIC

    def __init__(self, message: Any = "escritura a través de un puntero de solo lectura", **kwargs: Any):
        super().__init__(message, code="SEM015", **kwargs)


class ExpressionTooDeepError(SemanticError):
    """Se detecta una expresión con un nivel de anidación excesivo.

    Las pasadas semánticas recorren el árbol de forma recursiva, así que un
    programa demasiado anidado puede agotar la pila de Python. Este error lo
    convierte en un diagnóstico controlado en lugar de dejar que el proceso
    se detenga con un traceback.
    """

    def __init__(self, message: Any = "construcción demasiado anidada para el análisis semántico", **kwargs: Any):
        super().__init__(message, code="SEM017", **kwargs)


class InvalidCastError(SemanticError):
    """``cast<T>(x)`` sin conversión definida: par de primitivos no
    permitido, o tipo nominal destino sin hook ``__cast__`` declarado."""

    def __init__(self, message: Any = "conversión 'cast' inválida", **kwargs: Any):
        super().__init__(message, code="SEM016", **kwargs)


class UnknownHookError(SemanticError):
    """``hook fn __x__(...)`` cuyo nombre NO pertenece al set fijo de hooks
    del compilador (``__free__``/``__make__``/``__sizeof__``/``__print__``/
    ``__len__``/``__cast__``, ver ``semantic/hooks.py``). El especificador
    ``hook`` promete un hook reconocido; para un metodo especial libre use
    ``dunder``."""

    def __init__(self, message: Any = "nombre de hook no reconocido", **kwargs: Any):
        super().__init__(message, code="SEM018", **kwargs)


class VisibilityViolationError(SemanticError):
    """Se usa un símbolo cuya reserva de visibilidad lo prohíbe en este punto:
    un ``internal`` fuera de su archivo, o un ``private`` fuera de su paquete."""

    def __init__(self, message: Any = "símbolo no visible en este punto", **kwargs: Any):
        super().__init__(message, code="SEM019", **kwargs)


class TraitNotSatisfiedError(SemanticError):
    """Un ``@impl(trait)`` no cumple el contrato: al tipo le falta un método
    dunder que el trait requiere, o la firma no coincide (con ``self``
    sustituido por el tipo que implementa). También cubre ``@impl`` de un
    trait no declarado."""

    def __init__(self, message: Any = "el tipo no satisface el trait", **kwargs: Any):
        super().__init__(message, code="SEM021", **kwargs)


class InvalidDunderSignatureError(SemanticError):
    """Un ``dunder fn`` (método especial libre del usuario) no toma un tipo
    dueño como receptor: su primer parámetro debe ser ``T`` o ``T ptr`` (T
    nominal), para poder indexarlo por tipo igual que un hook."""

    def __init__(self, message: Any = "firma de 'dunder fn' inválida", **kwargs: Any):
        super().__init__(message, code="SEM022", **kwargs)


class InvalidValueTypeError(SemanticError):
    """``void`` usado como tipo de un VALOR (variable, parámetro o campo).

    ``void`` significa "no hay valor": solo tiene sentido como tipo de
    retorno. Se comprueba en el único punto por el que pasan las tres
    posiciones de valor (``TypeBinder.bind``), no en cada una — así no puede
    quedar una sin cubrir, que es como ``struct { void v; }`` llegó a
    compilar.

    También un ARGUMENTO DE TIPO ``void`` (``Vector<void>``, ``make<void>``):
    el parámetro de tipo nombra el tipo de unos valores.
    """

    severity = Severity.PANIC

    def __init__(self, message: Any = "'void' no puede ser el tipo de un valor",
                 **kwargs: Any):
        super().__init__(message, code="SEM025", **kwargs)


class InfiniteSizeTypeError(SemanticError):
    """Un ``struct`` que se contiene a sí mismo POR VALOR.

    ``struct { S s; } S;`` no tiene tamaño finito: cada ``S`` contendría otro
    ``S``. La recursión legítima se escribe con un puntero
    (``struct { S ptr sig; } S;``), que sí tiene tamaño conocido — y es la
    misma distinción que gobierna la propiedad: un puntero no contiene, se
    refiere.
    """

    severity = Severity.PANIC

    def __init__(self, message: Any = "tipo de tamaño infinito", **kwargs: Any):
        super().__init__(message, code="SEM026", **kwargs)


class TypeArityError(SemanticError):
    """Un tipo generico usado con un numero de argumentos que no es el suyo.

    ``Vector<int, str>`` sobre un ``Vector<T>``, o ``Vector`` a secas cuando
    declara un parametro. Es la razon de que los parametros se escriban en la
    declaracion: sin ellos escritos, la aridad no seria comprobable.
    """

    severity = Severity.PANIC

    def __init__(self, message: Any = "numero de argumentos de tipo incorrecto",
                 **kwargs: Any):
        super().__init__(message, code="SEM027", **kwargs)


class IncompleteStructLiteralError(SemanticError):
    """Un literal de struct que deja campos sin valor.

    ``P{ a: 1 }`` sobre un ``struct { int a; int b; } P;`` construia un valor
    al que le FALTA ``b``: el programa compilaba y reventaba al leer ``p.b``,
    en runtime y lejos de la causa. No hay valor por defecto en suriaX —un
    campo sin escribir no tiene nada que leer—, asi que el literal es el unico
    sitio donde la ausencia se puede ver, y aqui se ve.
    """

    severity = Severity.PANIC

    def __init__(self, message: Any = "literal de struct incompleto",
                 **kwargs: Any):
        super().__init__(message, code="SEM028", **kwargs)


class NonExhaustiveMatchError(SemanticError):
    """Un ``match`` sobre un ``enum`` que deja variantes sin cubrir.

    Un ``match`` que no encaja con ninguna rama no hace nada, en silencio: el
    fallo aparece como un comportamiento que falta, no como un error, y lejos
    de la causa. Anadir una variante a un ``enum`` deja asi TODOS los ``match``
    del proyecto incompletos sin que nada lo diga — que es justo cuando mas
    falta hace saberlo.

    Es un **aviso**, no un rechazo, por dos razones: un ``match`` parcial es
    hoy un programa valido y con significado definido (no hacer nada), y el
    lenguaje no tiene comodin (``_``/``default``) con el que decir "el resto
    me da igual" — convertirlo en error obligaria a escribir ramas vacias.

    Solo se emite donde se SABE: el sujeto tiene que ser un ``enum`` conocido y
    todas las ramas tienen que nombrar variantes suyas. Si una rama es una
    expresion cualquiera, el analisis no puede decir que cubre y calla — el
    contrato de cero falsos positivos de la Semantica manda sobre la ganas de
    avisar.
    """

    severity = Severity.WARNING

    def __init__(self, message: Any = "match no exhaustivo", **kwargs: Any):
        super().__init__(message, code="SEM030", **kwargs)


class NotIndexableError(SemanticError):
    """``x[i]`` sobre un tipo que nunca puede indexarse.

    Se escribia, compilaba, y reventaba en EJECUCION con ``RT014`` — un
    programa que el sistema de tipos podia haber rechazado al leerlo. El caso
    que lo destapo es el mas natural que hay: recorrer una cadena
    (``texto[i]``) despues de medirla con ``len``.

    Solo se rechaza lo que se SABE: los primitivos, que no tienen ni pueden
    tener ``__index__``. Un tipo nominal sin el hook se deja pasar — puede
    declararlo una libreria que esta pasada aun no vio, y el contrato de cero
    falsos positivos manda.

    Tambien ESCRIBIR por indice en un ``str`` (``s[0] = 'x'``): una cadena se
    lee por indice (nativo, da un ``char``) pero es inmutable. Era ``RT014``
    al ejecutar.
    """

    def __init__(self, message: Any = "el tipo no es indexable", **kwargs: Any):
        super().__init__(message, code="SEM031", **kwargs)


class ImplicitOwnershipCopyError(SemanticError):
    """Ligar a un nombre nuevo un valor que POSEE recursos, sin ``move``.

    ``var R b = a;`` dejaba a los dos nombres con el mismo recurso y el
    destructor corría DOS veces sobre él — justo la doble liberación que el
    modelo promete que no ocurre. Un ``struct`` es un valor y ligarlo lo
    copia; pero copiar algo que tiene una obligación de destrucción no
    duplica el recurso, duplica al dueño.

    La transferencia se escribe: ``var R b = move a;``. Es la forma que la
    documentación del modelo de memoria usa desde el principio.

    Solo se rechaza cuando el valor ligado NOMBRA a otro dueño (una variable,
    un campo): un literal o el retorno de una función no tienen un segundo
    dueño del que hablar.

    ``return g;`` con ``g`` una variable GLOBAL es la misma copia: devolver
    por valor entrega una copia al llamador, y la global sigue siendo dueña
    del original hasta que el programa termina. Antes compilaba y el recurso
    se destruía dos veces (una por cada copia). Devolver un LOCAL no copia,
    lo mueve: el local muere al salir y no queda un segundo dueño. Para
    entregar la global, ``return move g;`` (la global queda movida); para
    dejarla leer, que la función devuelva un puntero (``R ptr``) y ``&g``.
    """

    def __init__(self, message: Any = "copia implícita de un valor con dueño",
                 **kwargs: Any):
        super().__init__(message, code="SEM032", **kwargs)


class ContainerOverflowError(SemanticError):
    """Se reservaron N espacios y hay mas de N ``push`` seguidos sobre ellos.

    ``int vec.Vector v[2];`` reserva DOS. El tercer ``push`` no cabe, y eso se
    puede ver sin ejecutar el programa cuando la capacidad es un literal y los
    ``push`` estan uno detras de otro en el mismo bloque: no hay condicion ni
    bucle que pueda cambiar la cuenta.

    Solo se reporta ese caso. Un ``push`` dentro de un ``if`` o de un ``while``
    depende de la ejecucion, y afirmar ahi que "no cabe" rechazaria programas
    correctos; esos siguen fallando en ejecucion, donde el vector lanza. La
    regla es la de siempre en este compilador: avisar de lo que se puede
    demostrar, callar donde habria falsos positivos, y no dejarlo pasar en
    silencio en ninguno de los dos casos.

    Que hacer: reserva mas espacio en la declaracion, o quita los ``push`` que
    sobran.
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SEM033", **kwargs)


class ThrowInDestructorError(SemanticError):
    """Un ``throw`` dentro de un ``__free__``: un destructor no puede fallar.

    Un ``__free__`` corre cuando un valor muere, y un valor también muere
    mientras un ``throw`` sube por las llamadas (el desenrollado). Si ahí el
    destructor lanzara otro, habría dos excepciones a la vez y una se
    perdería. Por eso la regla es la de C++: un destructor nunca lanza. Si
    liberar puede fallar, el fallo se registra (se imprime, se cuenta) y el
    destructor termina normalmente.

    La Semántica ve el ``throw`` escrito; si el ``__free__`` llama a algo que
    lanza, lo detecta la ejecución (``RT021``).
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SEM034", **kwargs)


class LiteralDivisionByZeroError(SemanticError):
    """``x / 0`` o ``x % 0`` con un cero ENTERO escrito en el fuente.

    Es la parte de la división por cero que se ve sin ejecutar: el texto ya
    dice que la operación no tiene resultado, y ningún ``try`` lo arregla.
    Cuando el divisor solo vale cero al ejecutar, es una excepción del
    programa (``EXC001``) que se puede atrapar como
    ``excepciones.DivisionPorCero``.
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SEM035", **kwargs)


class MoveOutOfBorrowError(SemanticError):
    """Ceder (``move``, ``return``, ``throw``) algo con destructor a lo que se
    llega a través de un puntero.

    Un puntero es un PRÉSTAMO: lo que hay detrás es de otro, que lo destruirá
    cuando le toque. Cederlo dejaría dos dueños y el valor se destruiría dos
    veces. Para leerlo se usa el puntero (``&c.dentro``); para quitárselo a su
    dueño, lo cede el dueño.
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SEM036", **kwargs)


class DanglingAddressError(SemanticError):
    """``return &x`` con ``x`` una variable (o un parámetro por valor) de la
    función que devuelve, o un campo de una.

    ``x`` muere al salir: el llamador recibiría una dirección a algo que ya no
    existe. El intérprete lo toleraba (sus celdas las recoge Python) y la VM
    lo detecta al usarlo (RT003); el error es del texto, y se dice aquí. Para
    devolver algo que sobreviva, se devuelve el VALOR, o se reserva con
    ``mem``, o se guarda en una arena y se devuelve su índice.
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SEM037", **kwargs)


class GenericOwnerCopyError(SemanticError):
    """Un GENÉRICO que copia su ``T``, instanciado con un tipo con destructor.

    ``Vector<T>.get`` devuelve una COPIA del elemento. Con ``T = int`` es lo
    correcto; con ``T = R`` (``R`` con ``__free__``) la copia y el elemento
    serían dos dueños del mismo recurso, y su destructor correría dos veces.
    El cuerpo del genérico no está mal —no sabe con qué se instanciará—: lo
    que está mal es ESTA instancia, y por eso el error sale en la llamada y
    dice dónde copia el genérico.

    La salida es una operación que PRESTE (un puntero: ``v.at(i)``) o que
    SAQUE el valor (``v.take(i)``, ``move``). Es la regla de C++ (un
    ``std::vector<std::unique_ptr<T>>`` no se copia) y la de Rust (``T:
    Clone``), dicha en el sitio de la instancia.
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SEM038", **kwargs)


class GenericNotOrderableError(SemanticError):
    """Un GENÉRICO que ORDENA su ``T`` (``a < b``), instanciado con un tipo
    que no se ordena.

    Dentro de ``fn menor<T>(T a, T b)`` o de ``Vector.sort``, ``a < b`` no se
    puede decidir: depende de con qué se instancie. Con ``T = int`` o ``T =
    str`` el orden es el nativo; con un tipo propio, el que da su ``__cmp__``.
    Un tipo sin orden —un ``struct`` sin ``__cmp__``, un ``T?``, un ``bool``—
    hace imposible ESTA instancia, y por eso el error sale en la llamada (no
    en el cuerpo del genérico, que no está mal) y dice dónde ordena.

    Se arregla declarando el orden del tipo, ``hook fn __cmp__(P ptr a, P ptr
    b) -> int``: negativo si ``a`` va antes, cero si empatan, positivo si va
    después. Es la regla de Rust (``T: Ord``) dicha en el sitio de la
    instancia, como ``SEM038``.
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SEM039", **kwargs)


class UninitializedVariableError(SemanticError):
    """``var T x;`` sin valor: toda variable nace con un valor de su tipo.

    Antes se aceptaba y ``x`` valía ``null`` aunque su tipo no lo admitiera:
    ``x + 1`` con ``var int x;`` era un fallo interno del intérprete y un
    ``bool`` sin valor tomaba la rama falsa de un ``if`` en silencio. El tipo
    prometía un ``int`` y entregaba otra cosa.

    Se rechaza en vez de dar un valor por defecto (``0``, ``false``, ``""``)
    porque un valor inventado esconde el olvido: el programa corre, con un
    dato que nadie escribió. Escribirlo cuesta tres caracteres y deja claro
    con qué empieza: ``var int x = 0;``. Si "todavía no hay valor" es un
    estado legítimo, se dice en el tipo: ``var int? x = null;``.

    No afecta a ``const type T;`` (eso declara un TIPO, no una variable) ni a
    los nombres que liga el lenguaje (``catch (e)``, ``case A(x)``, ``with``),
    que siempre nacen con un valor.
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SEM040", **kwargs)


class TemporaryMutationError(SemanticError):
    """Escribir en una COPIA temporal: el cambio se perdería al terminar la
    sentencia.

    ``v[i]`` sobre un tipo con ``__index__`` (un ``Vector``) y la llamada a una
    función que devuelve por valor entregan una COPIA, como al ligarla a una
    variable. Escribir en ella (``v[i].n = 5``, ``dame().n = 5``) o llamar
    sobre ``v[i]`` a un método que modifica su receptor (``v[i].push(x)``, que
    declara ``ptr mutable self``) cambiaría la copia, y la copia muere al
    terminar la sentencia: el programa compilaría y no haría nada.

    Antes funcionaba por accidente: el valor devuelto quedaba enlazado al
    original y la escritura llegaba al elemento guardado. Desde que devolver
    por valor copia, la única forma de modificar un elemento es pedirlo
    PRESTADO y mutable, de forma explícita: ``v.at_mut(i).n = 5`` o
    ``v.at_mut(i).push(x)`` (un ``T ptr mutable``). Un ``Dictionary`` tiene lo
    mismo por clave (``d.at_mut(k)``).

    Llamar a un método que modifica sobre el RESULTADO de una llamada
    (``abrir(...).write(...)``) sí se acepta: ese valor es nuevo y no es copia
    de nada guardado, y el método puede hacer algo más que cambiarlo (escribir
    un archivo).
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SEM041", **kwargs)


class NotCallableError(SemanticError):
    """Llamar a algo que no es una función: ``n(3)`` con ``n`` un ``int``,
    ``p.noexiste()`` sobre un tipo que no declara ese método, ``s.k(1)`` con
    ``k`` un campo que no es de tipo función.

    Antes se aceptaba en silencio: la llamada no tenía tipo y la Semántica
    "no rechaza lo que no sabe". Pero aquí sí se sabe —el tipo del valor, o
    los métodos del tipo—, y el programa fallaba al ejecutar (``RT011``) lejos
    de la causa, o hacía otra cosa. Lo único que se puede llamar es una
    función: la declarada por su nombre, un valor de tipo ``fn(...) -> R``
    (una variable, un parámetro, un campo, un elemento) o un método del tipo
    del receptor.

    Un ``(fn(...) -> R)?`` SÍ se puede llamar: si vale ``null`` es un error
    de ejecución, como leer un campo a través de un puntero nulo.
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SEM042", **kwargs)


class UnboundedGenericMemberError(SemanticError):
    """Un método, un campo o ``[]`` sobre un valor de un parámetro de tipo
    SIN cota: ``x.aplica(1)``, ``x.campo``, ``x[i]`` con ``x: T``.

    El cuerpo de un genérico se comprueba UNA vez, sin saber con qué se
    instanciará, y un ``T`` sin cota no promete nada: ningún método, ningún
    campo, ningún ``__index__``. Antes se dejaba pasar y cada instancia
    fallaba a su manera: ``RT011`` al ejecutar con un tipo que no lo tenía, o
    —peor— el tipo equivocado pasaba en silencio (``map<str>(&v, "hola")``
    metía los caracteres de la cadena en un ``Vector<int>``).

    Lo que el LENGUAJE hace por su cuenta sobre un ``T`` sigue valiendo, porque
    cada instancia lo comprueba con su tipo concreto: ``==`` (``__eq__``),
    ``<`` (``__cmp__``, ``SEM039``), ``hash`` (``__hash__``), copiar
    (``SEM038``), destruir (``__free__``) y escribirlo en un f-string. Lo que
    se rechaza es pedirle a ``T`` algo por su NOMBRE. Cuando el lenguaje tenga
    cotas (``fn f<T: trait>``), una cota dirá qué métodos tiene ``T``; hasta
    entonces, para pasar comportamiento a un genérico se pasa una función
    (``fn(T) -> R``). El indexado crudo de un bloque (``T ptr``) no entra
    aquí: ``self.datos[i]`` es memoria, no un método de ``T``.
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SEM043", **kwargs)


class InvalidFunctionValueError(SemanticError):
    """Un nombre de función que no puede usarse como VALOR.

    Son valores las funciones del módulo, las de una librería (``lib.f``) y
    los métodos de ``@impl`` escritos ``Tipo.metodo`` (el receptor ya es
    explícito: ``Punto.distancia`` es un ``fn(Punto ptr) -> int``). No lo son:

    - un ``hook``/``dunder`` (``__free__``, ``__aplica__``): los invoca el
      lenguaje o se llaman sobre su receptor, no se pasan;
    - un PROTOTIPO (``fn f(int x) -> int;``): su cuerpo lo pone el host o un
      ``#extern``, y no hay una función del programa que entregar;
    - una función GENÉRICA, ni siquiera instanciada: el valor tendría que
      llevar sus tipos y el HIR todavía no los transporta (se envuelve en una
      función con los tipos escritos);
    - un método de un tipo genérico (``Vector.push``), por lo mismo;
    - un método cuyo receptor se recibe por VALOR y tiene destructor: llamado
      como función, el llamador le cedería un dueño que el método no destruye.
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SEM044", **kwargs)


class GlobalUsedTooEarlyError(SemanticError):
    """Una sentencia de nivel superior (el valor inicial de una global) usa
    una global que se declara MÁS ABAJO.

    El nivel superior se ejecuta en el orden en que se escribe. Al iniciar
    ``var int a = b + 1;``, una ``b`` declarada después todavía no tiene
    valor: compilaba y era ``RT006`` al ejecutar ("'b' no está ligado"), lejos
    de la causa y en cada programa que la usara. Es la misma regla que en C y
    en Python (en C, ni siquiera se puede nombrar algo antes de declararlo).
    Una función sí puede usar una global declarada después: cuando se la
    llama, el nivel superior ya terminó.

    Se ve el uso DIRECTO. Una función llamada desde el valor inicial que lee
    una global posterior sigue siendo ``RT006``: decidirlo exigiría saber qué
    camino toma la función al ejecutar.
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SEM045", **kwargs)


class DuplicateCaseError(SemanticError):
    """Dos ramas de un ``match`` con el MISMO patrón.

    Gana la primera rama que encaja y el ``match`` no sigue: la segunda no se
    ejecuta nunca. Compilaba en silencio, y casi siempre es un patrón copiado
    al que le faltó cambiar algo. Se compara lo que se puede afirmar igual sin
    ejecutar: el mismo literal, la misma variante de un enum (escrita
    ``ROJO`` o ``Color.ROJO``, con o sin nombres que ligar) o el mismo nombre.
    Decisión del mantenedor: las construcciones dudosas son ERROR.
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SEM046", **kwargs)


class ExpressionWithoutEffectError(SemanticError):
    """Una sentencia que solo calcula un valor y lo tira.

    ``f;`` nombra la función sin llamarla, y ``a == b;`` compara y descarta
    el resultado (casi siempre se quería ``a = b;``): compilaban y no hacían
    nada. También un nombre, un campo o un literal sueltos (``x;``, ``5;``).
    No entra lo que puede hacer algo: una llamada, una asignación, un
    indexado o una división (pueden lanzar), ``and``/``or`` (el lado derecho
    puede ser una llamada). Decisión del mantenedor: las construcciones
    dudosas son ERROR.
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SEM047", **kwargs)


class UnreachableCodeWarning(SemanticError):
    """**Aviso**: sentencias detrás de un ``return``, ``throw``, ``break`` o
    ``continue`` del mismo bloque. Nunca se ejecutan.

    Es un AVISO (decisión del mantenedor), no un error: el programa es válido
    y hace lo que dice. Solo se mira el mismo bloque, que es lo que se ve sin
    analizar el flujo; un ``if`` cuyas dos ramas devuelven no cuenta. Se
    avisa una vez por bloque, en la primera sentencia muerta.
    """

    severity = Severity.WARNING

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SEM048", **kwargs)


class NarrowerTypeInSignatureWarning(SemanticError):
    """**Aviso**: una función de una librería se ve más que un tipo de su
    firma (``fn f() -> P`` con ``private struct P``, o un ``internal``).

    Quien puede llamar a ``f`` no puede NOMBRAR ``P``: como suriaX no tiene
    inferencia, ni siquiera puede guardar el resultado en una variable; solo
    usarlo de paso (``lib.f().n``). Es un aviso y no un error, como el lint
    ``private_interfaces`` de Rust (fue el error E0446 hasta que se vio que
    rechazaba programas correctos): el programa es válido, pero la API casi
    nunca es la que se quería. Solo en librerías; un hook no cuenta (se
    despacha por su tipo, no se llama por nombre).
    """

    severity = Severity.WARNING

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SEM049", **kwargs)


class LambdaOutOfPlaceError(SemanticError):
    """Una ``lambda`` fuera del UNICO sitio donde vale: el argumento de una
    llamada cuyo parametro esta ESCRITO como ``fn(...) -> R``.

    Una lambda lee los locales y parametros de quien la escribe sin copiarlos
    ni moverlos (captura de solo lectura). Eso es seguro sin analizar vidas
    porque NO ESCAPA: muere antes de que termine la llamada que la recibe, y
    lo que lee sigue vivo mientras tanto. Guardarla en una variable, un campo
    o un vector, devolverla, compararla, o pasarla a un parametro que no es un
    tipo funcion escrito (un ``T``, un ``(fn(...) -> R)?``, un prototipo del
    host) la dejaria vivir mas que sus capturas. Lo que si puede escapar es
    una funcion con NOMBRE, que no captura nada.
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SEM050", **kwargs)


class FunctionParameterEscapeError(SemanticError):
    """Un parametro de tipo ``fn(...) -> R`` usado de otra forma que
    LLAMARLO o PASARLO a otro parametro de tipo funcion.

    Es la otra mitad de que una lambda no escape: la lambda llega a la
    funcion por un parametro de tipo funcion, y si la funcion pudiera
    guardarlo (en un campo, una global, un vector), devolverlo o pasarlo a un
    ``T``, la lambda viviria mas que los locales que lee. Por eso un
    parametro asi es PRESTADO, como un ``ptr``: se usa durante la llamada y
    nada mas. Quien necesite guardar una funcion que recibe declara el
    parametro ``(fn(...) -> R)?``, que no admite lambdas.
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SEM051", **kwargs)


class MissingHandlerError(SemanticError):
    """Un nodo del AST llegó a una pasada que no sabe recorrerlo.

    NO es un error del programa que se compila: es un defecto del compilador.
    Se reporta como diagnóstico —y no con una excepción— por la misma razón
    que el resto de la fase: un fallo no debe tirar la compilación entera ni
    esconder los diagnósticos reales que ya se habían acumulado. Va con
    severidad ``PANIC`` para que se distinga de un error del usuario.

    Existe porque el silencio costó caro: el despacho de ``scope_resolver``
    ignoraba sin decir nada las clases que no estaban en su tabla, y por eso
    el inicializador de un ``type_decl`` cruzó el frontend entero sin que
    nadie lo mirara.
    """
    severity = Severity.PANIC

    def __init__(self, message: Any = "nodo sin handler en esta pasada",
                 **kwargs: Any):
        super().__init__(message, code="SEM000", **kwargs)


__all__ = [
    "SemanticError",
    "InvalidValueTypeError",
    "InfiniteSizeTypeError",
    "TypeArityError",
    "IncompleteStructLiteralError",
    "NonExhaustiveMatchError",
    "NotIndexableError",
    "ImplicitOwnershipCopyError",
    "MissingHandlerError",
    "LambdaOutOfPlaceError",
    "FunctionParameterEscapeError",
    "UndefinedSymbolError",
    "DuplicateSymbolError",
    "ImmutableAssignmentError",
    "UseAfterMoveError",
    "DoubleMoveError",
    "InvalidHookSignatureError",
    "DuplicateHookError",
    "CallArityError",
    "LibraryNotFoundError",
    "InvalidLibraryError",
    "UnknownLibraryMemberError",
    "UseAfterFreeError",
    "DoubleFreeError",
    "InvalidAddressOfError",
    "InvalidFreeTargetError",
    "ReadOnlyPointerWriteError",
    "InvalidCastError",
    "ExpressionTooDeepError",
    "UnknownHookError",
    "VisibilityViolationError",
    "TraitNotSatisfiedError",
    "InvalidDunderSignatureError",
    "ContainerOverflowError",
    "ThrowInDestructorError",
    "LiteralDivisionByZeroError",
    "MoveOutOfBorrowError",
    "DanglingAddressError",
    "GenericOwnerCopyError",
    "GenericNotOrderableError",
    "UninitializedVariableError",
    "TemporaryMutationError",
    "NotCallableError",
    "UnboundedGenericMemberError",
    "InvalidFunctionValueError",
    "GlobalUsedTooEarlyError",
    "DuplicateCaseError",
    "ExpressionWithoutEffectError",
    "UnreachableCodeWarning",
    "NarrowerTypeInSignatureWarning",
]

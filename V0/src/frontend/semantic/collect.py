"""Pasada 1 — Recolección: símbolos de nivel superior al scope global.

Recorre ``Program.items`` UNA sola vez, sin recursión a cuerpos de función
(``ARQUITECTURA.md`` secc. 1): registra ``fn`` / ``struct`` / ``enum`` /
imports / variables globales ANTES de que ninguna otra pasada mire un cuerpo
— así ``main()`` puede llamar a una función declarada más abajo sin
retrocesos.

También registra los *hooks* de tipo (``__free__``/``__make__``/
``__sizeof__``/``__print__``/``__len__``): son siempre declaraciones de
nivel superior (la gramática no permite ``fn`` anidada), así que esta pasada
es su lugar natural. La validación es de firma COMPLETA (parámetros y
retorno, ver ``hooks.validate_hook``). Un ``__foo__`` con forma válida pero
nombre no reconocido se registra como función normal, sin error (escribir un
dunder no es obligatorio ni cerrado).

Los ``#import``/``#from`` se resuelven DE VERDAD contra su ``.libsrx``
(``src/linker_p/``, el linker de librerías nativas, con caché): el símbolo
IMPORT queda con los exports en ``Symbol.members`` y los hooks de la
librería se fusionan en la tabla del consumidor.

``type`` (``const type int8;``) declara un tipo nominal OPACO: se registra en
el namespace de TIPOS sin miembros — su representación la aporta el backend
o sus hooks. Es la forma en que una librería publica tipos no nativos
(``int8``/``float16``...) usables como cualquier ``struct``.
"""

from __future__ import annotations

import os
from typing import Callable, Dict, Optional, Tuple

try:
    from include import ast_nodes as ast
    from include.types_ast import META_TYPE, Type, TypeKind, nominal
    from error_handler import SemanticError
except ImportError:  # pragma: no cover - ejecucion directa
    from include import ast_nodes as ast  # type: ignore
    from types_ast import META_TYPE, Type, TypeKind, nominal  # type: ignore
    import SemanticError  # type: ignore

from ... import linker_p
from . import traits as _traits
from .context import SemanticContext
from .hooks import HOOK_SPECS, HookKind, validate_hook
from .symbol_table import Symbol, SymbolKind


def run(program: ast.Program, ctx: SemanticContext) -> None:
    """Ejecuta la pasada sobre ``program`` acumulando errores en ``ctx``."""
    # '@impl(trait)' se verifica DESPUES de registrar todo (dunders y traits
    # pueden declararse en cualquier orden respecto al @impl).
    pending_impls = []
    for item in program.items:
        if isinstance(item, ast.TraitDecl):
            _collect_trait(item, ctx)
            continue
        deco = None
        if isinstance(item, ast.DecoratorDecl):
            # '@decorador decl' recolecta la declaracion decorada tal cual; el
            # decorador solo se interpreta si es '@impl' (conformidad de trait).
            deco = item
            item = item.target
        handler = _COLLECT_DISPATCH.get(item.__class__)
        if handler is not None:
            handler(item, ctx)
        if deco is not None and deco.name == "impl" and isinstance(item, ast.StructDecl):
            pending_impls.append((deco.args, item.name, deco.ln, deco.col))
        # ExternBlock / ExportDirective / statements sueltos: sin simbolo
        # de nivel superior que registrar (los statements los visita la
        # pasada 3 contra el scope global).

    for trait_names, impl_type, ln, col in pending_impls:
        _traits.check_impl(trait_names, impl_type, ctx, ln, col)


# ------------------------------------------------------------------ #
# declaraciones
# ------------------------------------------------------------------ #

def _collect_function(fn: ast.FunctionDecl, ctx: SemanticContext) -> None:
    # el compilador YA NO adivina por la forma '__x__': un hook se declara
    # explicitamente con 'hook fn' (set fijo, validado y despachado). 'dunder
    # fn' es un metodo especial LIBRE sin significado especial (se registra
    # como funcion normal); 'fn __x__' a secas tambien es funcion normal.
    if fn.specifier == "hook":
        _collect_hook(fn, ctx)
        return
    if fn.specifier == "dunder":
        _collect_dunder(fn, ctx)
        return

    param_types: Tuple[Type, ...] = tuple(
        p.restype for p in fn.params if p.restype is not None
    )
    symbol = Symbol(
        name=fn.name, kind=SymbolKind.FUNCTION, ln=fn.ln, col=fn.col,
        type=fn.return_restype, param_types=param_types,
        visibility=fn.visibility,
    )
    if not ctx.scope.define_value(symbol):
        ctx.error(SemanticError.DuplicateSymbolError(
            f"la función '{fn.name}' ya está declarada en este scope",
            line=fn.ln, column=fn.col,
        ))


def _owner_of(t: Optional[Type]) -> Optional[str]:
    """Nombre nominal 'nucleo' de un tipo, desenvolviendo ``ptr``/``?``: la
    identidad del tipo DUENO de un dunder (``__x__(T ptr self)`` -> ``T``)."""
    while t is not None and (t.kind is TypeKind.POINTER or t.kind is TypeKind.NULLABLE):
        t = t.inner
    if t is not None and t.kind is TypeKind.NOMINAL:
        return t.name
    return None


def _collect_dunder(fn: ast.FunctionDecl, ctx: SemanticContext) -> None:
    """``dunder fn __x__(T ptr self, ...)``: método especial LIBRE, indexado
    por ``(T, __x__)`` (los "hooks del usuario"). Su primer parámetro define el
    tipo dueño; sin uno nominal no se puede asociar a un tipo."""
    owner = _owner_of(fn.params[0].restype) if fn.params else None
    if owner is None:
        ctx.error(SemanticError.InvalidDunderSignatureError(
            f"'{fn.name}': un 'dunder fn' debe tomar 'T ptr' (T nominal) como "
            "primer parámetro (el tipo dueño)",
            line=fn.ln, column=fn.col,
        ))
        return
    param_types: Tuple[Type, ...] = tuple(
        p.restype for p in fn.params if p.restype is not None
    )
    symbol = Symbol(
        name=fn.name, kind=SymbolKind.DUNDER, ln=fn.ln, col=fn.col,
        type=fn.return_restype, param_types=param_types,
        hook_owner=owner, visibility=fn.visibility,
    )
    if not ctx.table.register_dunder(owner, fn.name, symbol):
        ctx.error(SemanticError.DuplicateSymbolError(
            f"el dunder '{fn.name}' ya está declarado para '{owner}'",
            line=fn.ln, column=fn.col,
        ))


def _collect_trait(trait: ast.TraitDecl, ctx: SemanticContext) -> None:
    """``@trait`` -> registra el contrato (conjunto de firmas). Los métodos
    deben tener nombre dunder (``__x__``): un método de trait siempre se
    satisface con un ``dunder fn`` homónimo."""
    for m in trait.methods:
        if not (m.name.startswith("__") and m.name.endswith("__") and len(m.name) > 4):
            ctx.error(SemanticError.TraitNotSatisfiedError(
                f"el método '{m.name}' del trait '{trait.name}' debe tener "
                "nombre dunder ('__x__')", line=m.ln, column=m.col,
            ))
    if trait.name in ctx.table.traits:
        ctx.error(SemanticError.DuplicateSymbolError(
            f"el trait '{trait.name}' ya está declarado",
            line=trait.ln, column=trait.col,
        ))
        return
    ctx.table.traits[trait.name] = _traits.build_trait_sigs(trait)


def _collect_hook(fn: ast.FunctionDecl, ctx: SemanticContext) -> None:
    # 'hook' promete un nombre del SET FIJO; si no lo es, es un error explicito
    # (antes un '__foo__' desconocido se ignoraba en silencio — ahora el
    # usuario afirmo que es un hook).
    if fn.dunder is None or fn.dunder not in HOOK_SPECS:
        ctx.error(SemanticError.UnknownHookError(
            f"'{fn.name}' no es un hook reconocido; el set es "
            f"{sorted('__' + n + '__' for n in HOOK_SPECS)}. Para un metodo "
            "especial libre usa 'dunder fn' en vez de 'hook fn'",
            line=fn.ln, column=fn.col,
        ))
        return
    owner, error_msg = validate_hook(fn, fn.dunder)
    if owner is None:
        ctx.error(SemanticError.InvalidHookSignatureError(
            f"'{fn.name}': {error_msg}", line=fn.ln, column=fn.col,
        ))
        return

    spec = HOOK_SPECS[fn.dunder]
    symbol = Symbol(
        name=fn.name, kind=SymbolKind.HOOK, ln=fn.ln, col=fn.col,
        type=fn.return_restype,
        param_types=tuple(p.restype for p in fn.params if p.restype is not None),
        hook_kind=spec.kind, hook_owner=owner, visibility=fn.visibility,
    )

    if spec.kind is HookKind.CAST:
        # __cast__ va a la TABLA DE CONVERSIONES, clave (origen, destino):
        # un tipo puede declarar tantas conversiones como pares distintos
        # (int->int8, int8->int, str->Estado...). Duplicado = mismo PAR.
        source = fn.params[0].restype if fn.params else None
        target = fn.return_restype
        if source is None or target is None:  # pragma: no cover - tipos sin resolver
            return
        if not ctx.table.register_cast(source, target, symbol):
            ctx.error(SemanticError.DuplicateHookError(
                f"ya existe un '__cast__' para '{source!r} -> {target!r}'",
                line=fn.ln, column=fn.col,
            ))
        return

    if not ctx.table.register_hook(owner, spec.kind, symbol):
        ctx.error(SemanticError.DuplicateHookError(
            f"ya existe un hook {spec.kind.name} para '{owner}'",
            line=fn.ln, column=fn.col,
        ))


def _collect_struct(node: ast.StructDecl, ctx: SemanticContext) -> None:
    members: Dict[str, Symbol] = {}
    for f in node.fields:
        if f.name in members:
            ctx.error(SemanticError.DuplicateSymbolError(
                f"campo duplicado '{f.name}' en struct '{node.name}'",
                line=f.ln, column=f.col,
            ))
            continue
        members[f.name] = Symbol(
            name=f.name, kind=SymbolKind.FIELD, ln=f.ln, col=f.col,
            type=f.restype, mutable=True,
        )
    symbol = Symbol(
        name=node.name, kind=SymbolKind.STRUCT, ln=node.ln, col=node.col,
        type=nominal(node.name), members=members, visibility=node.visibility,
    )
    if not ctx.scope.define_type(symbol):
        ctx.error(SemanticError.DuplicateSymbolError(
            f"el tipo '{node.name}' ya está declarado",
            line=node.ln, column=node.col,
        ))


def _collect_type_decl(node: ast.TypeDecl, ctx: SemanticContext) -> None:
    """``const type int8;`` -> tipo nominal OPACO, en AMBOS namespaces.

    Sin ``members``: no tiene campos que recorrer (su representación la
    aportan el backend o sus hooks). Es lo que permite a una librería
    publicar tipos NO nativos (``int8``, ``float16``...) y que el consumidor
    los use igual que un ``struct``.

    Se registra dos veces, y las dos hacen falta porque ``type`` es un tipo
    de PRIMERA CLASE (mismo patrón que los items de enum, que viven pelados
    en el namespace de valores además de en su enum):

     - en **tipos**, con el nominal que declara -> ``const int8 x;``
     - en **valores**, con tipo ``type`` -> ``return int8;`` dentro de una
       ``fn ... -> type``. Sin esto el metatipo no sería usable: una función
       que devuelve tipos no podría nombrar ninguno.
    """
    # 'const type T;' liga el nombre a ESE tipo para siempre; 'type T;' (o
    # 'var type T;') lo deja redefinible — mismo modelo que las variables.
    mutable = node.qualifier != "const"
    symbol = Symbol(
        name=node.name, kind=SymbolKind.TYPE, ln=node.ln, col=node.col,
        type=nominal(node.name), mutable=mutable, visibility=node.visibility,
    )
    if not ctx.scope.define_type(symbol):
        ctx.error(SemanticError.DuplicateSymbolError(
            f"el tipo '{node.name}' ya está declarado",
            line=node.ln, column=node.col,
        ))
        return

    as_value = Symbol(
        name=node.name, kind=SymbolKind.TYPE, ln=node.ln, col=node.col,
        type=META_TYPE, mutable=mutable, visibility=node.visibility,
    )
    if not ctx.scope.define_value(as_value):
        ctx.error(SemanticError.DuplicateSymbolError(
            f"el tipo '{node.name}' colisiona con otro símbolo del mismo scope",
            line=node.ln, column=node.col,
        ))


def _collect_enum(node: ast.EnumDecl, ctx: SemanticContext) -> None:
    enum_type = nominal(node.name)
    members: Dict[str, Symbol] = {}
    for item in node.items:
        if item.name in members:
            ctx.error(SemanticError.DuplicateSymbolError(
                f"item duplicado '{item.name}' en enum '{node.name}'",
                line=item.ln, column=item.col,
            ))
            continue
        item_sym = Symbol(
            name=item.name, kind=SymbolKind.ENUM_ITEM, ln=item.ln,
            col=item.col, type=enum_type,
        )
        members[item.name] = item_sym
        # los items tambien viven PELADOS en el namespace de valores (mismo
        # modelo que C: 'return Origen;' sin 'Cuadrante.' — es la forma de
        # TODOS los ejemplos reales, ver structs_and_control.md). Dos enums
        # con un item homonimo SI colisionan, y se reporta.
        if not ctx.scope.define_value(item_sym):
            ctx.error(SemanticError.DuplicateSymbolError(
                f"el item '{item.name}' de enum '{node.name}' colisiona con "
                "otro símbolo del mismo scope",
                line=item.ln, column=item.col,
            ))
    symbol = Symbol(
        name=node.name, kind=SymbolKind.ENUM, ln=node.ln, col=node.col,
        type=enum_type, members=members, visibility=node.visibility,
    )
    if not ctx.scope.define_type(symbol):
        ctx.error(SemanticError.DuplicateSymbolError(
            f"el tipo '{node.name}' ya está declarado",
            line=node.ln, column=node.col,
        ))


# ------------------------------------------------------------------ #
# imports (resolucion real contra .libsrx)
# ------------------------------------------------------------------ #

def _collect_import_binding(node: ast.ImportBinding, ctx: SemanticContext) -> None:
    define_import(node.name, node.source, ctx, mutable=(node.qualifier != "const"),
                  visibility=node.visibility)


def _collect_import_dir(node: ast.ImportDirective, ctx: SemanticContext) -> None:
    # '#import io.string;' sin alias liga el ULTIMO componente ('string');
    # un nombre punteado no es un identificador valido como simbolo.
    default_name = node.lib.rsplit(".", 1)[-1]
    define_import(node.alias or default_name, node, ctx, mutable=False)


def _collect_from_dir(node: ast.FromDirective, ctx: SemanticContext) -> None:
    define_import(node.alias or node.name, node, ctx, mutable=False)


def _same_package(consumer_path: Optional[str], lib_path: Optional[str]) -> bool:
    """¿El archivo consumidor y la librería viven en el MISMO paquete?

    Modelo simple y coherente con ``linker_p/packages.py`` (un paquete es una
    carpeta): mismo directorio, o el consumidor está DENTRO de la carpeta del
    paquete. Basta para la regla de ``private`` (visible entre archivos del
    mismo paquete): los hermanos de una carpeta-paquete se ven; una app que
    importa un paquete externo (otra carpeta) no ve sus ``private``.
    """
    if not consumer_path or not lib_path:
        return False
    lib_dir = lib_path if os.path.isdir(lib_path) else os.path.dirname(lib_path)
    lib_dir = os.path.abspath(lib_dir)
    cons_dir = os.path.dirname(os.path.abspath(consumer_path))
    return cons_dir == lib_dir or cons_dir.startswith(lib_dir + os.sep)


def _visible_members(members: Dict[str, Symbol], same_pkg: bool) -> Dict[str, Symbol]:
    """Miembros de una librería visibles para el consumidor. ``internal`` ya
    se filtró en el linker (``loader``); aquí solo se oculta ``private`` a un
    consumidor de OTRO paquete."""
    if same_pkg:
        return members
    return {n: s for n, s in members.items() if s.visibility != "private"}


def define_import(name: str, source, ctx: SemanticContext, *, mutable: bool,
                  visibility: Optional[str] = None) -> None:
    """Registra ``name`` como símbolo IMPORT resolviendo su ``.libsrx``.

    Pública: ``scope_resolver`` la reutiliza para un ``ImportBinding``
    declarado dentro de un cuerpo de función (mismo comportamiento, scope
    actual en vez de global).

    Si la librería no se puede cargar, el símbolo se registra igualmente
    como *opaco* (``members=None``): así el resto del análisis no produce
    una cascada de ``UndefinedSymbolError`` sobre cada uso de ``IO`` — el
    error real (librería no encontrada/ inválida) ya fue reportado una vez.
    """
    library = linker_p.load_library(
        source.lib,
        source_path=ctx.source_path, config=ctx.config,
        errors=ctx.errors, notes=ctx.notes, ln=source.ln, col=source.col,
    )

    members: Optional[Dict[str, Symbol]] = None
    sym_type = nominal(source.lib)
    if library is not None:
        # ¿el consumidor está en el mismo paquete que la librería? decide si
        # ve los símbolos 'private' (los 'internal' ya no llegan hasta aquí).
        same_pkg = _same_package(ctx.source_path, library.path)
        # registrar la unidad cargada (nombre CALIFICADO -> ruta): la fase HIR
        # emite un .phir POR unidad y el módulo principal solo las referencia.
        # La clave es 'unit' ('IO.stdp'), no 'alias' ('stdp'): dos paquetes
        # con un submódulo homónimo son dos unidades distintas.
        ctx.loaded_libraries.setdefault(library.unit, library.path)
        # importar un PAQUETE carga todos sus submódulos ('IO.stdp.print' es
        # alcanzable desde '#import IO'), así que cada uno es también una
        # unidad del programa y necesita su propio .phir. El padre no los
        # importa: la carpeta los descubre sola (ver linker_p/packages.py).
        for sub in library.subs.values():
            ctx.loaded_libraries.setdefault(sub.unit, sub.path)
        # ...y ANOTAR la resolución en el nodo, para que viaje al HIR y
        # ningún consumidor (intérprete, backend) tenga que repetirla.
        source.unit = library.unit
        if not isinstance(source, ast.FromDirective):
            source.binding = name
        # fusionar los hooks de la libreria en la tabla del consumidor:
        # 'print(x)' sobre un tipo de la libreria despacha a su '__print__'.
        # VISIBILIDAD: un 'private hook' despacha DENTRO de la libreria (donde
        # se compilo) pero NO se fusiona en un consumidor de OTRO paquete —
        # el que usa la libreria no conoce el hook, aunque las funciones que lo
        # usan sigan funcionando. 'internal' ya se filtro en el loader.
        for (owner, kind), hook_sym in library.hooks.items():
            if hook_sym.visibility == "private" and not same_pkg:
                continue
            ctx.table.register_hook(owner, kind, hook_sym)
        # ...y sus dunders (métodos de usuario): 'x.__m__()' sobre un tipo de la
        # librería despacha a su cuerpo. Misma regla de visibilidad que hooks:
        # un 'private' solo se fusiona dentro del mismo paquete.
        for (owner, dname), dunder_sym in library.dunders.items():
            if dunder_sym.visibility == "private" and not same_pkg:
                continue
            ctx.table.register_dunder(owner, dname, dunder_sym)
        # ...y su tabla de conversiones (mismo mecanismo). Un par repetido
        # entre librerías se queda con el PRIMERO (determinista por orden de
        # import); no es error del consumidor.
        for (src_t, dst_t), cast_sym in library.casts.items():
            if cast_sym.visibility == "private" and not same_pkg:
                continue
            ctx.table.register_cast(src_t, dst_t, cast_sym)
        if isinstance(source, ast.FromDirective):
            member = library.member(source.name)
            if member is not None and member.visibility == "private" and not same_pkg:
                # existe pero es 'private' y el consumidor es de otro paquete:
                # diagnostico especifico (no el generico 'no exporta').
                ctx.error(SemanticError.VisibilityViolationError(
                    f"'{source.name}' es 'private' de '{source.lib}': solo es "
                    "visible dentro de su mismo paquete",
                    line=source.ln, column=source.col,
                ))
                return
            if member is None:
                ctx.error(SemanticError.UnknownLibraryMemberError(
                    f"'{source.lib}' no exporta '{source.name}'",
                    line=source.ln, column=source.col,
                ))
            else:
                # '#from lib #import x [as y]': el simbolo importado ES el
                # export (misma firma), expuesto bajo el nombre local.
                imported = Symbol(
                    name=name, kind=member.kind, ln=source.ln, col=source.col,
                    type=member.type, param_types=member.param_types,
                    members=member.members, mutable=mutable, visibility=visibility,
                )
                if not ctx.scope.define_value(imported):
                    ctx.error(SemanticError.DuplicateSymbolError(
                        f"'{name}' ya está declarado en este scope",
                        line=source.ln, column=source.col,
                    ))
                return
        else:
            members = _visible_members(library.all_members(), same_pkg)

    symbol = Symbol(
        name=name, kind=SymbolKind.IMPORT, ln=source.ln, col=source.col,
        type=sym_type, mutable=mutable, members=members, visibility=visibility,
    )
    if not ctx.scope.define_value(symbol):
        # reimportar la MISMA libreria bajo el mismo nombre es idempotente
        # (harmless, y los ejemplos de la documentacion muestran las formas
        # 'const IO = #import IO;' y '#import IO;' juntas); solo es colision
        # si el nombre ya lo ocupa otra cosa.
        existing = ctx.scope.values.get(name)
        if existing is not None and existing.kind is SymbolKind.IMPORT \
                and existing.type == sym_type:
            return
        ctx.error(SemanticError.DuplicateSymbolError(
            f"'{name}' ya está declarado en este scope",
            line=source.ln, column=source.col,
        ))


def _collect_global_var(node: ast.VarDecl, ctx: SemanticContext) -> None:
    """Variable global: registrada aquí para que un cuerpo de función pueda
    usarla aunque se declare más abajo en el archivo (misma razón que las
    funciones). La pasada 3 valida su inicializador SIN redefinirla."""
    symbol = Symbol(
        name=node.name, kind=SymbolKind.VAR, ln=node.ln, col=node.col,
        type=node.restype, mutable=(node.qualifier != "const"),
        visibility=node.visibility,
    )
    if not ctx.scope.define_value(symbol):
        ctx.error(SemanticError.DuplicateSymbolError(
            f"'{node.name}' ya está declarado en este scope",
            line=node.ln, column=node.col,
        ))


# despacho O(1) por clase de nodo (mismo patron que _STATEMENT_DISPATCH).
_COLLECT_DISPATCH: Dict[type, Callable] = {
    ast.FunctionDecl: _collect_function,
    ast.StructDecl: _collect_struct,
    ast.EnumDecl: _collect_enum,
    ast.TypeDecl: _collect_type_decl,
    ast.ImportBinding: _collect_import_binding,
    ast.ImportDirective: _collect_import_dir,
    ast.FromDirective: _collect_from_dir,
    ast.VarDecl: _collect_global_var,
}


__all__ = ["run", "define_import"]

"""Vista LEGIBLE del HIR (``--hir-pretty``).

Es la respuesta a una medición incómoda: ``module_to_text`` —el
``text_format`` de protobuf— era el proceso **más caro de toda la fase**,
551 ms y 5,5 MB de texto para un programa de 47 k tokens, ocho veces lo que
cuesta emitir el ``.phir``. Y a cambio de ese precio daba el árbol crudo del
protobuf: veinte líneas anidadas para escribir ``return a + b``.

Esta vista tiene otro objetivo. No describe el *formato*; describe el
**programa tal como el HIR lo dejó**, que es lo que uno quiere ver al
preguntarse "¿qué le llegó al intérprete?". Una línea por sentencia, las
expresiones en línea con su tipo resuelto, y la posición del fuente a la
derecha para poder cruzarla con el código::

    unit programa.srcx   schema 2 · 4 items · 12 símbolos · 5 tipos

    types
      #1 int      #2 bool     #3 Punto    #4 Punto ptr

    fn suma(int a, int b) -> int                              @14:1
      return (a:int + b:int):int                              @15:5

    fn main() -> int                                          @28:1
      var Punto p = Punto{x: 1:int, y: 2:int}                 @29:5
      if (total:int > 2:int):bool                             @32:5
        stdp.println("mayor")                                 @33:9

``--hir-text`` no desaparece: sigue siendo la herramienta para depurar el
*wire format* (qué tag lleva qué), que es una pregunta distinta.

**La destrucción también se ve, y nadie la escribió.** Los ``drop`` al cerrar
un bloque, la marca ``⟨transfiere⟩`` de un retorno que cede la propiedad y el
``⟨temporal …⟩`` de un valor que nadie recibe son decisiones del frontend que
viajan en el HIR. En un lenguaje cuyo modelo de memoria es la característica
principal, "¿qué decidió el compilador que hay que destruir aquí?" es justo
la pregunta que se le hace a esta vista::

    fn main() -> int
      var R a = R{id: 1}                                      @14:5
      fabrica()  ⟨temporal __free__ de R⟩:R                   @16:5
      return 0                                                @17:5
      drop a  ⟨hook __free__ de R⟩

**El pool no se ve, y ese es el punto.** Desde el esquema v2 los nodos
guardan un ``type_id``; aquí se resuelve contra ``Module.types`` y se imprime
``Punto ptr mutable``, no ``#7``. Plegar el artefacto lo hizo más pequeño sin
hacerlo menos legible — siempre que exista esta vista.

Escribe en **streaming** sobre un archivo: nunca construye la cadena
completa en memoria (el texto de protobuf sí lo hacía, 24 MB para el mayor
de los programas de prueba).
"""

from __future__ import annotations

from typing import List, Optional, TextIO

#: columna donde se alinean las posiciones ``@ln:col``.
_POS_COL = 66


# --------------------------------------------------------------------------- #
# tipos
# --------------------------------------------------------------------------- #
def format_type(t, pb) -> str:
    """``Type`` protobuf -> notación de suriaX (``int ptr mutable``, ``T?``).

    Fuente ÚNICA de la notación para los lectores del HIR: la importan el
    resumen del intérprete (``runtime/interpreter/loader``) y la copian
    ``web/src/hir/schema.formatType`` y ``backend/src/view.cpp`` — un tipo no
    puede escribirse de dos maneras según quién lo imprima.

    Todo lo que participa de la IDENTIDAD del tipo se escribe. Que no fuera
    así costaba información en las dos preguntas que más se hacen al depurar:
    ``error int`` se veía como ``error`` (el tipo del valor, perdido) y
    ``Vector<int>`` como ``Vector`` (justo la distinción que hace que el
    genérico no sea decorativo).
    """
    kind = pb.TypeKind.Name(t.kind)
    if kind == "FUNCTION_TYPE":
        # 'args' son los parametros e 'inner' el retorno (ver hir.proto)
        params = ", ".join(format_type(a, pb) for a in t.args)
        return f"fn({params}) -> {format_type(t.inner, pb)}"
    if kind == "POINTER":
        return _wrapped(t.inner, pb) + (" ptr mutable" if t.mut else " ptr")
    if kind == "NULLABLE":
        return _wrapped(t.inner, pb) + "?"
    if kind == "ERROR":
        # 'error' sola (sin inner) es un tipo legítimo: solo error.
        return f"error {_wrapped(t.inner, pb)}" if t.HasField("inner") else "error"
    if kind == "NOMINAL":
        if not t.args:
            return t.name
        args = ", ".join(format_type(a, pb) for a in t.args)
        return f"{t.name}<{args}>"
    if kind == "TYPE_UNSPECIFIED":
        return "<?>"
    return kind.lower()


def _wrapped(t, pb) -> str:
    """Un tipo funcion ENVUELTO se escribe entre parentesis: un sufijo tras
    'fn(int) -> int' se pegaria al retorno ('(fn(int) -> int)?' no es
    'fn(int) -> int?')."""
    text = format_type(t, pb)
    return f"({text})" if pb.TypeKind.Name(t.kind) == "FUNCTION_TYPE" else text


class _Printer:
    """Estado de UNA impresión: stubs, pool de tipos resuelto y salida."""

    __slots__ = ("pb", "out", "types", "_kind_names", "marcas", "lineas",
                 "_citadas", "_lambdas")

    def __init__(self, module, out: TextIO, marcas: Optional[dict] = None,
                 lineas: Optional[List[str]] = None) -> None:
        from .stubs import load_hir_pb2
        self.pb = load_hir_pb2()
        self.out = out
        # el pool se resuelve UNA vez a texto: cada nodo lo consulta por
        # índice y no vuelve a formatear el mismo tipo (es el mismo motivo
        # por el que el pool existe en el artefacto).
        self.types: List[str] = [format_type(t, self.pb) for t in module.types]
        self._kind_names = {}
        # la vista de DESUGARING: (ln, col, nodo) -> de que azucar salio, y
        # las lineas del fuente para citar lo que se escribio
        self.marcas = marcas or {}
        self.lineas = lineas or []
        self._citadas: set = set()
        # las LAMBDAS de la linea que se esta armando: una expresion es una
        # sola linea, y el cuerpo de una lambda son sentencias. Se escriben
        # justo DEBAJO de la linea que las contiene (ver 'line')
        self._lambdas: list = []

    # -- utilidades ------------------------------------------------------ #
    def type_of(self, type_id: int) -> str:
        """Índice del pool -> texto. 0 (o fuera de rango) = sin tipo."""
        if 0 < type_id < len(self.types):
            return self.types[type_id]
        return ""

    def line(self, text: str, *, ln: int = 0, col: int = 0,
             indent: int = 0) -> None:
        """Una línea, con su posición alineada a la derecha si la tiene."""
        body = "  " * indent + text
        if ln:
            pad = max(1, _POS_COL - len(body))
            body = f"{body}{' ' * pad}@{ln}:{col}"
        self.out.write(body)
        self.out.write("\n")
        if self._lambdas:
            # el cuerpo de cada lambda de esta linea, debajo y sangrado: que
            # LEE del entorno (sus capturas) y sus sentencias
            pending, self._lambdas = self._lambdas, []
            for e in pending:
                lam = e.lambda_expr
                reads = (f"  ⟨lee: {', '.join(lam.captures)}⟩"
                         if lam.captures else "")
                self.line(f"cuerpo de la lambda{reads}", ln=e.ln, col=e.col,
                          indent=indent + 1)
                self.block(lam.body, indent + 2)

    # -- expresiones ----------------------------------------------------- #
    def expr(self, e) -> str:
        """La expresion, con su marca de AZUCAR si la vista la pide."""
        texto = self._expr(e)
        marca = self.marcas.get((e.ln, e.col, e.WhichOneof("node"))) if self.marcas else None
        return f"{texto}  ⟨azúcar: {marca}⟩" if marca else texto

    def _cita_la_fuente(self, s, indent: int) -> None:
        """Antes de una sentencia con azucar, la linea tal como se escribio."""
        if not self.marcas or s.ln in self._citadas:
            return
        if not any(ln == s.ln for (ln, _col, _n) in self.marcas):
            return
        self._citadas.add(s.ln)
        if 0 < s.ln <= len(self.lineas):
            self.line(f"// fuente {s.ln}: {self.lineas[s.ln - 1].strip()}",
                      indent=indent)

    def _expr(self, e) -> str:
        """Expresión -> una sola línea, con el tipo resuelto como sufijo.

        El sufijo ``:tipo`` solo aparece donde APORTA: en un literal el tipo
        es evidente y ensucia; en una llamada o una variable es la
        información que se vino a buscar.
        """
        which = e.WhichOneof("node")
        text = self._expr_text(e, which)
        tipo = self._type_suffix(e.type_id)
        if tipo and which not in ("literal", "struct_literal", "identifier",
                                  "lambda_expr"):
            return f"{text}:{tipo}"
        return text

    def _type_suffix(self, type_id: int) -> str:
        """El tipo como SUFIJO de una expresion. Un tipo funcion va entre
        parentesis: sin ellos, 'f:fn(int) -> int(3)' no deja ver donde
        termina el tipo y empieza la llamada."""
        typ = self.type_of(type_id)
        return f"({typ})" if typ.startswith("fn(") else typ

    def _expr_text(self, e, which: str) -> str:
        if which == "literal":
            return self._literal(e.literal)
        if which == "identifier":
            tipo = self._type_suffix(e.type_id)
            return f"{e.identifier.name}:{tipo}" if tipo else e.identifier.name
        if which == "binary":
            return (f"({self.expr(e.binary.left)} {e.binary.op} "
                    f"{self.expr(e.binary.right)})")
        if which == "unary":
            return f"({e.unary.op} {self.expr(e.unary.operand)})"
        if which == "assignment":
            return (f"{self.expr(e.assignment.target)} = "
                    f"{self.expr(e.assignment.value)}"
                    + ("  ⟨destruye el viejo⟩" if e.assignment.drops_old else ""))
        if which == "call":
            args = ", ".join(self.expr(a) for a in e.call.args)
            call = f"{self.expr(e.call.callee)}({args})"
            return call + self._hook(e.call.hook) + self._temp(e.call.temp_drop)
        if which == "index":
            return f"{self.expr(e.index.obj)}[{self.expr(e.index.index)}]"
        if which == "member":
            return f"{self.expr(e.member.obj)}.{e.member.member}"
        if which == "cast_expr":
            destino = format_type(e.cast_expr.type, self.pb)
            return (f"cast<{destino}>({self.expr(e.cast_expr.value)})"
                    f"{self._hook(e.cast_expr.hook)}")
        if which == "sizeof":
            return (f"sizeof({format_type(e.sizeof.type, self.pb)})"
                    f"{self._hook(e.sizeof.hook)}")
        if which == "move_expr":
            return f"move {self.expr(e.move_expr.operand)}"
        if which == "addr_of":
            marca = "&mut " if e.addr_of.mut else "&"
            return f"{marca}{self.expr(e.addr_of.operand)}"
        if which == "struct_literal":
            campos = ", ".join(
                f"{name}: {self.expr(value)}"
                for name, value in zip(e.struct_literal.field_names,
                                       e.struct_literal.values))
            return (f"{e.struct_literal.type_name}{{{campos}}}"
                    + self._temp(e.struct_literal.temp_drop))
        if which == "lambda_expr":
            # la FIRMA en linea (ya es su tipo); el cuerpo, debajo
            self._lambdas.append(e)
            lam = e.lambda_expr
            params = ", ".join(f"{self.type_of(p.type_id)} {p.name}"
                               for p in lam.params)
            ret = self.type_of(lam.return_type_id) or "void"
            return f"lambda({params}) -> {ret}"
        if which == "interp":
            partes = []
            for part in e.interp.parts:
                if part.WhichOneof("part") == "text":
                    partes.append(part.text)
                else:
                    formato = ("!r" if part.repr else "") + \
                        (":" + part.spec if part.spec else "")
                    partes.append("{" + self.expr(part.expr) + formato + "}")
            return 'f"' + "".join(partes) + '"'
        return f"<{which or 'vacío'}>"

    def _literal(self, lit) -> str:
        which = lit.WhichOneof("value")
        if which == "str_value":
            return f'"{lit.str_value}"' if lit.kind == "str" else f"'{lit.str_value}'"
        if which == "int_value":
            return str(lit.int_value)
        if which == "float_value":
            return repr(lit.float_value)
        if which == "bool_value":
            return "true" if lit.bool_value else "false"
        return "null"

    def _hook(self, hook) -> str:
        """Anotación del hook enlazado: la decisión que tomó la Semántica y
        que el intérprete ejecuta sin volver a decidir."""
        if not hook.owner_type:
            return ""
        nombre = hook.hook_name or self._hook_kind_name(hook.kind)
        return f"  ⟨hook {nombre} de {hook.owner_type}⟩"

    def _temp(self, hook) -> str:
        """El ``__free__`` de un valor que POSEE recursos y que nadie recibe:
        el frontend lo ata a la expresión para que muera al terminar la
        sentencia. Se marca distinto del hook disparado por la sintaxis
        porque responde a otra pregunta."""
        if not hook.owner_type:
            return ""
        nombre = hook.hook_name or self._hook_kind_name(hook.kind)
        return f"  ⟨temporal {nombre} de {hook.owner_type}⟩"

    def _hook_kind_name(self, kind: int) -> str:
        cached = self._kind_names.get(kind)
        if cached is None:
            cached = "__" + self.pb.HookKind.Name(kind).lower() + "__"
            self._kind_names[kind] = cached
        return cached

    # -- sentencias ------------------------------------------------------ #
    def block(self, b, indent: int) -> None:
        for stmt in b.statements:
            self.stmt(stmt, indent)
        # Los drops los INSERTA el compilador al cerrar el bloque: nadie los
        # escribe. Verlos es la única forma de contestar "¿qué decidió el
        # frontend que hay que destruir aquí?" sin leer el protobuf crudo —
        # y en un lenguaje cuyo modelo de memoria es la característica
        # principal, esa es justo la pregunta.
        for drop in b.drops:
            como = "  ⟨por su tipo⟩" if drop.by_type else self._hook(drop.hook)
            self.line(f"drop {'.'.join(drop.path)}{como}", indent=indent)

    def stmt(self, s, indent: int) -> None:
        which = s.WhichOneof("node")
        ln, col = s.ln, s.col
        self._cita_la_fuente(s, indent)
        marca = self.marcas.get((ln, col, which)) if self.marcas else None
        if marca:
            self.line(f"⟨azúcar: {marca}⟩", indent=indent)

        if which == "var_decl":
            v = s.var_decl
            tipo = self.type_of(v.type_id)
            cabeza = f"{v.qualifier or 'var'} {tipo + ' ' if tipo else ''}{v.name}"
            if v.HasField("value"):
                self.line(f"{cabeza} = {self.expr(v.value)}", ln=ln, col=col,
                          indent=indent)
            else:
                self.line(cabeza, ln=ln, col=col, indent=indent)
        elif which == "expr_stmt":
            self.line(self.expr(s.expr_stmt.expr), ln=ln, col=col, indent=indent)
        elif which == "return_stmt":
            valor = (f" {self.expr(s.return_stmt.value)}"
                     if s.return_stmt.HasField("value") else "")
            # 'transfers': la propiedad pasa al llamador y el ámbito que lo
            # tenía NO debe destruirlo. Es una decisión del frontend, y sin
            # verla los drops de arriba parecen incompletos.
            marca = "  ⟨transfiere⟩" if s.return_stmt.transfers else ""
            self.line(f"return{valor}{marca}", ln=ln, col=col, indent=indent)
        elif which == "if_stmt":
            self._if(s.if_stmt, indent, ln, col)
        elif which == "while_stmt":
            self.line(f"while {self.expr(s.while_stmt.condition)}", ln=ln,
                      col=col, indent=indent)
            self.block(s.while_stmt.body, indent + 1)
        elif which == "match_stmt":
            self.line(f"match {self.expr(s.match_stmt.subject)}", ln=ln,
                      col=col, indent=indent)
            for arm in s.match_stmt.cases:
                self.line(f"case {self.expr(arm.pattern)}", indent=indent + 1)
                self.stmt(arm.body, indent + 2)
        elif which == "block":
            self.line("{", ln=ln, col=col, indent=indent)
            self.block(s.block, indent + 1)
            self.line("}", indent=indent)
        elif which == "break_stmt":
            self.line("break", ln=ln, col=col, indent=indent)
        elif which == "continue_stmt":
            self.line("continue", ln=ln, col=col, indent=indent)
        elif which == "move_stmt":
            self.line(f"move {self.expr(s.move_stmt.target)}", ln=ln, col=col,
                      indent=indent)
        elif which == "free_stmt":
            self.line(f"free {self.expr(s.free_stmt.target)}"
                      f"{self._hook(s.free_stmt.hook)}", ln=ln, col=col,
                      indent=indent)
        elif which == "throw_stmt":
            self.line(f"throw {self.expr(s.throw_stmt.value)}", ln=ln, col=col,
                      indent=indent)
        elif which == "expect_stmt":
            self.line(f"expect {self.expr(s.expect_stmt.condition)}", ln=ln, col=col,
                      indent=indent)
            if s.expect_stmt.HasField("body"):
                self.block(s.expect_stmt.body, indent + 1)
        elif which == "try_stmt":
            self.line("try", ln=ln, col=col, indent=indent)
            self.block(s.try_stmt.try_block, indent + 1)
            # las ramas se prueban EN ORDEN y el filtro es opcional: una rama
            # sin 'type' atrapa cualquier valor. Imprimir el tipo importa
            # porque es lo que decide cuál rama gana.
            for rama in s.try_stmt.catches:
                filtro = (f"{format_type(rama.type, self.pb)} "
                          if rama.HasField("type") else "")
                self.line(f"catch ({filtro}{rama.name})", indent=indent)
                self.block(rama.block, indent + 1)
            if s.try_stmt.HasField("finally_block"):
                self.line("finally", indent=indent)
                self.block(s.try_stmt.finally_block, indent + 1)
        elif which == "type_decl":
            t = s.type_decl
            valor = f" = {self.expr(t.value)}" if t.HasField("value") else ""
            self.line(f"{t.qualifier or 'const'} type {t.name}{valor}", ln=ln,
                      col=col, indent=indent)
        elif which == "import_binding":
            b = s.import_binding
            miembro = f".{b.member}" if b.member else ""
            self.line(f"bind {b.name} <- {b.lib}{miembro}", ln=ln, col=col,
                      indent=indent)
        else:
            self.line(f"<{which or 'vacío'}>", ln=ln, col=col, indent=indent)

    def _if(self, node, indent: int, ln: int, col: int) -> None:
        self.line(f"if {self.expr(node.condition)}", ln=ln, col=col,
                  indent=indent)
        self.block(node.then_block, indent + 1)
        rama = node.WhichOneof("else_branch")
        if rama == "else_block":
            self.line("else", indent=indent)
            self.block(node.else_block, indent + 1)
        elif rama == "else_if":
            self.line("else if " + self.expr(node.else_if.condition),
                      indent=indent)
            self.block(node.else_if.then_block, indent + 1)
            self._if_tail(node.else_if, indent)

    def _if_tail(self, node, indent: int) -> None:
        rama = node.WhichOneof("else_branch")
        if rama == "else_block":
            self.line("else", indent=indent)
            self.block(node.else_block, indent + 1)
        elif rama == "else_if":
            self.line("else if " + self.expr(node.else_if.condition),
                      indent=indent)
            self.block(node.else_if.then_block, indent + 1)
            self._if_tail(node.else_if, indent)

    # -- declaraciones --------------------------------------------------- #
    def decl(self, d) -> None:
        which = d.WhichOneof("node")
        if which == "function":
            self._function(d.function, d.ln, d.col)
        elif which == "struct_decl":
            campos = ", ".join(f"{self.type_of(f.type_id)} {f.name}"
                               for f in d.struct_decl.fields)
            self.line(f"struct {d.struct_decl.name} {{ {campos} }}", ln=d.ln,
                      col=d.col)
            self.out.write("\n")
        elif which == "enum_decl":
            # Una variante con PAYLOAD no es un entero sino un constructor que
            # se invoca. Escribir sus tipos es lo que distingue 'Numero(int)'
            # de un 'Numero' auto-numerado — sin ellos las dos formas del enum
            # se leen igual, que es justo lo que el esquema evita.
            items = ", ".join(
                item.name
                + ("(" + ", ".join(self.type_of(t) for t in item.payload_type_ids) + ")"
                   if item.payload_type_ids
                   else (f" = {self.expr(item.value)}"
                         if item.HasField("value") else ""))
                for item in d.enum_decl.items)
            self.line(f"enum {d.enum_decl.name} {{ {items} }}", ln=d.ln, col=d.col)
            self.out.write("\n")
        elif which == "import_directive":
            i = d.import_directive
            alias = f" as {i.alias}" if i.alias else ""
            self.line(f"import {i.lib}{alias}   -> unidad '{i.unit}', liga "
                      f"'{i.binding}'", ln=d.ln, col=d.col)
        elif which == "from_directive":
            f = d.from_directive
            alias = f" as {f.alias}" if f.alias else ""
            self.line(f"from {f.lib} import {f.name}{alias}   -> unidad "
                      f"'{f.unit}'", ln=d.ln, col=d.col)
        elif which == "export_directive":
            e = d.export_directive
            paquete = "package " if e.package else ""
            self.line(f"export {paquete}as {e.alias}", ln=d.ln, col=d.col)
        elif which == "extern_block":
            lineas = d.extern_block.raw.count("\n") + 1
            self.line(f"extern {d.extern_block.target} {{ … {lineas} líneas }}",
                      ln=d.ln, col=d.col)
        elif which == "test_decl":
            self.line(f'test "{d.test_decl.name}"', ln=d.ln, col=d.col)
            self.block(d.test_decl.body, 1)
            if d.test_decl.HasField("errfinally"):
                self.line("errfinally")
                self.block(d.test_decl.errfinally, 1)
            if d.test_decl.HasField("finally_block"):
                self.line("finally")
                self.block(d.test_decl.finally_block, 1)
            self.out.write("\n")
        elif which == "statement":
            self.stmt(d.statement, 0)
        else:
            self.line(f"<{which or 'vacío'}>", ln=d.ln, col=d.col)

    def _function(self, fn, ln: int, col: int) -> None:
        params = ", ".join(f"{self.type_of(p.type_id)} {p.name}"
                           for p in fn.params)
        retorno = self.type_of(fn.return_type_id) or "void"
        marca = ""
        if fn.decorator:
            marca += f"@{fn.decorator} "
        if fn.dunder:
            marca += "dunder "
        if not fn.HasField("body"):
            self.line(f"{marca}fn {fn.name}({params}) -> {retorno};   "
                      f"(prototipo: lo aporta el host)", ln=ln, col=col)
            self.out.write("\n")
            return
        self.line(f"{marca}fn {fn.name}({params}) -> {retorno}", ln=ln, col=col)
        self.block(fn.body, 1)
        self.out.write("\n")


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
def write_pretty(module, out: TextIO, *, marcas: Optional[dict] = None,
                 lineas: Optional[List[str]] = None) -> None:
    """Escribe la vista legible de ``module`` en ``out``, en streaming.

    Con ``marcas`` (``(ln, col, nodo) -> azucar``) y las ``lineas`` del
    fuente es la vista de DESUGARING: antes de cada sentencia que salio de un
    azucar, la linea como se escribio, y cada nodo fabricado marcado con de
    que azucar viene."""
    p = _Printer(module, out, marcas, lineas)
    pb = p.pb

    simbolos = len(module.symbols.types) + len(module.symbols.values)
    out.write(f"unit {module.source_file or '<sin nombre>'}   "
              f"schema {module.schema_version} · {len(module.items)} items · "
              f"{simbolos} símbolos · {max(len(module.types) - 1, 0)} tipos")
    if module.libraries:
        out.write(f" · {len(module.libraries)} librerías")
    out.write("\n\n")

    # el POOL de tipos, que es lo que hace legible todo lo de abajo
    if len(module.types) > 1:
        out.write("types\n")
        for i, texto in enumerate(p.types):
            if i:
                out.write(f"  #{i:<3} {texto}\n")
        out.write("\n")

    if module.libraries:
        out.write("libs\n")
        for lib in module.libraries:
            out.write(f"  {lib.alias} -> {lib.phir}\n")
        out.write("\n")

    hooks = module.symbols.hooks
    casts = module.symbols.casts
    if hooks or casts:
        out.write("hooks\n")
        for h in hooks:
            nombre = h.hook_name or p._hook_kind_name(h.kind)
            origen = f"   (extensión '{h.extension}')" if h.extension else ""
            out.write(f"  {nombre} de {h.owner_type}{origen}\n")
        for c in casts:
            origen = (format_type(c.param_types[0], pb)
                      if c.param_types else "<?>")
            out.write(f"  __cast__ {origen} -> {format_type(c.type, pb)}\n")
        out.write("\n")

    for decl in module.items:
        p.decl(decl)


def pretty(module) -> str:
    """La vista legible como cadena. Para tests y para quien la quiera en
    memoria; el camino normal (``--hir-pretty``) escribe a archivo."""
    import io
    buffer = io.StringIO()
    write_pretty(module, buffer)
    return buffer.getvalue()


__all__ = ["format_type", "pretty", "write_pretty"]

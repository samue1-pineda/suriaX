# Frontend (Python)

El frontend de suriaX, escrito en Python, va del código fuente al **HIR**
serializado en protobuf.

observe el pipeline global en [ARCHITECTURE.md](../ARCHITECTURE.md).

```
.srcx → source_reader → Lexer → Parser → AST → AST-tipado → Semántica → HIR(protobuf)
```

## Estado actual

| Fase          | Estado     | Notas |
|---------------|------------|-------|
| source_reader | funcional  | UTF-8 → Unicode, normaliza saltos de línea. Un fuente que no es UTF-8 es `LEX008`. |
| Lexer         | funcional  | Una pasada; comentarios, interpolación, `#extern cpp{}`. |
| Parser        | funcional  | Descenso recursivo LL(k≤2) + Pratt, recuperación en modo pánico. Ver [su diseño](../V0/src/frontend/parser/ARQUITECTURA.md). |
| AST           | funcional  | `--emit-ast-json`, `#test parser`. |
| AST-tipado    | funcional  | Tipado estático, fuerte y nominal; `--emit-ast-json` lo vuelca anotado. |
| Semántica     | funcional  | Símbolos y scopes, tipos, propiedad (`move`/`free`), hooks, librerías. Ver [su diseño](../V0/src/frontend/semantic/ARQUITECTURA.md). |
| HIR (protobuf)| funcional  | Codec propio, sin dependencias. Ver [hir.md](hir.md). |

## Lexer (lo que ya funciona)

- **Decodificación** UTF-8 una sola vez (`source_reader`).
- **Scanners modulares** orquestados por `lexer.py` con dispatch por
  carácter inicial: identificadores/keywords, números, strings/chars,
  operadores, directivas/comentarios.
- **Comentarios** `//` y `/- -/` saltados en el mismo paso.
- **Interpolación de strings** solo con prefijo explícito (`f"hola{a}"`;
  una cadena plana `"..."` nunca interpola) y **bloque crudo** `#extern cpp{}`.
- **Recuperación de errores**: emite token `ERROR` y continúa.

Salida: `list[Token]` terminada en `EOF`. Detalle de tokens en
[gramar/t_types.md](gramar/t_types.md); gramática en
[gramar/grammar.ebnf](gramar/grammar.ebnf).

## Pendiente

Lo que falla hoy en el frontend está en [c_errorstfix.md](../c_errorstfix.md).
El plan está en
[ROADMAP.md](../ROADMAP.md).

# Frontend (Python)

El frontend de suriaX, escrito en Python, va del código fuente al **HIR**
serializado en protobuf.

observe el pipeline global en [ARCHITECTURE.md](../ARCHITECTURE.md).

```
.srcx → source_reader → Lexer → Parser → AST → AST-tipado → Semántica → HIR(protobuf)
```

## Estado actual

| Fase          | Estado            | Notas |
|---------------|-------------------|-------|
| source_reader |  funcional      | UTF-8 → Unicode, normaliza saltos de línea. |
| Lexer         |  funcional      | Una pasada; comentarios, interpolación, `#extern cpp{}`. |
| Parser        |  solo recibe tokens | Cursor listo (peek/advance/expect); orquesta `#test lexer`. |
| AST           |  pendiente       | añadir interaccion con JSON para debugging|
| AST-tipado    |  pendiente       | Tipado estático fuerte y nominal. |
| Semántica     |  pendiente       | Símbolos, scopes, modelo de memoria. |
| HIR (protobuf)|  pendiente       | Puente Python → C++. |

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

## TODO

- [ ] Parser de descenso recursivo + Pratt (expresiones con precedencia).
- [ ] Construcción del AST.
- [ ] Anotación de tipos (AST-tipado) — sistema nominal.
- [ ] Análisis semántico (símbolos, regiones, move).
- [ ] Emisión del HIR en protobuf.

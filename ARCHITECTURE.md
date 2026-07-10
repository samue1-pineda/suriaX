# Arquitectura de suriaX

Este documento describe el **pipeline interno** del compilador y cómo se reparte
entre los dos mundos del proyecto: el **frontend en Python** y el
**backend en C++**. El objetivo educativo del lenguaje (visualizar qué entrega
cada etapa) hace que estas fronteras sean explícitas.

> Estado: **Pre-Alpha (V.0.0.1)**

## Visión general del pipeline

```
                         archivo .srcx / .libsrx
                                   │
                                   ▼
  ┌───────────────────────── PYTHON · frontend ──────────────────────────┐

     source_reader ─▶ Lexer ─▶ Parser ─▶ AST ─▶ AST-tipado ─▶ Semántica
     (UTF-8 → Unicode)                                              │
                                                                    ▼
                                                             HIR (protobuf)

  └──────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼   HIR serializado en protobuf
                                   │   (puente Python → C++)
  ┌────────────────────────── C++ · backend ─────────────────────────────┐

     HIR ─▶ MIR lowering ─▶ Backend (LLVM IR) ─▶ objeto ─▶ linker
                                   │
                                   ▼   target según compilerconfig
              IS_WEB → .wasm       IS_WIN32 → .exe       IS_LINUX → .o

  └──────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
                          ejecutable / módulo
```

## Frontend (Python)

| Fase | Entrada → Salida | Responsabilidad |
|------|------------------|-----------------|
| **source_reader** | bytes → `str` Unicode | Decodifica UTF-8 (una vez), normaliza saltos de línea. No tokeniza. |
| **Lexer** | `str` → `list[Token]` | Tokeniza en una pasada; salta comentarios; reconoce interpolación de strings y el bloque crudo `#extern cpp{}`. Termina en `EOF`. |
| **Parser** | `list[Token]` → AST | Descenso recursivo + Pratt |
| **AST** | tokens → árbol | Representación sintáctica del programa. |
| **AST-tipado** | AST → AST con tipos | Anotación de tipos (sistema **estático fuerte y nominal**). |
| **Semántica** | AST-tipado → AST validado | Resolución de símbolos, scopes, reglas del modelo de memoria (regiones, move). |
| **HIR (protobuf)** | AST validado → HIR | Representación intermedia **serializada en protobuf**, este es el puente Python → C++. |

El **sistema de tipos** no es una fase única: opera transversalmente sobre AST,
AST-tipado y semántica, y enriquece una tabla de símbolos persistente que viaja
serializada dentro del HIR.

## Backend (C++)

| Fase | Entrada → Salida | Responsabilidad |
|------|------------------|-----------------|
| **MIR lowering** | HIR (protobuf) → MIR | Baja el HIR a una IR de más bajo nivel con control de flujo explícito y las verificaciones del modelo de memoria (lifetimes de regiones, move). |
| **Backend (LLVM IR)** | MIR → LLVM IR | Genera **LLVM IR** (LLVM-22) y, a partir de él, el objeto del target. |
| **Targets** | LLVM IR → artefacto | de acuerdo a la `compilerconfig` obtenida: `IS_WEB`→**wASM**, `IS_WIN32`→**.exe**, `IS_LINUX`→**.o**. |
| **Linker** | objeto(s) → ejecutable | Etapa **final dentro del backend C++**: enlaza el/los objeto(s) y produce el ejecutable. `compilerconfig` aporta rutas/flags. |

## El puente: HIR en protobuf

La frontera Python ↔ C++ se cruza con un **HIR serializado en protobuf** facilitando:

- mantener un contexto semántico persistente (tabla de símbolos enriquecida con
  tipos, mutabilidad e información de regiones/propiedad) a través de IRs.
- desacoplar el frontend del backend (versionado de esquema).
- reconstruir parcialmente el contexto en C++ para el lowering a MIR.

## Interoperabilidad C++: `#extern cpp{ ... }`

El bloque `#extern cpp{ ... }` incrusta codigo C++ . El **lexer lo captura crudo**
(token `RAW_BLOCK`) sin tokenizarlo con las reglas de suriaX; el contenido viaja
intacto hasta el backend C++, que lo compila e integra vía los *bindings*
(pybind11). La validación del C++ ocurre en el backend, no en el frontend.

## `compilerconfig` y la selección de target

`compilerconfig.py` es transversal a la compilación:

- detecta plataforma y dependencias (LLVM-22 vía `llvm-config`, protobuf,
  pybind11, pyyaml).
- lee/genera el formato de compilación `.suriaX_config.yaml`.
- expone los flags (`IS_WEB`, `IS_WIN32`, `IS_LINUX`) que el backend consulta
  para elegir el target y, finalmente, orquestar el linker.

## Manejo de errores

Cada fase tiene su jerarquía de errores con códigos estables (`LEXxxx`,
`PARxxx`, `ASTxxx`, `HIRxxx`, ...) bajo `V0/error_handler/`, todos derivados de
`CompilerError`. Esto permite reportes uniformes y serializables a lo largo del
pipeline.

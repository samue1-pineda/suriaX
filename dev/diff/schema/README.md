# El esquema 1 del HIR, tal como era

[`hir_v1_original.proto`](hir_v1_original.proto) es una copia **literal** de
`V0/src/HIR/proto/hir.proto` en el commit `8b8e65e` (el último con
`schema_version == 1`), sacada con:

```console
git show 8b8e65e:V0/src/HIR/proto/hir.proto > dev/diff/schema/hir_v1_original.proto
```

(sha256 `7b2e8a8a992aaff516b66dbf0dfef8bad98244b6e19a423657a5cc0bbeb91b14`, el
mismo que el del blob del commit). Es una **referencia histórica**: ningún
código la lee. La fuente única del esquema sigue siendo `hir.proto`.

## Por qué está aquí

Del esquema 1 al 2 cambió una sola cosa: el **pool de tipos**. En el 1 cada
nodo llevaba su `Type` inline (`Expr.restype`, `VarDecl.type`,
`Parameter.type`, `FunctionDecl.return_type`, `Field.type`); en el 2 el
`Module` lleva `types` (campo 6) y los nodos un índice (`type_id`,
`return_type_id`). Al estar versionado, el 1 puede seguir funcionando: hoy el
emisor lo escribe con `--hir-schema 1` y los tres lectores (intérprete, VM y
web) lo aceptan y lo normalizan al cargarlo. Ver la cabecera de `hir.proto` y
`documentation/source/hir.rst`.

## En qué se diferencia del esquema 1 que se emite hoy

Lo que emite `--hir-schema 1` es el esquema 1 **adaptado a hoy**: el
`hir.proto` actual con `schema_version = 1`, sin pool y con cada tipo inline.

| | 1 original (este archivo) | 1 adaptado (`--hir-schema 1`) |
|---|---|---|
| Tipos de los nodos | inline: `Expr.restype = 3`, `VarDecl.type = 2`, `Parameter.type = 1`, `FunctionDecl.return_type = 3`, `Field.type = 1` | los **mismos campos, con el mismo tag y el mismo significado** (volvieron de `reserved`) |
| Tipos que nacieron después | no existían | gemelos inline con tag **nuevo**: `LambdaExpr.return_type = 5`, `EnumItem.payload_types = 4` |
| `Module.types`, `type_id` | no existían | no se escriben (un v1 que los traiga se rechaza) |
| El resto del lenguaje | el de agosto de 2026 | el de hoy: `Type.args`, `BYTE`, `FUNCTION_TYPE`, `MoveExpr`, `LambdaExpr`, `ExpectStmt`, `Block.drops`, los temporales (`temp_drop`), `ReturnStmt.transfers`, `CaseArm.binds`, `type_params`, `hook_name`/`EXTENDED`, `ExternBlock.requires`... |
| `try` | una sola rama: `TryStmt.catch_name = 2`, `catch_block = 3` | N ramas filtradas: `catches = 4` (`CatchClause`) y `finally_block = 5`; los tags 2 y 3 siguen `reserved` |
| `HookKind` | `MAKE = 2` | `2` está `reserved` (se retiró con las regiones) |

## Lo que NO se garantiza

Un `.phir` escrito por el compilador **de `8b8e65e`** dice `schema_version: 1`
igual que uno de `--hir-schema 1`, y el número no los distingue. Los lectores
de hoy leen bien el **adaptado**; el original **no** es una entrada soportada:

- su `try` usa los tags 2 y 3, que hoy están reservados. Un lector los salta
  como campos desconocidos y vería un `try` sin ramas (*inferido del código de
  los tres lectores; no se ejecutó con un `.phir` real de entonces*: aquel
  compilador emitía con `protoc` + `google.protobuf`, y el paquete de Python
  no está instalado en esta máquina);
- `HookKind = 2` (`__make__`) ya no tiene nombre;
- todo lo que el lenguaje ganó después llega ausente (sin `drops`, sin
  temporales), que describe un programa de otra época, no el mismo.

Esta copia sirve para eso: para que se vea, campo a campo, qué es "el esquema
1" y qué se adaptó.

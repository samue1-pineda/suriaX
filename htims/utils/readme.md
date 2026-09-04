# `htims/utils/` — herramientas para escribir hooks

Para el **usuario** que declara hooks, no para el compilador: el compilador
usa `htims/declarations.py` directamente y no importa nada de esta carpeta.

| archivo | qué trae |
|---|---|
| `check.py` | Verifica tus declaraciones **sin compilar** un `.srcx`, con el mismo escaneo que usa el compilador. `check(ruta)` devuelve `(declaraciones, errores)`; `report(...)` los imprime; `archivos(...)` lista los `.py` que se escanearían. CLI: `python -m htims.utils.check extensions/calls/`. |
| `srcx.py` | La línea `hook fn ... { }` que hay que escribir en el `.srcx` para implementar cada firma. `stub(decl)` una, `stubs(decls)` todas agrupadas por dueño. CLI: `python -m htims.utils.srcx extensions/calls/`. |
| `cxx.py` | El **prototipo C++** que `logic_dir` tendrá que implementar, para las firmas con `cxx=True`. `cxx_type` traduce un tipo, `prototype` una declaración, `header` la cabecera entera. Un tipo sin representación decidida en C++ —`str`, nullables, `error T`, genéricos— se reporta en vez de traducirse. CLI: `python -m htims.utils.cxx extensions/calls/ > extensions/logic/hooks.h`. |

`srcx.py` y `cxx.py` son los dos lados del mismo contrato: de una declaración
salen la implementación en el lenguaje y la declaración nativa, sin copiar la
firma a mano a ninguno de los dos.

**No hay un constructor de firmas** (`ptr("Body", mutable=True)`): el escaneo
exige que cada argumento del decorador sea un **literal** —es la condición
para no ejecutar tu archivo al compilar—, así que una llamada ahí produce
`EXT025`. Las firmas se escriben como cadenas.

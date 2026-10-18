# Reproducciones de los errores conocidos

Un programa mínimo por cada error abierto de
[`c_errorstfix.md`](../../c_errorstfix.md). Cada entrada de ese documento
dice qué programa de aquí lo muestra y qué sale hoy.

## Cómo se usan

Desde la raíz del repositorio (Git Bash en Windows, o cualquier shell en
Linux):

```bash
bash dev/repros/run.sh vm_mem_take            # V0 + intérprete y V0 + VM
bash dev/repros/run.sh web_test w             # el target web (WebAssembly)
bash dev/repros/run.sh v1_exponente v1        # la V1 compilando el programa
bash dev/repros/run.sh limites/l05_for i      # un límite del lenguaje
```

| Motor | Qué corre |
|---|---|
| `i` | `python V0/main.py prog.srcx --run interpreter` |
| `c` | `python V0/main.py prog.srcx --run compiler` (la VM) |
| `w` | `--emit-hir` y `node web/main.ts dumps/prog.srcx.phir --run` |
| `v1` | arma un proyecto con la V1, la compila con la V0 y la usa para compilar el programa en la VM |

El programa se copia a una carpeta temporal: no deja `dumps/` ni `log/` en
el repositorio. Se quitan de la salida las líneas de progreso del
compilador.

**Requisitos:** Python 3.10+; para `c` y `v1`, la VM construida en
`build/bin/` (ver [how_to_run.md](../../how_to_run.md)); para `w`, node 22 o
superior.

## Qué hay

- `vm*`, `nuevo_vm_*`: lo que la VM rechaza o hace distinto del intérprete.
- `web_*`: lo que el target web rechaza.
- `v1_*`, `v2_*`, `v1_enlazador/`: lo que la V1 y la semilla no conocen.
- `host_*`, `lib_*`: la librería y las llamadas al host.
- `ptr_*`, `move_*`, `cmp_*`: propiedad y memoria.
- `falta_return`, `sem04*`, `global_por_funcion`: diagnósticos que faltan.
- `par_*`, `generico_repr`, `print_catch`: la segunda caza de fallos.
- `ub1_*`, `extern_excepcion`: los comportamientos indefinidos (UB).
- `limites/`: los límites del lenguaje que parecen errores.
- `dap.py`, `dap2.py`: sesiones mínimas del depurador
  (`python dev/repros/dap.py dev/repros/dap_prog.srcx 4`).
- `lsp_t.py`: mide el servidor de lenguaje sobre un archivo.

Cuando un error se corrige, su programa sale de aquí junto con su entrada de
`c_errorstfix.md`.

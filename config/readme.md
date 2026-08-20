# /config — configuración, dependencias y salidas del compilador

*¿por qué no tener todo en una sola carpeta en lugar de todo repartido?*, una
pregunta que puede surgir y es completamente normal.

en suriaX una de las principales preocupaciones es tener **código ilegible**,
**imposible de mantener** o **ineficiente**; por eso cada responsabilidad
vive en su propio módulo y un orquestador delgado los expone. Refactorizar
una pieza no toca a las demás.

*happy coding : )*

## Estructura (refactorización del antiguo `V0/compilerconfig.py`)

| Módulo | Responsabilidad |
|---|---|
| [`compilerconfig.py`](compilerconfig.py) | **Orquestador**: re-exporta la API pública; `python -m config.compilerconfig` = reporte de dependencias. |
| [`dependencies.py`](dependencies.py) | Plataforma (win32/linux/macos/web), verificación de dependencias (protobuf, pybind11, pyyaml), detección de toolchain. LLVM ya no se detecta: el target nativo es la VM/JIT y no pasa por él. |
| [`errors.py`](errors.py) | Diagnósticos del formato de compilación (familia `CFG0xx`), con el mismo contrato que el resto del compilador. |
| [`validate.py`](validate.py) | Validación del `.suriaX_config.yaml`. El esquema se **deriva** de `default_config()`: dos listas de claves acabarían divergiendo. |
| [`yaml_config.py`](yaml_config.py) | Esquema/generación/carga del `.suriaX_config.yaml`. **Toda ruta relativa se resuelve contra la raíz del proyecto** (el directorio del yaml), nunca contra el CWD. |
| [`logs.py`](logs.py) | Generador de logs → `./log`: **`<fuente>.log`, uno por archivo compilado** (legible, sobrescrito en cada corrida, con los errores de las `.libsrx` que importe) + `notes.jsonl` (NOTAS con recomendación) y `errors.jsonl` (estructurados globales, por el objetivo WIP de suriaX). Un flush por compilación. |
| [`dumps.py`](dumps.py) | Volcados → `./dumps`: AST-tipado a `.ast.json` y tokens a `.tokens.txt` (flags `--emit-ast-json` / `--emit-tokens` de `V0/main.py`). |
| [`cache.py`](cache.py) | Verificador de caché → `./build/cache` con `manifest.json` (invalidación por mtime+size). **Puerta de entrada al runtime system y a suriniX** (build system, Fase 10): aún sin consumidores, pero el contrato ya está fijado. |

## `.suriaX_config.yaml`: rutas de librerías `.libsrx`

```yaml
libraries:
  libsrx_paths:      # relativas a la RAÍZ DEL PROYECTO (donde vive este yaml)
    - ./lib          # default
    - ./vendor/libs  # el usuario añade las suyas
```

Orden real de búsqueda de un `#import`: (1) el directorio del `.srcx` que
importa, (2) cada entrada de `libsrx_paths`. Sin yaml, la raíz es el
directorio del fuente. Si `pyyaml` no está instalado, encontrar el yaml
sigue anclando la raíz (los valores personalizados no se aplican, pero las
rutas jamás caen al CWD del proceso).

## Regla de dependencia

El frontend (`V0/src/frontend/`) **no importa este paquete**: `V0/main.py`
es el único puente (carga la config, la pasa a la Semántica como dict, y
enruta errores/NOTAS hacia `logs.py`). Así el frontend sigue siendo
utilizable de forma aislada (tests, playground wASM).

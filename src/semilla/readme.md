# La semilla: la V2

Esta carpeta es el **compilador de suriaX compilado por sí mismo**: la V1
(`src/`) compilada por la V1, que es lo que el plan de versiones llama la V2.
Son las unidades `.phir` del compilador (`main.srcx.phir`) y de cada librería
que usa. Con ellas y la VM (`suriax-hir`) suriaX se compila **sin la V0**.

## Usarla

```sh
suriax-hir src/semilla/main.srcx.phir --run --quiet -- prog.srcx salida/prog.phir --stdlib lib
suriax-hir salida/prog.phir --run
```

Escribe `salida/prog.phir` y una unidad por librería que importa el programa.
Con errores, los escribe a la salida de errores (los mismos que la V0) y no
escribe nada.

## Regenerarla

Cuando cambia la V1 (`src/frontend`, `src/semantica`, `src/hir`,
`src/main.srcx`), la semilla deja de ser la V1 de hoy y
`test/bootstrap/test_semilla.py` lo dice. Se regenera con:

```sh
python src/semilla/regenera.py            # con la semilla actual (sin la V0)
python src/semilla/regenera.py --desde-v0 # desde la V0: la primera vez, o si la
                                          # semilla ya no puede compilar el fuente
```

La receta compila la V1 con la semilla, compila lo que sale otra vez consigo
mismo y solo reemplaza la semilla si las dos salidas son idénticas (el punto
fijo). Python solo arma la carpeta y llama a la VM.

## Por qué es reproducible

Las unidades no guardan rutas de la máquina: la ruta de cada librería viaja
relativa a su raíz (`<stdlib>/...` o relativa al proyecto; ver
`src/hir/contrato.md`, sección 10.7). La receta arma siempre el mismo proyecto,
así que la semilla sale igual en cualquier carpeta y máquina.
`test/bootstrap/test_v2.py` lo comprueba (otra carpeta, otra stdlib).

# `suri` — el compilador desde la terminal

```bash
pip install -e .        # desde la raíz del repositorio
suri hola.srcx          # compila y ejecuta
suri hola.srcx --emit-hir
suri --check
```

Sin instalar nada:

```bash
python -m suri hola.srcx
```

## Qué es y qué no

Es un **envoltorio**. Las banderas son las del compilador y salen de un solo
sitio, [`V0/cli/args.py`](../V0/cli/args.py): aquí no se declara ninguna, no se
traduce ninguna y no se inventa ninguna. Ese fue el motivo por el que ese
parser se separó de `main()`, escrito en su propio docstring — *"permite que
otro front consulte o reutilice el mismo parser sin arrastrar el resto"*.

Por eso `suri --help` y `python V0/main.py --help` imprimen **lo mismo**, y una
bandera nueva aparece en los dos sin tocar esta carpeta.

Lo único que añade es la comodidad que ya tenía el atajo de la raíz: **compilar
un fuente sin decir qué hacer con él lo ejecuta**. `suri hola.srcx` equivale a
`python V0/main.py hola.srcx --run`, igual que `python main.py hola.srcx`.

## Dónde busca el compilador

En este orden, y si no lo encuentra dice **qué rutas probó**:

| | dónde | para qué |
|---|---|---|
| 1 | `SURIAX_ROOT` | apuntar a un árbol concreto sin instalar nada |
| 2 | la raíz del repositorio, subiendo desde el paquete | uso desde el clon |
| 3 | el directorio actual | `suri` instalado, corriendo dentro de un proyecto con su propio `V0/` |

## Mapa

| archivo | responsabilidad |
|---|---|
| `command.py` | encontrar el compilador y cederle el control |
| `__main__.py` | `python -m suri` |
| `__init__.py` | expone `main` |

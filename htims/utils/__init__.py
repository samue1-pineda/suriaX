"""Herramientas para quien ESCRIBE hooks, no para el compilador.

El compilador no importa nada de aquí: usa ``htims.declarations`` directo.
Este paquete existe para el otro lado —el usuario que declara un hook— y por
eso puede depender de ``htims``, pero sigue sin tocar ``V0/`` (la frontera del
módulo vale igual aquí; ver ``htims/readme.md``).

Los submódulos se importan a mano (``from htims.utils import check``): no se
reexportan aquí porque los tres se usan también como CLI (``python -m
htims.utils.check``), y precargarlos haría que Python avisara de que el módulo
ya estaba importado antes de ejecutarlo.
"""

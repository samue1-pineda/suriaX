"""Las capas del playground, de fuera hacia dentro.

    transporte   ``server.py``      HTTP: rutas, cabeceras, límites, errores
    aplicación   ``aplicacion.py``  qué se le pide a quién y cómo se junta
    adaptadores  ``compilador.py``  el compilador (Python, en el proceso)
                 ``web.py``         el target web (TypeScript, otro proceso)

La regla que las separa: **una capa solo conoce a la de debajo**. El
transporte no sabe qué es un ``.phir``; un adaptador no sabe qué es una
cabecera. Y los dos adaptadores no se conocen entre sí: lo único que comparten
es el vocabulario de ``estados.py``, que es lo que permite que uno falle sin
que el otro se entere.
"""

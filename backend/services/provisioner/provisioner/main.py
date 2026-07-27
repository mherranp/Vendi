"""Punto de entrada ASGI del provisioner.

Deliberadamente vacío de lógica, como `app/main.py` de la API: aquí solo se
instancia la aplicación leyendo la configuración del entorno, que es lo que
necesita `uvicorn provisioner.main:app`. La fábrica —importable sin variables
de entorno, que es lo que usan los tests— vive en `provisioner.factory`.
"""

from provisioner.factory import crear_app

app = crear_app()

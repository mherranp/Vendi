"""Punto de entrada ASGI de la API de Vendi.

Deliberadamente vacío de lógica: aquí solo se instancia la aplicación leyendo la
configuración del entorno, que es lo que necesita
`uvicorn app.main:app`. Todo lo demás —la cadena de middlewares, su orden y el
porqué de cada capa— vive en `app.factory`.

La separación no es cosmética: `app.factory` se puede importar sin que exista
una sola variable de entorno, y por eso los tests construyen la aplicación
**real** (los mismos middlewares, las mismas rutas) con unos `Settings` de
prueba. Si la fábrica viviera aquí, importar el módulo para llamarla ya habría
ejecutado `crear_app()` y exigido un DSN de producción.
"""

from app.factory import crear_app

app = crear_app()

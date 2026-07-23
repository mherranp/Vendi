"""Candado del ORDEN de la cadena de middlewares.

Existe porque el orden de esta cadena decide comportamiento observable y nadie
lo ve leyendo un diff. `add_middleware` **inserta al principio** de
`app.user_middleware`, así que el código se lee al revés de como se ejecuta, y
mover una línea dos posiciones puede tumbar las cuatro SPAs sin que falle ni un
test de negocio.

Los dos fallos concretos que este archivo impide que vuelvan:

1. `TenantMiddleware` por fuera de `CORSMiddleware`. El preflight muere con 401
   y sin cabeceras `Access-Control-Allow-*`: el navegador nunca hace el request
   real y el desarrollador del SPA solo ve «CORS error».
2. `ErrorHandlerMiddleware` por fuera de `CorrelationIdMiddleware` o de las
   cabeceras de seguridad. Entonces los 500 salen sin `X-Correlation-ID` —el
   único hilo para encontrarlos en el log— y sin cabeceras de seguridad.
"""

from __future__ import annotations

from ayudas import app_de_prueba, settings_de_prueba

#: De FUERA hacia DENTRO, que es como se ejecuta.
ORDEN_ESPERADO_SIN_CORS = [
    "CorrelationIdMiddleware",
    "SecurityHeadersMiddleware",
    "APIVersionMiddleware",
    "ErrorHandlerMiddleware",
    "TenantMiddleware",
    "PrometheusInstrumentatorMiddleware",
]

ORDEN_ESPERADO_CON_CORS = ["CORSMiddleware", *ORDEN_ESPERADO_SIN_CORS]


def _orden(aplicacion) -> list[str]:
    # `user_middleware[0]` es el más EXTERNO: Starlette construye la pila
    # envolviendo en orden inverso a la lista.
    return [m.cls.__name__ for m in aplicacion.user_middleware]


def test_el_orden_por_defecto_es_exactamente_el_declarado():
    aplicacion, _, _ = app_de_prueba()
    assert _orden(aplicacion) == ORDEN_ESPERADO_SIN_CORS


def test_con_cors_el_middleware_de_cors_es_el_mas_externo():
    """Si CORS no es el primero, las respuestas de error salen sin sus cabeceras."""
    aplicacion, _, _ = app_de_prueba(settings_de_prueba(cors_origins="http://localhost:4200"))
    assert _orden(aplicacion) == ORDEN_ESPERADO_CON_CORS


def test_cors_va_por_fuera_de_tenant():
    """La aserción explícita del fallo 1, con mensaje propio.

    Redundante con el test de igualdad de arriba a propósito: cuando el orden
    cambie, este es el que dice POR QUÉ importa, y el otro solo dice que la
    lista no coincide.
    """
    aplicacion, _, _ = app_de_prueba(settings_de_prueba(cors_origins="http://localhost:4200"))
    orden = _orden(aplicacion)
    assert orden.index("CORSMiddleware") < orden.index("TenantMiddleware"), (
        "TenantMiddleware quedó por fuera de CORSMiddleware: exigirá token en el "
        "preflight y la respuesta 401 saldrá sin cabeceras CORS. Todo el tráfico "
        "cross-origin de las cuatro SPAs muere con un error que no menciona el 401."
    )


def test_el_manejador_de_errores_va_por_dentro_de_correlacion_y_cabeceras():
    """La aserción explícita del fallo 2."""
    orden = _orden(app_de_prueba()[0])
    assert orden.index("CorrelationIdMiddleware") < orden.index("ErrorHandlerMiddleware")
    assert orden.index("SecurityHeadersMiddleware") < orden.index("ErrorHandlerMiddleware")
    assert orden.index("APIVersionMiddleware") < orden.index("ErrorHandlerMiddleware")


def test_tenant_va_por_dentro_del_manejador_de_errores():
    """Sus 401/403 tienen que pasar por la cadena de cabeceras al salir."""
    orden = _orden(app_de_prueba()[0])
    assert orden.index("ErrorHandlerMiddleware") < orden.index("TenantMiddleware")


def test_prometheus_es_el_mas_interno():
    """Mide el trabajo de la API, no el coste de estampar cabeceras."""
    assert _orden(app_de_prueba()[0])[-1] == "PrometheusInstrumentatorMiddleware"

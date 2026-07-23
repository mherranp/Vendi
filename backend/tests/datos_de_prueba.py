"""Identificadores fijos de los negocios de prueba.

Viven aparte de `conftest.py` para que los módulos de test los importen por
nombre (`from datos_de_prueba import T1`) sin depender de que pytest exponga el
conftest como módulo importable, que es un detalle de su mecanismo de carga y
no un contrato.

Son fijos y legibles a propósito: cuando un assert falla, "esperaba filas de
1111...-1111" se entiende de un vistazo; dos UUID aleatorios distintos en cada
corrida, no.
"""

import uuid

T1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
T2 = uuid.UUID("22222222-2222-2222-2222-222222222222")

TABLA_PRUEBA = "ventas_de_prueba"

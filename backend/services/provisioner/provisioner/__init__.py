"""El provisioner de Vendi: la única unidad de despliegue con `manage-realm`.

Cierre de D-02 (ADR-027). Hasta Fase 1 la credencial de `vendi-provisioning`
vivía en el proceso de la API: quien la comprometiera con ejecución de código
podía reescribir los flujos de autenticación del realm, apagar la protección
de fuerza bruta y hacerse administrador de cualquier tenant. Este servicio es
la frontera que faltaba: la credencial vive AQUÍ, la API le habla por HTTP
interno (`vendi_core.provisioning.cliente`), y la superficie que expone son
operaciones acotadas de negocio, no la Admin API de Keycloak (ver
`provisioner/rutas.py`).

No es una API pública y no lo parezca: sin `/docs`, sin `/openapi.json`, sin
router en Traefik y sin puertos publicados fuera de la red del compose.
"""

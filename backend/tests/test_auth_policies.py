"""Catálogo de permisos y roles de negocio.

Procedencia: `/Users/maoherran/BaseSaaS/backend/tests/test_auth_policies.py`.
Adaptación grande, porque el módulo se reescribió para Vendi: los roles pasan de
`admin`/`user` a `dueno`/`cajero`/`almacenista` (`PERMISOS_POR_ROL`), y el
catálogo pierde los permisos de los módulos que no existen en Fase 0.

Los dos asserts que no vienen de BaseSaaS y son los que de verdad importan aquí:

- `dueno` NO tiene `platform:admin`. El aislamiento entre negocios no puede
  depender de que a nadie se le vaya la mano en la consola de Keycloak.
- No existe ningún permiso de suplantación. La Etapa 2 quitó el rol
  `impersonation` de la cuenta de servicio por ser un agujero de aislamiento
  multi-negocio; si el permiso reapareciera en el catálogo, alguien se lo
  asignaría a un rol y quedaría prometiendo algo que el sistema no hace.
"""

from __future__ import annotations

from vendi_core.auth.context import UserContext
from vendi_core.auth.policies import (
    PERM_AUDIT_READ,
    PERM_PLATFORM_ADMIN,
    PERM_TENANT_CREATE,
    PERM_TENANT_DELETE,
    PERM_TENANT_READ,
    PERM_TENANT_UPDATE,
    PERM_WILDCARD,
    PERMISOS_POR_ROL,
    PERMISSION_CATALOG,
    ROL_ALMACENISTA,
    ROL_CAJERO,
    ROL_DUENO,
    ROLES_DE_NEGOCIO,
    has_permission,
    roles_de_realm_del_grupo,
)


def _usuario(**kwargs) -> UserContext:
    datos = {"user_id": "u1", "username": "ana", "email": "ana@ejemplo.test"}
    datos.update(kwargs)
    return UserContext(**datos)


def test_el_catalogo_declara_los_permisos_de_negocio_de_fase_0():
    nombres = {p[0] for p in PERMISSION_CATALOG}
    assert nombres == {
        PERM_TENANT_READ,
        PERM_TENANT_CREATE,
        PERM_TENANT_UPDATE,
        PERM_TENANT_DELETE,
        PERM_PLATFORM_ADMIN,
        PERM_AUDIT_READ,
    }


def test_el_catalogo_no_declara_ningun_permiso_de_suplantacion():
    """En Fase 0 no hay suplantación: la Etapa 2 quitó el rol `impersonation`
    de la cuenta de servicio. Un permiso declarado aquí prometería algo que el
    sistema no puede cumplir."""
    nombres = {p[0] for p in PERMISSION_CATALOG}
    prohibidos = {"user:impersonate", "impersonate:user", "impersonation"}
    assert nombres & prohibidos == set()


def test_todo_rol_de_negocio_tiene_entrada_en_el_mapa_de_permisos():
    assert set(PERMISOS_POR_ROL) == set(ROLES_DE_NEGOCIO)
    assert ROLES_DE_NEGOCIO == (ROL_DUENO, ROL_CAJERO, ROL_ALMACENISTA)


def test_el_dueno_manda_en_su_negocio_y_en_nada_mas():
    permisos = PERMISOS_POR_ROL[ROL_DUENO]
    assert PERM_TENANT_READ in permisos
    assert PERM_TENANT_UPDATE in permisos
    assert PERM_AUDIT_READ in permisos
    # Lo que NO tiene, que es el punto:
    assert PERM_PLATFORM_ADMIN not in permisos
    assert PERM_TENANT_CREATE not in permisos
    assert PERM_TENANT_DELETE not in permisos


def test_ningun_rol_de_negocio_alcanza_la_consola_de_plataforma():
    for rol, permisos in PERMISOS_POR_ROL.items():
        assert PERM_PLATFORM_ADMIN not in permisos, f"el rol {rol} llega a la consola de plataforma"


def test_cajero_y_almacenista_estan_declarados_y_vacios_a_proposito():
    """Sus permisos son los del modelo de datos del MVP, que aún no existe. Se
    declaran ahora para que el grupo exista en el realm desde el primer día."""
    assert PERMISOS_POR_ROL[ROL_CAJERO] == frozenset()
    assert PERMISOS_POR_ROL[ROL_ALMACENISTA] == frozenset()


def test_has_permission_mira_los_roles_del_token():
    usuario = _usuario(roles=frozenset({PERM_TENANT_READ}))
    assert has_permission(usuario, PERM_TENANT_READ)
    assert not has_permission(usuario, PERM_TENANT_CREATE)


def test_has_permission_respeta_el_comodin():
    assert has_permission(_usuario(roles=frozenset({PERM_WILDCARD})), "lo:que:sea")


def test_has_permission_respeta_el_marcador_de_superusuario():
    assert has_permission(_usuario(is_superuser=True), PERM_TENANT_CREATE)


def test_has_role_lee_los_roles_de_realm():
    """Desde la Etapa 5 (D-08) el rol de negocio viaja en `realm_access.roles`,
    junto a los permisos: es el único claim que el realm emite de fábrica."""
    usuario = _usuario(roles=frozenset({ROL_DUENO, PERM_TENANT_READ}))
    assert usuario.has_role(ROL_DUENO)
    assert not usuario.has_role(ROL_CAJERO)


def test_un_rol_ausente_deniega_de_verdad():
    """El candado de D-08: antes `has_role` leía un claim que el realm nunca
    emite, así que devolvía False para TODO el mundo —el dueño incluido— y
    cualquier `require_role` fallaba por la razón equivocada. Esta pareja de
    aserciones distingue «deniega porque no lo tiene» de «deniega siempre»."""
    dueno = _usuario(roles=frozenset(roles_de_realm_del_grupo(ROL_DUENO)))
    cajero = _usuario(roles=frozenset(roles_de_realm_del_grupo(ROL_CAJERO)))

    assert dueno.has_role(ROL_DUENO) is True
    assert cajero.has_role(ROL_DUENO) is False
    assert cajero.has_role(ROL_CAJERO) is True


def test_el_grupo_de_un_rol_mapea_el_rol_y_sus_permisos():
    """Lo que la siembra escribe en Keycloak. Sin el propio rol en el mapeo, el
    token del dueño no llevaría `dueno` y volvería D-08."""
    mapeo = roles_de_realm_del_grupo(ROL_DUENO)
    assert ROL_DUENO in mapeo
    assert PERM_TENANT_READ in mapeo
    assert mapeo == sorted(mapeo), "el orden tiene que ser estable: la siembra hace diff contra él"

    # Los roles sin permisos declarados (cajero, almacenista) siguen llevando su
    # propio rol: es lo que hace que `has_role` los reconozca.
    assert roles_de_realm_del_grupo(ROL_CAJERO) == [ROL_CAJERO]

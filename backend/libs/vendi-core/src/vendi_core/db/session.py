"""Fábricas de sesión: la de tenant (con RLS) y la de plataforma (sin él).

Este módulo es el corazón del aislamiento multi-tenant de Vendi. Merece leerse
entero antes de tocarlo.

## Por qué el `SET LOCAL` va aquí y no en el middleware

El spike de RLS (escenario B.3 del informe `2026-07-22-verificacion-rls.md`)
midió que `SET LOCAL` **muere en el `COMMIT`**. Un middleware que lo emitiera una
vez por request dejaría este agujero:

    async def handler(session):
        await session.execute(...)      # ve sus filas
        await session.commit()          # ← aquí muere el SET LOCAL
        await session.execute(...)      # ve CERO filas, sin ningún error

Cero filas en silencio es la peor forma de fallar: no hay excepción, no hay log,
el endpoint devuelve una lista vacía y parece que el negocio no tiene datos. Por
eso el `SET LOCAL` lo reinstala el evento `after_begin` de la sesión, que
dispara en **cada** transacción nueva, incluidas las que abre SQLAlchemy sola
después de un commit o un rollback.

## Por qué el listener se registra sobre una subclase

`event.listens_for(Session, "after_begin")` registra en la clase `Session`
global de SQLAlchemy, y afectaría también a la fábrica de plataforma —que
existe justamente para NO sembrar tenant—. Cada llamada a
`create_session_factory` crea su propia subclase anónima de `Session` y registra
el listener ahí. Es lo que hace que `create_platform_session_factory` sea
verificablemente distinta y no una cuestión de fe.

## Por qué `set_config(..., true)` y no `SET LOCAL` textual

Son la misma cosa: el tercer parámetro `is_local=true` de `set_config` le da
exactamente el alcance de transacción de `SET LOCAL`. La diferencia es que
`set_config` **admite parámetros ligados** y `SET LOCAL` no —Postgres solo acepta
un literal ahí—. Interpolar el UUID en el SQL sería seguro por tipo hoy (es un
`uuid.UUID`, no un string), pero es un invariante que se rompe el día que
alguien relaje el tipo. Con `set_config` no hay nada que romper. Además se
valida el tipo antes de emitir, y se falla ruidoso: un tenant que no sea UUID es
un bug de programación, no una entrada de usuario.
"""

import uuid
from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from vendi_core.db.engine import GUC_TENANT
from vendi_core.tenant.context import current_tenant_id

# Clave que marca a las sesiones de plataforma en `Session.info`. Permite
# distinguirlas en tiempo de ejecución (ver `es_sesion_de_plataforma`) sin
# depender de qué fábrica las creó.
_MARCA_PLATAFORMA = "vendi_sesion_de_plataforma"

# `set_config(nombre, valor, is_local)`: con is_local=true equivale a SET LOCAL,
# es decir, muere al terminar la transacción en curso.
_SQL_SEMBRAR_TENANT = text(f"SELECT set_config('{GUC_TENANT}', :tenant_id, true)")


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Fábrica de sesiones **de tenant**: siembra el GUC en cada transacción.

    Es la que usan los handlers de la API. El engine que reciba debe apuntar al
    rol `vendi_app` (sin `BYPASSRLS`): si se le pasa el de `vendi_platform` el
    `SET LOCAL` se emite igual pero no sirve de nada, porque `BYPASSRLS` salta
    la policy. Esa combinación es un error de cableado y no se puede detectar
    desde aquí — se detecta en el arranque de la app (tarea 4.1).
    """

    class _SesionDeTenant(Session):
        """Subclase por fábrica: acota el listener a estas sesiones y solo a estas."""

    @event.listens_for(_SesionDeTenant, "after_begin")
    def _sembrar_tenant(session, transaction, connection):  # noqa: ANN001, ARG001
        if transaction.nested:
            # Un SAVEPOINT vive dentro de la transacción externa y hereda su
            # GUC. Re-emitirlo aquí sería redundante, y peor: un `SET LOCAL`
            # dentro de un SAVEPOINT que luego se revierte deja el GUC en un
            # estado que depende del rollback, no del contexto.
            return
        tenant_id = current_tenant_id.get()
        if tenant_id is None:
            # Sin tenant no se siembra nada. La policy ve el GUC en '' (lo dejó
            # el hook de checkout), `NULLIF` lo convierte en NULL y la
            # comparación da NULL: cero filas, cero error. Fail-closed.
            return
        if not isinstance(tenant_id, uuid.UUID):
            # Ruidoso a propósito. Si aquí llega un string es que alguien puso
            # el ContextVar a mano saltándose el middleware, y lo que sigue es
            # o un error de cast del driver (feo) o —si el string tiene forma de
            # UUID ajeno— una fuga. Se corta antes.
            raise TypeError(f"current_tenant_id debe ser uuid.UUID, llegó {type(tenant_id).__name__}: {tenant_id!r}")
        connection.execute(_SQL_SEMBRAR_TENANT, {"tenant_id": str(tenant_id)})

    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        sync_session_class=_SesionDeTenant,
        expire_on_commit=False,
    )


def create_platform_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Fábrica de sesiones **de plataforma**: nunca siembra el GUC.

    Para el worker, el runner de retención y los endpoints de `/platform/*`, que
    son cross-tenant por naturaleza. Va sobre el engine del rol
    `vendi_platform` (con `BYPASSRLS`), así que ve todas las filas de la región.

    No lleva listener. No es que lo lleve y no haga nada: literalmente no está
    registrado, y el test `test_platform_session_no_emite_set_local` lo verifica
    contra la base real.

    Las sesiones que produce quedan marcadas en `Session.info` para que un
    handler de tenant que reciba una por error pueda detectarlo (tarea 4.1
    cablea la dependencia de FastAPI que lo hace ruidoso).
    """
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        info={_MARCA_PLATAFORMA: True},
    )


def es_sesion_de_plataforma(session: AsyncSession | Session) -> bool:
    """¿Esta sesión salta RLS? Candado para dependencias y tests.

    Existe porque el peor error posible en este diseño es usar la sesión de
    plataforma dentro de un handler de tenant: funciona, no lanza nada, y
    devuelve los datos de todos los negocios. Un `assert not
    es_sesion_de_plataforma(s)` en la frontera lo convierte en un fallo visible.
    """
    info = getattr(session, "info", None) or {}
    return bool(info.get(_MARCA_PLATAFORMA, False))


async def get_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

"""Alta, baja y modificación de negocios, con su Organization de Keycloak.

## Por qué este servicio EXIGE la sesión de plataforma

Se comprueba en el constructor y se falla con un mensaje explícito. No es
defensa teórica: es el fallo que ya se identificó y que sin este candado sale
como un `permission denied` opaco a tres capas de distancia.

El alta encola el evento `tenant.creado` en el outbox **dentro de la misma
transacción** que el INSERT (esa es toda la garantía del patrón). Ese evento es
de plataforma: viaja con `tenant_id = NULL`. Y `outbox_messages` tiene una
policy de INSERT —`outbox_encolado_del_tenant`— que exige
`tenant_id = current_setting('vendi.tenant_id')`. Con la sesión de la API (rol
`vendi_app`) esa comparación es `NULL = NULL` → NULL → **la fila se rechaza**, y
lo que ve el operador es «new row violates row-level security policy» en el alta
de un negocio, sin ninguna pista de que el problema sea qué fábrica de sesión se
cableó. Con la sesión de plataforma (`vendi_platform`, con `BYPASSRLS`) la
policy no aplica y el evento entra.

Dicho de otro modo: el contrato "el aprovisionamiento va con la sesión de
plataforma" es un requisito de corrección, no una preferencia — y por eso lo
verifica un test (`test_tenants_provisioning.py`).

## La compensación del alta, y qué NO cubre

    INSERT tenant  ──►  create_organization  ──►  COMMIT
                             │ falla
                             ▼
                          ROLLBACK  (no queda negocio sin organización)

`create_organization` ya no habla con Keycloak: habla con el servicio
`provisioner` por HTTP interno (cierre de D-02, ADR-027), y es el provisioner
quien llama a Keycloak con la credencial que ya no vive en este proceso. Para
la compensación el cambio es neutro: un provisioner caído produce el mismo
`ExternalServiceError` tipado que producía un Keycloak caído, y el ROLLBACK se
ejecuta igual.

El camino inverso —organización creada y `COMMIT` fallido— deja una Organization
huérfana en Keycloak. No se compensa en caliente a propósito: un `DELETE` contra
Keycloak dentro del manejador de un fallo de base de datos es otra operación de
red que también puede fallar, y anidar compensaciones solo mueve el problema.
Lo resuelve `scripts/reconcile-keycloak.sh`, que compara las dos fuentes. La
ventana es estrecha (entre la llamada a Keycloak y el `COMMIT`) y su daño es
acotado: una organización sin negocio no da acceso a nada, porque el
`tenant_id` que llevaría en el claim no existe en la tabla y la dependencia de
estado corta con 403.

## Por qué la baja BORRA la Organization en vez de deshabilitarla

El plan decía "soft delete + org deshabilitada". Deshabilitarla no sirve para lo
que hace falta:

- El spike midió que una Organization deshabilitada **no impide el login**: solo
  desaparece del claim. Como freno de acceso no aporta nada que no aporte ya el
  estado del negocio en esta tabla.
- Keycloak exige `name` único por realm y una organización deshabilitada sigue
  ocupando su nombre y su alias. Como el `name` que escribimos es el
  `tenant_id`, esto no bloquearía un alta nueva — pero deja el realm creciendo
  con organizaciones fantasma que nadie limpia.

Borrarla libera el nombre, saca a los miembros del claim en su siguiente token y
deja el estado del negocio como única fuente de verdad. La fila de `tenants`
sobrevive (borrado lógico) para la auditoría y para que su `id` no se reutilice
jamás.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenants.models import EstadoTenant, Tenant
from vendi_core.audit.events import AuditEvent, AuditStatus
from vendi_core.audit.service import AuditService
from vendi_core.auth.context import UserContext
from vendi_core.cache.redis import RedisCache
from vendi_core.db.session import es_sesion_de_plataforma
from vendi_core.errors.domain import NotFoundError
from vendi_core.events.service import DomainEventService
from vendi_core.provisioning.cliente import PuertoAprovisionamiento
from vendi_core.tracing.context import get_correlation_id

logger = structlog.get_logger()

#: Prefijo de las claves de cache del estado de un negocio.
PREFIJO_CACHE_ESTADO = "vendi:tenant:estado:"


class ErrorDeCableadoDelServicio(RuntimeError):
    """El servicio se construyó con la fábrica de sesión equivocada."""


def clave_de_cache(tenant_id: uuid.UUID) -> str:
    return f"{PREFIJO_CACHE_ESTADO}{tenant_id}"


class TenantService:
    """Operaciones sobre el catálogo de negocios. Siempre con sesión de plataforma."""

    def __init__(
        self,
        session: AsyncSession,
        aprovisionamiento: PuertoAprovisionamiento,
        audit: AuditService,
        cache: RedisCache | None = None,
        cache_ttl: int = 60,
    ):
        if not es_sesion_de_plataforma(session):
            raise ErrorDeCableadoDelServicio(
                "TenantService recibió una sesión de TENANT (rol vendi_app). El "
                "aprovisionamiento necesita la sesión de plataforma: `tenants` está "
                "revocada para vendi_app y el evento `tenant.creado` viaja con "
                "tenant_id NULL, que la policy de INSERT del outbox rechaza. Con la "
                "sesión equivocada esto falla con un 'permission denied' que no "
                "menciona ninguna de las dos causas."
            )
        self._session = session
        self._aprovisionamiento = aprovisionamiento
        self._audit = audit
        self._cache = cache
        self._cache_ttl = cache_ttl

    # --- Lectura -----------------------------------------------------------

    async def obtener(self, tenant_id: uuid.UUID, *, incluir_eliminados: bool = False) -> Tenant:
        consulta = select(Tenant).where(Tenant.id == tenant_id)
        if not incluir_eliminados:
            consulta = consulta.where(Tenant.deleted_at.is_(None))
        tenant = (await self._session.execute(consulta)).scalar_one_or_none()
        if tenant is None:
            raise NotFoundError("El negocio no existe.", code="tenant_no_encontrado")
        return tenant

    async def listar(
        self,
        *,
        skip: int = 0,
        limit: int = 25,
        incluir_eliminados: bool = False,
    ) -> tuple[list[Tenant], int]:
        base = select(Tenant)
        conteo = select(func.count()).select_from(Tenant)
        if not incluir_eliminados:
            base = base.where(Tenant.deleted_at.is_(None))
            conteo = conteo.where(Tenant.deleted_at.is_(None))
        total = (await self._session.execute(conteo)).scalar_one()
        filas = (
            (await self._session.execute(base.order_by(Tenant.created_at.desc(), Tenant.id).offset(skip).limit(limit)))
            .scalars()
            .all()
        )
        return list(filas), int(total)

    async def listar_por_ids(self, ids: list[uuid.UUID]) -> list[Tenant]:
        """Los negocios vivos de una lista de ids (los alias del token).

        Sesión de plataforma (el constructor ya la exige): la tabla `tenants`
        no es visible para el rol de aplicación. Los eliminados no vuelven:
        un negocio dado de baja no se ofrece en el selector.
        """
        if not ids:
            return []
        consulta = (
            select(Tenant).where(Tenant.id.in_(ids), Tenant.deleted_at.is_(None)).order_by(Tenant.nombre, Tenant.id)
        )
        return list((await self._session.execute(consulta)).scalars().all())

    async def estado_de(self, tenant_id: uuid.UUID) -> str | None:
        """Estado del negocio, con cache. `None` = no existe (o está eliminado).

        El cache es lo que hace barato comprobar la suspensión en cada request.
        Su TTL es también la latencia máxima entre suspender un negocio en la
        consola y que sus tokens dejen de servir — por eso las mutaciones
        invalidan la clave en vez de esperar a que caduque.
        """
        clave = clave_de_cache(tenant_id)
        if self._cache is not None:
            try:
                cacheado = await self._cache.get(clave)
            except Exception as exc:  # noqa: BLE001
                # Un Redis caído degrada a "pregunta a la base", nunca a "deja
                # pasar". Ver `dependencies.py`.
                logger.warning("cache_de_estado_no_disponible", error=str(exc))
                cacheado = None
            if isinstance(cacheado, str) and cacheado:
                return None if cacheado == "-" else cacheado

        fila = (
            await self._session.execute(
                select(Tenant.estado).where(Tenant.id == tenant_id).where(Tenant.deleted_at.is_(None))
            )
        ).scalar_one_or_none()

        if self._cache is not None:
            try:
                # "-" es el centinela de "no existe". Cachear también la
                # ausencia evita que un id inventado golpee la base en cada
                # request (el ataque de enumeración más barato que hay).
                await self._cache.set(clave, fila or "-", ttl=self._cache_ttl)
            except Exception as exc:  # noqa: BLE001
                logger.warning("cache_de_estado_no_escribible", error=str(exc))
        return fila

    async def invalidar_cache(self, tenant_id: uuid.UUID) -> None:
        if self._cache is None:
            return
        try:
            await self._cache.delete(clave_de_cache(tenant_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache_de_estado_no_invalidable", tenant_id=str(tenant_id), error=str(exc))

    # --- Escritura ---------------------------------------------------------

    async def crear(self, nombre: str, actor: UserContext | None = None) -> Tenant:
        """INSERT + Organization, con compensación. Ver la cabecera del módulo."""
        tenant = Tenant(nombre=nombre, estado=EstadoTenant.ACTIVO)
        self._session.add(tenant)
        # `flush` y no `commit`: necesitamos el id generado para el alias de la
        # Organization, pero la transacción sigue abierta para poder deshacerla
        # si Keycloak falla.
        await self._session.flush()

        try:
            tenant.kc_org_id = await self._aprovisionamiento.create_organization(tenant.id, nombre)
        except Exception:
            await self._session.rollback()
            await self._auditar(
                accion="tenant.crear",
                tenant_id=None,
                actor=actor,
                estado=AuditStatus.FAILURE,
                cambios={"nombre": nombre},
                error="no se pudo crear la organización en Keycloak",
            )
            raise

        await DomainEventService.emit(
            self._session,
            # `None` a propósito: el alta de un negocio es un evento de
            # PLATAFORMA (clave `plataforma.tenant.creado`). Su público es la
            # consola, no el propio negocio, que en este instante todavía no
            # tiene ni usuarios. El id va en `resource_id` y en `data`.
            tenant_id=None,
            event_name="tenant.creado",
            resource_type="tenant",
            resource_id=str(tenant.id),
            data={"tenant_id": str(tenant.id), "nombre": nombre, "kc_org_id": tenant.kc_org_id},
        )
        await self._session.commit()
        await self._session.refresh(tenant)

        await self.invalidar_cache(tenant.id)
        await self._auditar(
            accion="tenant.crear",
            tenant_id=tenant.id,
            actor=actor,
            cambios={"nombre": nombre, "kc_org_id": tenant.kc_org_id},
        )
        logger.info("tenant_creado", tenant_id=str(tenant.id), kc_org_id=tenant.kc_org_id)
        return tenant

    async def actualizar(
        self,
        tenant_id: uuid.UUID,
        *,
        nombre: str | None = None,
        estado: str | None = None,
        actor: UserContext | None = None,
    ) -> Tenant:
        tenant = await self.obtener(tenant_id)
        cambios: dict[str, object] = {}
        if nombre is not None and nombre != tenant.nombre:
            cambios["nombre"] = {"antes": tenant.nombre, "despues": nombre}
            tenant.nombre = nombre
        if estado is not None and estado != tenant.estado:
            cambios["estado"] = {"antes": tenant.estado, "despues": estado}
            tenant.estado = estado

        if not cambios:
            return tenant

        await DomainEventService.emit(
            self._session,
            tenant_id=None,
            event_name="tenant.actualizado",
            resource_type="tenant",
            resource_id=str(tenant.id),
            data={"tenant_id": str(tenant.id), "cambios": cambios},
        )
        await self._session.commit()
        await self._session.refresh(tenant)

        # Invalidar DESPUÉS del commit: si se invalidara antes, una lectura
        # concurrente repoblaría el cache con el valor viejo y la suspensión
        # tardaría un TTL entero en verse.
        await self.invalidar_cache(tenant.id)
        await self._auditar(accion="tenant.actualizar", tenant_id=tenant.id, actor=actor, cambios=cambios)
        logger.info("tenant_actualizado", tenant_id=str(tenant.id), cambios=list(cambios))
        return tenant

    async def eliminar(self, tenant_id: uuid.UUID, *, actor: UserContext | None = None) -> None:
        """Baja del negocio: borrado lógico + borrado de su Organization."""
        tenant = await self.obtener(tenant_id)
        org_id = tenant.kc_org_id

        tenant.estado = EstadoTenant.ELIMINADO
        tenant.deleted_at = datetime.now(UTC)
        tenant.kc_org_id = None

        await DomainEventService.emit(
            self._session,
            tenant_id=None,
            event_name="tenant.eliminado",
            resource_type="tenant",
            resource_id=str(tenant.id),
            data={"tenant_id": str(tenant.id), "kc_org_id": org_id},
        )
        await self._session.commit()

        if org_id:
            # Después del commit y tolerante a fallos: si Keycloak no responde,
            # el negocio ya está dado de baja (que es lo que corta el acceso) y
            # la organización huérfana la recoge `reconcile-keycloak.sh`.
            # Hacerlo antes del commit invertiría el problema: organización
            # borrada y negocio vivo, es decir, un negocio cuyos usuarios dejan
            # de poder entrar sin que nadie lo haya dado de baja.
            try:
                await self._aprovisionamiento.delete_organization(org_id)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "no_se_pudo_borrar_la_organizacion",
                    tenant_id=str(tenant.id),
                    kc_org_id=org_id,
                    error=str(exc),
                )

        await self.invalidar_cache(tenant.id)
        await self._auditar(
            accion="tenant.eliminar",
            tenant_id=tenant.id,
            actor=actor,
            cambios={"kc_org_id": org_id},
        )
        logger.info("tenant_eliminado", tenant_id=str(tenant.id))

    # --- Auditoría ---------------------------------------------------------

    async def _auditar(
        self,
        *,
        accion: str,
        tenant_id: uuid.UUID | None,
        actor: UserContext | None,
        cambios: dict | None = None,
        estado: AuditStatus = AuditStatus.SUCCESS,
        error: str = "",
    ) -> None:
        """Escribe la fila de auditoría y **espera** a que se escriba.

        `log_sync` y no `log`: el alta de un negocio es una operación de
        plataforma, poco frecuente y con consecuencias, y la prueba de que
        ocurrió no puede depender de una tarea en segundo plano que el proceso
        podría no llegar a ejecutar. El coste —un INSERT más por operación de
        consola— es irrelevante a este volumen.

        `AuditService` abre su propia sesión con la fábrica de plataforma, así
        que esta escritura NO viaja en la transacción del CRUD: un rollback de
        negocio no borra la prueba de que se intentó la operación.
        """
        await self._audit.log_sync(
            AuditEvent(
                correlation_id=get_correlation_id(),
                tenant_id=tenant_id,
                user_id=actor.user_id if actor else "",
                user_email=actor.email if actor else "",
                action=accion,
                resource_type="tenant",
                resource_id=str(tenant_id) if tenant_id else "",
                status=estado,
                changes=cambios or {},
                error=error,
            )
        )

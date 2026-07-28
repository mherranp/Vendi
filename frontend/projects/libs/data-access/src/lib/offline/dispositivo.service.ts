import { HttpContext } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { lastValueFrom } from 'rxjs';
import type { paths } from '../api-client';
import { ApiService } from '../api.service';
import { SILENCIAR_AVISO_ERROR } from '../interceptors/error.interceptor';
import type { ClaveMeta } from './modelos-locales';
import { VendiDb } from './vendi.db';

type DispositivoSalida =
  paths['/api/v1/dispositivos']['post']['responses']['201']['content']['application/json'];

/**
 * Registro del dispositivo (ADR-017).
 *
 * El dispositivo nace con un UUIDv4 local que el servidor adopta como PK:
 * re-registrar con el mismo id devuelve el existente. La `ultima_secuencia`
 * se reconcilia con `max(local, servidor)`: el contador FIFO del dispositivo
 * jamás retrocede (decisión 9 del plan).
 *
 * Un fallo de red propaga y NO marca el registro: el sincronizador lo
 * reintenta con el mismo backoff que los lotes. Un 409 (id en conflicto) es
 * irrecuperable sin intervención y también propaga — inventar una curación
 * automática de identidad es peor que el bloqueo visible.
 */
@Injectable({ providedIn: 'root' })
export class DispositivoService {
  private readonly db = inject(VendiDb);
  private readonly api = inject(ApiService);

  private readonly _dispositivoId = signal<string | null>(null);
  readonly dispositivoId = this._dispositivoId.asReadonly();
  private readonly _registrado = signal(false);
  readonly registrado = this._registrado.asReadonly();

  async asegurarRegistro(): Promise<string> {
    let id = await this.leerMeta('dispositivo_id');
    if (!id) {
      id = crypto.randomUUID();
      await this.db.meta.put({ clave: 'dispositivo_id', valor: id });
    }
    this._dispositivoId.set(id);

    if (await this.leerMeta('dispositivo_registrado')) {
      this._registrado.set(true);
      return id;
    }

    let nombre = await this.leerMeta('nombre_dispositivo');
    if (!nombre) {
      nombre = 'Caja 1';
      await this.db.meta.put({ clave: 'nombre_dispositivo', valor: nombre });
    }

    const salida = await lastValueFrom(
      this.api.post<DispositivoSalida>(
        '/dispositivos',
        { id, nombre },
        { context: new HttpContext().set(SILENCIAR_AVISO_ERROR, true) },
      ),
    );

    const secuenciaLocal = await this.numeroMeta();
    await this.db.meta.put({
      clave: 'ultima_secuencia',
      valor: Math.max(secuenciaLocal, salida.ultima_secuencia),
    });
    await this.db.meta.put({ clave: 'dispositivo_registrado', valor: 'si' });
    this._registrado.set(true);
    return id;
  }

  private async leerMeta(clave: ClaveMeta): Promise<string | null> {
    const entrada = await this.db.meta.get(clave);
    return typeof entrada?.valor === 'string' ? entrada.valor : null;
  }

  private async numeroMeta(): Promise<number> {
    const entrada = await this.db.meta.get('ultima_secuencia');
    return typeof entrada?.valor === 'number' ? entrada.valor : 0;
  }
}

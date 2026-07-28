import { Component, inject } from '@angular/core';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { StatusBadgeComponent } from 'ui-kit';

import { formatearPesos, pesosPorDia } from '../moneda';
import { TIERS, TierComercial } from '../planes';

interface FilaComparativa {
  readonly clave: string;
  /**
   * Un valor por tier, en el orden de `TIERS`. Las cifras literales (`'100'`)
   * se pintan tal cual; el resto son claves bajo `portal.precios`.
   */
  readonly valores: readonly string[];
}

/**
 * La tabla de precios de ADR-010.
 *
 * Los números que no deben derivar NUNCA (los tres precios) vienen del modelo
 * candado de `planes.ts`; los límites y descripciones vienen del catálogo
 * i18n y los vigila el spec de esta sección. El add-on DIAN se anuncia sin
 * precio: es Fase 2 y prometerle precio hoy sería inventarlo.
 */
@Component({
  selector: 'vd-precios',
  imports: [TranslateModule, StatusBadgeComponent],
  templateUrl: './precios.component.html',
  styleUrl: './precios.component.scss',
})
export class PreciosComponent {
  private readonly traductor = inject(TranslateService);

  readonly tiers = TIERS;

  /** Las filas de la comparativa, en el orden de `TIERS`. */
  readonly filas: readonly FilaComparativa[] = [
    { clave: 'portal.precios.fila_productos', valores: ['100', '500', 'ilimitado'] },
    { clave: 'portal.precios.fila_usuarios', valores: ['1', '2', '3'] },
    { clave: 'portal.precios.fila_fiado', valores: ['no', 'si', 'si'] },
    {
      clave: 'portal.precios.fila_asistente',
      valores: ['asistente_5_mes', 'asistente_30_dia', 'ilimitado'],
    },
    {
      clave: 'portal.precios.fila_reportes',
      valores: ['no', 'reportes_briefing', 'reportes_completos'],
    },
  ];

  precioDe(tier: TierComercial): string {
    return formatearPesos(tier.precioMensualPesos);
  }

  /** El ancla por día, redondeada al alza (nunca prometer de menos). Gratis no tiene. */
  porDiaDe(tier: TierComercial): string | null {
    if (tier.precioMensualPesos === 0) {
      return null;
    }
    return formatearPesos(pesosPorDia(tier.precioMensualPesos));
  }

  /** Cifra literal o traducción bajo `portal.precios`, según la celda. */
  textoDeCelda(celda: string): string {
    return /^\d+$/.test(celda) ? celda : this.traductor.instant(`portal.precios.${celda}`);
  }
}

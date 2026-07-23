// @ts-check
const { defineConfig } = require('eslint/config');
const rootConfig = require('../../eslint.config.js');
const { fronteraDeCapa } = require('../../eslint.fronteras.js');

module.exports = defineConfig([
  ...rootConfig,
  {
    files: ['**/*.ts'],
    rules: {
      '@angular-eslint/directive-selector': [
        'error',
        {
          type: 'attribute',
          prefix: 'vd',
          style: 'camelCase',
        },
      ],
      '@angular-eslint/component-selector': [
        'error',
        {
          type: 'element',
          prefix: 'vd',
          style: 'kebab-case',
        },
      ],
    },
  },
  {
    files: ['**/*.ts'],
    // `vendi-app` es la única app que corre dentro del contenedor nativo, pero eso
    // NO la autoriza a importar `@capacitor/*` a pelo: el README y ADR-011 dicen que
    // `native` es el único punto del workspace que lo hace, y una frontera que solo
    // vive en la documentación no es una frontera. Todo acceso a plataforma pasa por
    // la fachada de `native`.
    //
    // Los selectores de ADR-004 (cero monetización dentro de la app) viajan como
    // `selectoresExtra` del helper: si se declararan en un bloque aparte, los dos
    // `no-restricted-syntax` se pisarían y solo sobreviviría el último.
    rules: fronteraDeCapa(
      ['@capacitor/*'],
      'ADR-011: `native` es el único punto del workspace autorizado a importar @capacitor/*. Usa su fachada (p. ej. `esPlataformaNativa()` de `native`) en vez de @capacitor/core.',
      [
        {
          selector: 'Literal[value=/vendi\\.co\\/(pro|checkout|cuenta)/i]',
          message:
            'ADR-004: la app no puede enlazar al checkout web. La venta ocurre solo por canales propios (WhatsApp, portal).',
        },
        {
          selector: 'TemplateElement[value.raw=/vendi\\.co\\/(pro|checkout|cuenta)/i]',
          message:
            'ADR-004: la app no puede enlazar al checkout web, ni siquiera construyendo la URL por partes.',
        },
        {
          selector:
            'Literal[value=/suscr[ií]b(ete|ase|irse)|actualiza(r)? (tu|el) plan|mejora(r)? (tu|el) plan|compra(r)? (ahora|el plan)/i]',
          message:
            'ADR-004: cero CTAs de compra dentro de la app. Usa un badge Pro sin llamado a la acción (directiva *vdPro).',
        },
      ],
    ),
  },
  {
    files: ['**/*.html'],
    rules: {},
  },
]);

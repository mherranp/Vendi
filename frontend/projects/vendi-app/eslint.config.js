// @ts-check
const { defineConfig } = require('eslint/config');
const rootConfig = require('../../eslint.config.js');

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
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector: "Literal[value=/vendi\\.co\\/(pro|checkout|cuenta)/i]",
          message:
            'ADR-004: la app no puede enlazar al checkout web. La venta ocurre solo por canales propios (WhatsApp, portal).',
        },
        {
          selector:
            "TemplateElement[value.raw=/vendi\\.co\\/(pro|checkout|cuenta)/i]",
          message:
            'ADR-004: la app no puede enlazar al checkout web, ni siquiera construyendo la URL por partes.',
        },
        {
          selector:
            "Literal[value=/suscr[ií]b(ete|ase|irse)|actualiza(r)? (tu|el) plan|mejora(r)? (tu|el) plan|compra(r)? (ahora|el plan)/i]",
          message:
            'ADR-004: cero CTAs de compra dentro de la app. Usa un badge Pro sin llamado a la acción (directiva *vdPro).',
        },
      ],
    },
  },
  {
    files: ['**/*.html'],
    rules: {},
  },
]);

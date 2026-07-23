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
    rules: fronteraDeCapa(
      ['@capacitor/*', 'dexie', 'native'],
      'La consola del tenant es web pura: sin plataforma nativa ni persistencia offline. Puede usar ui-kit, domain, auth y data-access (data-access es la capa HTTP del monorepo — spec §6.2 —, no solo persistencia).',
    ),
  },
  {
    files: ['**/*.html'],
    rules: {},
  },
]);

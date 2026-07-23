// @ts-check
const { defineConfig } = require('eslint/config');
const rootConfig = require('../../../eslint.config.js');
const { fronteraDeCapa } = require('../../../eslint.fronteras.js');

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
      [
        '@angular/*',
        'rxjs',
        'rxjs/*',
        '@capacitor/*',
        'dexie',
        'ui-kit',
        'data-access',
        'auth',
        'native',
      ],
      'domain es lógica de negocio pura: sin framework, sin red, sin persistencia, sin UI. La reactividad vive en data-access y en las apps.',
    ),
  },
  {
    files: ['**/*.html'],
    rules: {},
  },
]);

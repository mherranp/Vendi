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
      ['@angular/common/http', '@capacitor/*', 'dexie', 'data-access', 'auth', 'native'],
      'ui-kit es presentación pura: sin HTTP, sin persistencia, sin plataforma nativa. Recibe datos por inputs y emite eventos por outputs.',
    ),
  },
  {
    files: ['**/*.html'],
    rules: {},
  },
]);

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
      ['ui-kit', 'dexie', '@capacitor/*'],
      'auth maneja identidad y entitlements. Puede usar data-access (la dependencia va auth → data-access). Para abrir el navegador del sistema usa la fachada de native, no @capacitor/browser directo.',
    ),
  },
  {
    files: ['**/*.html'],
    rules: {},
  },
]);

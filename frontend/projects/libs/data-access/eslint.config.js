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
      ['ui-kit', 'auth', '@capacitor/*'],
      'data-access no conoce la UI ni la sesión (la dependencia va auth → data-access, no al revés). El acceso a plataforma va por native.',
    ),
  },
  {
    files: ['**/*.html'],
    rules: {},
  },
]);

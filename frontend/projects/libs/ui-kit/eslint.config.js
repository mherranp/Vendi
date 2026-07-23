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
    // Excepción acotada a `src/lib/testing/`: utilidades de prueba que
    // `tsconfig.lib.json` excluye del paquete publicado, así que nada de esto
    // llega al bundle de una app ni al `dist/ui-kit`.
    //
    // El único import que se abre es `data-access`, y solo para reexportar
    // `CATALOGO_MINIMO_ES` como catálogo de los specs. El motivo es un defecto
    // real: mientras `ui-kit/testing` mantuvo su propia copia de las
    // traducciones, los specs pasaban con un catálogo completo mientras la ruta
    // degradada de producción (catálogo HTTP inaccesible, PWA sin red) usaba
    // uno incompleto y pintaba claves crudas —`ui.404.titulo`,
    // `ui.validacion.requerido`— en pantalla. Compartiendo la constante, la
    // suite de `ui-kit` ES la prueba de la ruta degradada y la deriva deja de
    // ser posible.
    //
    // El resto de la frontera sigue vigente aquí: sin HTTP, sin Capacitor, sin
    // dexie, sin auth y sin native.
    // El patrón lleva `**/` delante porque en el config plano las rutas se
    // resuelven contra el cwd desde el que corre ESLint (la raíz del workspace),
    // no contra el directorio de este archivo.
    files: ['**/src/lib/testing/**/*.ts'],
    rules: fronteraDeCapa(
      ['@angular/common/http', '@capacitor/*', 'dexie', 'auth', 'native'],
      'ui-kit es presentación pura: sin HTTP, sin persistencia, sin plataforma nativa. (En src/lib/testing/ se permite importar data-access solo para compartir el catálogo de traducción de respaldo.)',
    ),
  },
  {
    files: ['**/*.html'],
    rules: {},
  },
]);

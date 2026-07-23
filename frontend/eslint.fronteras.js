// @ts-check
/**
 * Fronteras de dependencia entre capas (ADR-011, spec §6.3).
 *
 * `no-restricted-imports` solo visita `ImportDeclaration`, `ExportNamedDeclaration`,
 * `ExportAllDeclaration` y `TSImportEqualsDeclaration` (ver
 * `node_modules/eslint/lib/rules/no-restricted-imports.js`). **No inspecciona
 * `ImportExpression`**, así que un `import('data-access')` dinámico —algo que Angular
 * usa de forma rutinaria para lazy loading— se salta la frontera entera.
 *
 * Este módulo emite, a partir de un único grupo de patrones, las dos reglas que hacen
 * falta para cerrar el hueco:
 *
 *  - `no-restricted-imports` para la forma estática.
 *  - `no-restricted-syntax` para la forma dinámica: `import(...)`, el tipo
 *    `import('...').Algo` y `require(...)`.
 *
 * Así el grupo prohibido se declara una sola vez por capa y no puede quedar
 * desincronizado entre las dos reglas.
 */

/**
 * Escapa los metacaracteres de expresión regular salvo `*`, que se traduce aparte.
 * @param {string} texto
 * @returns {string}
 */
function escaparRegex(texto) {
  return texto.replace(/[.+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Traduce un patrón de `no-restricted-imports` (sintaxis .gitignore, resuelta por el
 * paquete `ignore`) a una expresión regular equivalente para los casos que usamos:
 *
 *  - `data-access`        → coincide con `data-access` y con cualquier ruta relativa
 *                           que lo contenga como segmento (`../../libs/data-access/x`).
 *  - `@capacitor/*`       → coincide con `@capacitor/browser`, no con `@capacitorio`.
 *  - `@angular/common/http` → coincide con la ruta exacta.
 *
 * @param {string} patron
 * @returns {string} fuente de la expresión regular, sin delimitadores
 */
function patronARegex(patron) {
  const cuerpo = escaparRegex(patron).replace(/\*/g, '[^/]*');
  return `(^|/)${cuerpo}(/|$)`;
}

/**
 * Escapa la fuente de una regex para incrustarla como literal `/.../` dentro de un
 * selector esquery: la barra terminaría el literal antes de tiempo.
 * @param {string} fuente
 * @returns {string}
 */
function escaparParaSelector(fuente) {
  return fuente.replace(/\//g, '\\/');
}

/**
 * Construye el bloque de reglas que materializa una frontera de capa.
 *
 * @param {string[]} grupo patrones prohibidos (mismo formato que `no-restricted-imports`)
 * @param {string} mensaje explicación en español que ve quien viola la frontera
 * @param {{selector: string, message: string}[]} [selectoresExtra] entradas adicionales
 *        de `no-restricted-syntax` propias de la app (p. ej. ADR-004 en `vendi-app`)
 * @returns {Record<string, unknown>} objeto `rules` listo para el config plano
 */
function fronteraDeCapa(grupo, mensaje, selectoresExtra = []) {
  const alternancia = grupo.map(patronARegex).join('|');
  const regexSelector = escaparParaSelector(alternancia);
  const mensajeDinamico = `${mensaje} (La frontera también aplica al import dinámico: import() no es una puerta trasera.)`;

  return {
    'no-restricted-imports': [
      'error',
      {
        patterns: [
          {
            group: grupo,
            message: mensaje,
          },
        ],
      },
    ],
    'no-restricted-syntax': [
      'error',
      ...selectoresExtra,
      {
        // import('data-access') — lazy loading y carga condicional.
        selector: `ImportExpression > Literal[value=/${regexSelector}/]`,
        message: mensajeDinamico,
      },
      {
        // type Algo = import('data-access').Algo — el hueco en posición de tipo.
        selector: `TSImportType > Literal[value=/${regexSelector}/]`,
        message: mensajeDinamico,
      },
      {
        // require('data-access') — interop CommonJS.
        selector: `CallExpression[callee.name='require'] > Literal[value=/${regexSelector}/]`,
        message: mensajeDinamico,
      },
    ],
  };
}

module.exports = { fronteraDeCapa, patronARegex };

#!/usr/bin/env node
/**
 * Candado de contraste WCAG 2.1 AA sobre los tokens de color de `ui-kit`.
 *
 * Por qué existe como script y no como spec de vitest: los pares de color viven
 * en `_tokens.scss` y el runner de pruebas (esbuild) no tiene cargador para
 * `.scss`, así que un spec no puede leer el archivo — solo podría llevar una
 * copia de los valores, que es exactamente la segunda fuente de verdad que hace
 * inútil al candado. Este script parsea el SCSS real: si alguien cambia un
 * color, aquí se entera.
 *
 * Uso:
 *     cd frontend && npm run verificar:contraste
 *
 * Sale con código 1 si algún par baja del mínimo. Pensado para engancharse
 * también como paso de CI en la Etapa 5.
 */
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const AQUI = dirname(fileURLToPath(import.meta.url));
const TOKENS = resolve(AQUI, '../projects/libs/ui-kit/src/lib/theme/_tokens.scss');

/** Mínimo de WCAG 2.1 AA para texto normal (< 18pt / < 14pt en negrita). */
const MINIMO_AA = 4.5;

// --- Colorimetría ------------------------------------------------------------

/** Canal sRGB (0-255) a luminancia lineal. */
function lineal(canal) {
  const c = canal / 255;
  return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

/** Luminancia relativa de un `#rrggbb`. */
function luminancia(hex) {
  const limpio = hex.replace('#', '');
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(limpio.slice(i, i + 2), 16));
  return 0.2126 * lineal(r) + 0.7152 * lineal(g) + 0.0722 * lineal(b);
}

/** Razón de contraste entre dos colores opacos. */
function contraste(a, b) {
  const [la, lb] = [luminancia(a), luminancia(b)];
  const [alto, bajo] = la > lb ? [la, lb] : [lb, la];
  return (alto + 0.05) / (bajo + 0.05);
}

/** Compone `frente` con opacidad `alfa` sobre `fondo` opaco. */
function componer(frente, fondo, alfa) {
  const f = frente.replace('#', '');
  const b = fondo.replace('#', '');
  let salida = '#';
  for (const i of [0, 2, 4]) {
    const cf = parseInt(f.slice(i, i + 2), 16);
    const cb = parseInt(b.slice(i, i + 2), 16);
    salida += Math.round(alfa * cf + (1 - alfa) * cb)
      .toString(16)
      .padStart(2, '0');
  }
  return salida;
}

// --- Lectura de los tokens ---------------------------------------------------

const fuente = readFileSync(TOKENS, 'utf8');

/**
 * Extrae `--nombre: #rrggbb;` del bloque indicado.
 *
 * El archivo declara los tokens claros en `:root` y los oscuros dentro del
 * mixin `vd-tokens-oscuros`. Se parte por el encabezado del mixin en vez de
 * intentar equilibrar llaves: es frágil pero verificable de un vistazo, y si el
 * archivo se reestructura el script falla ruidosamente (token no encontrado) en
 * lugar de dar un falso verde.
 */
function tokensHex(texto) {
  const mapa = new Map();
  for (const [, nombre, valor] of texto.matchAll(/(--vd-[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) {
    if (!mapa.has(nombre)) mapa.set(nombre, valor.toLowerCase());
  }
  return mapa;
}

const corte = fuente.indexOf('@mixin vd-tokens-oscuros');
if (corte === -1) {
  console.error('No encuentro el mixin vd-tokens-oscuros en _tokens.scss. ¿Se reestructuró?');
  process.exit(2);
}
const claros = tokensHex(fuente.slice(0, corte));
const oscuros = tokensHex(fuente.slice(corte));

/** Los tokens oscuros solo redefinen algunos; el resto se hereda de `:root`. */
function token(mapa, nombre, respaldo) {
  const valor = mapa.get(nombre) ?? respaldo?.get(nombre);
  if (!valor) {
    console.error(`Token no declarado en _tokens.scss: ${nombre}`);
    process.exit(2);
  }
  return valor;
}

// --- Casos a verificar -------------------------------------------------------

const VARIANTES = ['exito', 'info', 'aviso', 'peligro', 'neutro'];

/**
 * Superficies de Material 3 sobre las que se compone el texto translúcido.
 * Son los valores que `mat.theme()` emite para `--mat-sys-surface` y
 * `--mat-sys-on-surface-variant` con la paleta azure que usan las apps.
 */
const SUPERFICIE_CLARA = '#faf9fd';
const SUPERFICIE_OSCURA = '#141218';
const VARIANTE_CLARA = '#49454f';
const VARIANTE_OSCURA = '#cac4d0';

const casos = [];

for (const v of VARIANTES) {
  casos.push({
    nombre: `insignia ${v} (claro)`,
    texto: token(claros, `--vd-insignia-${v}-texto`),
    fondo: token(claros, `--vd-insignia-${v}-fondo`),
  });
  casos.push({
    nombre: `insignia ${v} (oscuro)`,
    texto: token(oscuros, `--vd-insignia-${v}-texto`, claros),
    fondo: token(oscuros, `--vd-insignia-${v}-fondo`, claros),
  });
}

// `--vd-texto-terciario` es un `color-mix(... N%, transparent)`: se lee el
// porcentaje del propio SCSS y se compone sobre la superficie de cada esquema.
const mezcla = fuente.match(/--vd-texto-terciario:[\s\S]*?(\d+)%/);
if (!mezcla) {
  console.error('No pude leer el porcentaje de --vd-texto-terciario.');
  process.exit(2);
}
const alfaTerciario = Number(mezcla[1]) / 100;
casos.push({
  nombre: `texto terciario ${mezcla[1]}% (claro)`,
  texto: componer(VARIANTE_CLARA, SUPERFICIE_CLARA, alfaTerciario),
  fondo: SUPERFICIE_CLARA,
});
casos.push({
  nombre: `texto terciario ${mezcla[1]}% (oscuro)`,
  texto: componer(VARIANTE_OSCURA, SUPERFICIE_OSCURA, alfaTerciario),
  fondo: SUPERFICIE_OSCURA,
});

// --- Informe -----------------------------------------------------------------

let fallos = 0;
console.log(`Contraste WCAG 2.1 AA (mínimo ${MINIMO_AA}:1) — ${TOKENS}\n`);
for (const caso of casos) {
  const razon = contraste(caso.texto, caso.fondo);
  const pasa = razon >= MINIMO_AA;
  if (!pasa) fallos += 1;
  console.log(
    `  ${pasa ? '✓' : '✗'} ${caso.nombre.padEnd(30)} ${caso.texto} sobre ${caso.fondo} = ${razon.toFixed(2)}:1`,
  );
}

if (fallos > 0) {
  console.error(`\n${fallos} par(es) por debajo de ${MINIMO_AA}:1. Corrige los tokens.`);
  process.exit(1);
}
console.log(`\n${casos.length} pares verificados, todos ≥ ${MINIMO_AA}:1.`);

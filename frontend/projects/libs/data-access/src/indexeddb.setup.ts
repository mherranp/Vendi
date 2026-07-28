/**
 * IndexedDB falsa para los specs (jsdom no la implementa).
 *
 * `fake-indexeddb/auto` registra los globales sobre `window`, pero en el
 * entorno jsdom de Vitest el `window` de jsdom y el `globalThis` del worker
 * de Node son objetos distintos, y Dexie captura `globalThis.indexedDB` al
 * evaluarse el módulo. Este archivo —que el builder de pruebas evalúa ANTES
 * que cualquier spec (`setupFiles` en angular.json)— instala la fábrica falsa
 * en el global que Dexie lee. Los specs siguen importando 'fake-indexeddb/auto'
 * primero por documentación del patrón, pero el global efectivo sale de aquí.
 */
import fakeIndexedDB, { IDBKeyRange } from 'fake-indexeddb';

Object.assign(globalThis, { indexedDB: fakeIndexedDB, IDBKeyRange });

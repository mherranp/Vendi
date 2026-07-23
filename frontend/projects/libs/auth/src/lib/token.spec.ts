import { aliasDeOrganizaciones, rolesDeRealm } from './token';

const ORG_A = '1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e';
const ORG_B = '2c9f1e5f-9a4b-4d3c-8e6f-3a7b8c9d0e1f';

describe('aliasDeOrganizaciones', () => {
  it('acepta la forma POR DEFECTO de Keycloak 26: lista de alias', () => {
    // Medido en el informe de verificación (Pregunta 1): sin
    // `addOrganizationId`, el claim es un array de strings.
    expect(aliasDeOrganizaciones([ORG_A, ORG_B])).toEqual([ORG_A, ORG_B]);
  });

  it('acepta la forma de MAPA que aparece con addOrganizationId=true', () => {
    const claim = {
      [ORG_A]: { id: 'kc-org-1' },
      [ORG_B]: { id: 'kc-org-2' },
    };
    expect(aliasDeOrganizaciones(claim)).toEqual([ORG_A, ORG_B]);
  });

  it('acepta el mapa aunque el valor venga vacío o nulo', () => {
    expect(aliasDeOrganizaciones({ [ORG_A]: null })).toEqual([ORG_A]);
    expect(aliasDeOrganizaciones({ [ORG_A]: {} })).toEqual([ORG_A]);
  });

  it('devuelve lista vacía cuando el claim falta (caso normal, no error)', () => {
    // Usuario multi-organización que no pidió scope=organization:*, o usuario
    // de plataforma sin ninguna organización.
    expect(aliasDeOrganizaciones(undefined)).toEqual([]);
    expect(aliasDeOrganizaciones(null)).toEqual([]);
    expect(aliasDeOrganizaciones([])).toEqual([]);
    expect(aliasDeOrganizaciones({})).toEqual([]);
  });

  it('descarta alias que no son UUID en lugar de propagarlos', () => {
    // Un alias no-UUID no puede acabar en X-Tenant-Id: el backend responde 401
    // ante eso y aquí el equivalente es "no hay tenant".
    expect(aliasDeOrganizaciones(['acme'])).toEqual([]);
    expect(aliasDeOrganizaciones({ acme: { id: 'x' } })).toEqual([]);
    expect(aliasDeOrganizaciones([ORG_A, 'acme'])).toEqual([ORG_A]);
  });

  it('tolera basura en el claim sin lanzar', () => {
    expect(aliasDeOrganizaciones('texto')).toEqual([]);
    expect(aliasDeOrganizaciones(42)).toEqual([]);
    expect(aliasDeOrganizaciones([null, undefined, 7])).toEqual([]);
  });

  it('deduplica alias repetidos', () => {
    expect(aliasDeOrganizaciones([ORG_A, ORG_A])).toEqual([ORG_A]);
  });
});

describe('rolesDeRealm', () => {
  it('devuelve los roles del token', () => {
    expect(rolesDeRealm({ realm_access: { roles: ['dueno'] } })).toEqual(['dueno']);
  });

  it('devuelve lista vacía si no hay token o no hay realm_access', () => {
    expect(rolesDeRealm(undefined)).toEqual([]);
    expect(rolesDeRealm({})).toEqual([]);
  });
});

import { Tenant, esEstadoTenant } from '../models/tenant.model';
import { esEstadoVisible, esIdDeTenant, esTenantOperativo } from './tenant.reglas';

const TENANT: Tenant = {
  id: '1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e',
  nombre: 'Tienda Don Carlos',
  estado: 'activo',
};

describe('esIdDeTenant', () => {
  it('acepta el UUID con guiones que Keycloak devuelve como alias', () => {
    // Alias real del informe de verificación de Organizations (Pregunta 4).
    expect(esIdDeTenant('1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0e')).toBe(true);
  });

  it('acepta el UUID en mayúsculas', () => {
    expect(esIdDeTenant('1B8E0D4E-8F3A-4C2B-9D5E-2F6A7B8C9D0E')).toBe(true);
  });

  it('rechaza un slug heredado, que es el modo de fallo que importa', () => {
    // BaseSaaS identificaba al tenant por un slug; si un token viejo o mal
    // configurado trae "acme", no puede terminar en la cabecera X-Tenant-Id.
    expect(esIdDeTenant('acme')).toBe(false);
  });

  it('rechaza cadenas casi-UUID, vacías y valores no string', () => {
    expect(esIdDeTenant('1b8e0d4e8f3a4c2b9d5e2f6a7b8c9d0e')).toBe(false); // sin guiones
    expect(esIdDeTenant('1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0')).toBe(false); // un dígito menos
    expect(esIdDeTenant('1b8e0d4e-8f3a-4c2b-9d5e-2f6a7b8c9d0ee')).toBe(false); // uno de más
    expect(esIdDeTenant('zzzzzzzz-8f3a-4c2b-9d5e-2f6a7b8c9d0e')).toBe(false); // no hexadecimal
    expect(esIdDeTenant('')).toBe(false);
    expect(esIdDeTenant(null)).toBe(false);
    expect(esIdDeTenant(undefined)).toBe(false);
    expect(esIdDeTenant(42)).toBe(false);
    expect(esIdDeTenant({ id: TENANT.id })).toBe(false);
  });
});

describe('esTenantOperativo', () => {
  it('solo el tenant activo opera', () => {
    expect(esTenantOperativo(TENANT)).toBe(true);
    expect(esTenantOperativo({ ...TENANT, estado: 'suspendido' })).toBe(false);
    expect(esTenantOperativo({ ...TENANT, estado: 'eliminado' })).toBe(false);
  });

  it('sin tenant no se opera (falla cerrado)', () => {
    expect(esTenantOperativo(null)).toBe(false);
    expect(esTenantOperativo(undefined)).toBe(false);
  });
});

describe('esEstadoVisible', () => {
  it('oculta los eliminados y muestra el resto', () => {
    expect(esEstadoVisible('activo')).toBe(true);
    expect(esEstadoVisible('suspendido')).toBe(true);
    expect(esEstadoVisible('eliminado')).toBe(false);
  });
});

describe('esEstadoTenant', () => {
  it('reconoce los tres estados del contrato', () => {
    expect(esEstadoTenant('activo')).toBe(true);
    expect(esEstadoTenant('suspendido')).toBe(true);
    expect(esEstadoTenant('eliminado')).toBe(true);
  });

  it('rechaza un estado desconocido en vez de dejarlo pasar', () => {
    expect(esEstadoTenant('en_mora')).toBe(false);
    expect(esEstadoTenant('ACTIVO')).toBe(false);
    expect(esEstadoTenant(undefined)).toBe(false);
  });
});

"""Resolución de secretos: backend `env` y backend `file`.

Procedencia: `vendi_core.config.secrets` viene de `base_saas.config.secrets`.
BaseSaaS no tenía un test específico de este módulo (sí de
`base_saas.mail.secrets`, que es otra cosa: cifrado Fernet de credenciales SMTP
por inquilino, y que en Vendi no existe porque el mailer se redujo a
`SystemMailer`). Este archivo es nuevo y cubre el módulo tal cual está.

Lo que se fija:

- exactamente UN backend se consulta; en modo `file` no hay caída silenciosa a
  variables de entorno, porque un fichero que falta es un fallo de despliegue,
  no una invitación a mirar el entorno del proceso;
- un secreto que falta y sin `default` explícito revienta, en vez de devolver
  cadena vacía y dejar la app arrancada con una credencial en blanco;
- una errata en `SECRETS_BACKEND` cae a `env` en vez de a un backend inexistente.
"""

from __future__ import annotations

import pytest

from vendi_core.config.secrets import resolve_secret


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch):
    monkeypatch.delenv("SECRETS_BACKEND", raising=False)
    monkeypatch.delenv("SECRETS_FILE_ROOT", raising=False)
    yield


def test_el_backend_env_lee_la_variable_en_mayusculas(monkeypatch):
    monkeypatch.setenv("VENDI_CLAVE_DE_PRUEBA", "s3creto")
    assert resolve_secret("vendi_clave_de_prueba") == "s3creto"


def test_una_variable_vacia_cuenta_como_ausente(monkeypatch):
    """Una variable definida a "" es el error de despliegue más habitual, y el
    que peor falla: la app arranca con la credencial en blanco."""
    monkeypatch.setenv("VENDI_CLAVE_VACIA", "")
    assert resolve_secret("VENDI_CLAVE_VACIA", default="respaldo") == "respaldo"


def test_un_secreto_ausente_sin_default_revienta(monkeypatch):
    monkeypatch.delenv("VENDI_NO_EXISTE", raising=False)
    with pytest.raises(RuntimeError, match="VENDI_NO_EXISTE"):
        resolve_secret("VENDI_NO_EXISTE")


def test_un_secreto_ausente_con_default_none_devuelve_none(monkeypatch):
    """`default=None` es un valor explícito, no "no me pasaron default"."""
    monkeypatch.delenv("VENDI_NO_EXISTE", raising=False)
    assert resolve_secret("VENDI_NO_EXISTE", default=None) is None


def test_el_backend_file_lee_del_directorio_montado(monkeypatch, tmp_path):
    (tmp_path / "VENDI_CLAVE_MONTADA").write_text("desde-fichero\n", encoding="utf-8")
    monkeypatch.setenv("SECRETS_BACKEND", "file")
    monkeypatch.setenv("SECRETS_FILE_ROOT", str(tmp_path))
    # Se recorta un único salto de línea final: `echo "secreto" > fichero` es el
    # flujo normal y el salto no forma parte del secreto.
    assert resolve_secret("VENDI_CLAVE_MONTADA") == "desde-fichero"


def test_el_backend_file_no_cae_al_entorno(monkeypatch, tmp_path):
    """La garantía central: un fichero que falta es un fallo de despliegue, no
    un motivo para mirar el entorno del proceso."""
    monkeypatch.setenv("SECRETS_BACKEND", "file")
    monkeypatch.setenv("SECRETS_FILE_ROOT", str(tmp_path))
    monkeypatch.setenv("VENDI_CLAVE_FANTASMA", "valor-del-entorno")
    with pytest.raises(RuntimeError, match="VENDI_CLAVE_FANTASMA"):
        resolve_secret("VENDI_CLAVE_FANTASMA")


def test_una_errata_en_el_backend_cae_a_env(monkeypatch):
    monkeypatch.setenv("SECRETS_BACKEND", "vualt")
    monkeypatch.setenv("VENDI_CLAVE_ERRATA", "valor")
    assert resolve_secret("VENDI_CLAVE_ERRATA") == "valor"


def test_el_nombre_del_fichero_se_usa_tal_cual(monkeypatch, tmp_path):
    """En modo `file` el nombre NO se pasa a mayúsculas: el montaje de Docker o
    Kubernetes decide el nombre y hay que respetarlo tal cual.

    (No se comprueba el caso contrario —buscar `CLAVE` cuando el fichero se
    llama `clave`— porque el sistema de ficheros de macOS no distingue
    mayúsculas y el test daría verde o rojo según la máquina, no según el
    código.)
    """
    (tmp_path / "clave_en_minusculas").write_text("v", encoding="utf-8")
    monkeypatch.setenv("SECRETS_BACKEND", "file")
    monkeypatch.setenv("SECRETS_FILE_ROOT", str(tmp_path))
    assert resolve_secret("clave_en_minusculas") == "v"

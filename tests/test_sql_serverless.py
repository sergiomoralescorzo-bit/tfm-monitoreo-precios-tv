# -*- coding: utf-8 -*-
"""Pruebas de la Etapa 4: scripts de SQL serverless (sin conectarse a Azure)."""
import re

import pytest

from src.nube import sql_serverless as sq

TABLAS_ORO = {"dimensiones/dim_producto", "dimensiones/dim_tienda", "dimensiones/dim_calendario",
              "hechos/fact_precio_diario", "hechos/fact_ejecucion", "hechos/fact_evento_comercial",
              "kpis/kpi_brecha_precio", "kpis/kpi_calidad_captura"}


def test_lotes_separa_por_go_y_descarta_comentarios():
    texto = "-- encabezado\nSELECT 1;\nGO\n-- solo comentario\n  go  \nSELECT 2;\nGOTO_NO_ES_SEPARADOR\n"
    assert sq.lotes(texto) == ["-- encabezado\nSELECT 1;", "SELECT 2;\nGOTO_NO_ES_SEPARADOR"]


def test_sustituir_variables():
    assert sq.sustituir("PASSWORD = '$(CLAVE)'", {"CLAVE": "x1"}) == "PASSWORD = 'x1'"
    with pytest.raises(KeyError, match="CLAVE"):
        sq.sustituir("PASSWORD = '$(CLAVE)'", {})


def test_clave_maestra_aleatoria_y_sin_comillas():
    a, b = sq.clave_maestra(), sq.clave_maestra()
    assert a != b and len(a) >= 30 and "'" not in a


def test_scripts_completos_solo_usan_la_clave_maestra():
    for archivo, base in sq.DESPLIEGUE + sq.VERIFICACION:
        texto = (sq.CARPETA / archivo).read_text(encoding="utf-8")
        assert set(re.findall(r"\$\((\w+)\)", texto)) <= {"CLAVE_MAESTRA"}
        assert sq.lotes(texto), archivo
    assert sq.DESPLIEGUE[0][1] == "master"


def test_permiso_por_usuario_solo_acepta_correos():
    assert sq.usuarios(" A.B@comunidadunir.net , c@x.co ") == ["a.b@comunidadunir.net", "c@x.co"]
    for malo in ["x]; DROP USER y; --@a.co", "sin-arroba", ""]:
        with pytest.raises(ValueError):
            sq.usuarios(malo)
    texto = sq.sustituir((sq.CARPETA / sq.PERMISO[0][0]).read_text(encoding="utf-8"), {"USUARIO": "a@b.co"})
    assert "CREATE USER [a@b.co] FROM EXTERNAL PROVIDER" in texto and "cred_identidad_synapse" in texto


def test_tope_diario_de_datos_procesados():
    texto = (sq.CARPETA / "00_base_de_datos.sql").read_text(encoding="utf-8")
    assert "sp_set_data_processed_limit @type = N'daily', @limit_tb = 1" in texto


def test_una_vista_por_tabla_de_oro():
    texto = (sq.CARPETA / "02_vistas_oro.sql").read_text(encoding="utf-8")
    rutas = re.findall(r"BULK '([^']+)/'", texto)
    vistas = re.findall(r"CREATE OR ALTER VIEW oro\.(\w+)", texto)
    assert set(rutas) == TABLAS_ORO and len(rutas) == len(TABLAS_ORO)
    assert vistas == [r.split("/")[1] for r in rutas]       # la vista se llama como la tabla
    assert "precio_medio_pago" not in texto                  # ya no existe en oro (16-oct)

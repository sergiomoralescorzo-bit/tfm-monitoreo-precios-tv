# -*- coding: utf-8 -*-
"""Detector de descuentos (src/medallon/detector.py) y eventos comerciales (src/medallon/eventos.py),
con una serie sintética de fact_precio_diario. Corre en Docker con el resto de tests_spark."""
from datetime import date, timedelta

import pytest

from src.medallon import detector, eventos, oro
from tests_spark.test_medallon import spark  # noqa: F401  (fixture de sesión)

P = {"detector": {"ventana_dias": 30, "min_dias_observados": 20, "margen": 0.05},
     "alertas": {"umbral_cambio_precio": 0.10, "max_por_tipo_en_resumen": 5}}
INICIO = date(2026, 10, 20)
COLUMNAS = ("fecha_key int, producto_key string, tienda_key int, precio_lista long, precio_venta long, "
            "descuento_pct double, disponible boolean, url string, ruta_bronze string, motivos_atipico string")


def fila(dia: int, venta: int, lista: int, disponible=True, producto="P1", tienda=1):
    f = INICIO + timedelta(days=dia)
    descuento = round(1 - venta / lista, 4) if lista > venta else None
    return (int(f.strftime("%Y%m%d")), producto, tienda, lista, venta, descuento, disponible, "u", "b", None)


def fact(spark, filas):
    return detector.agregar_columnas(spark.createDataFrame(filas, COLUMNAS), P)


def por_dia(df, producto="P1"):
    return {r["fecha_key"]: r for r in df.filter(f"producto_key = '{producto}'").collect()}


def key(dia):
    return int((INICIO + timedelta(days=dia)).strftime("%Y%m%d"))


def test_precio_inflado_antes_de_la_rebaja_se_marca(spark):  # noqa: F811
    # 30 días a 1.000.000 sin descuento; el día 30 la lista sube a 2.000.000 y la venta baja a 900.000:
    # anuncia 55 % pero frente al mínimo de 30 días solo hay 10 %.
    filas = [fila(d, 1_000_000, 1_000_000) for d in range(30)] + [fila(30, 900_000, 2_000_000)]
    r = por_dia(fact(spark, filas))[key(30)]
    assert r["precio_referencia_30d"] == 1_000_000
    assert r["dias_observados_30d"] == 30
    assert r["descuento_respaldado"] == pytest.approx(0.10)
    assert r["descuento_sin_respaldo"] is True


def test_descuento_real_no_se_marca(spark):  # noqa: F811
    # La lista siempre fue el precio de venta habitual: la rebaja anunciada coincide con la respaldada.
    filas = [fila(d, 2_000_000, 2_000_000) for d in range(30)] + [fila(30, 1_500_000, 2_000_000)]
    r = por_dia(fact(spark, filas))[key(30)]
    assert r["descuento_respaldado"] == pytest.approx(0.25)
    assert r["descuento_sin_respaldo"] is False


def test_pocos_dias_observados_deja_el_indicador_nulo(spark):  # noqa: F811
    # Solo 19 días con existencias en la ventana: no se evalúa.
    filas = ([fila(d, 1_000_000, 1_000_000) for d in range(19)]
             + [fila(d, 1_000_000, 1_000_000, disponible=False) for d in range(19, 30)]
             + [fila(30, 900_000, 2_000_000)])
    r = por_dia(fact(spark, filas))[key(30)]
    assert r["dias_observados_30d"] == 19
    assert r["descuento_respaldado"] is None and r["descuento_sin_respaldo"] is None


def test_la_ventana_no_incluye_el_dia_evaluado_ni_dias_viejos(spark):  # noqa: F811
    # Un precio bajo hace 31 días queda fuera de la ventana; el del propio día no cuenta como referencia.
    filas = ([fila(0, 500_000, 500_000)] + [fila(d, 1_000_000, 1_000_000) for d in range(1, 31)]
             + [fila(31, 800_000, 1_000_000)])
    r = por_dia(fact(spark, filas))[key(31)]
    assert r["precio_referencia_30d"] == 1_000_000
    assert r["descuento_sin_respaldo"] is False


def test_eventos_comerciales(spark):  # noqa: F811
    filas = [
        # P1: precio estable, luego baja 20 % (cambio), luego se agota.
        fila(0, 1_000_000, 1_000_000), fila(1, 1_000_000, 1_000_000), fila(2, 800_000, 1_000_000),
        fila(3, 800_000, 1_000_000, disponible=False),
        # P2: promoción que termina con subida de precio.
        fila(0, 900_000, 1_000_000, producto="P2"), fila(1, 1_000_000, 1_000_000, producto="P2"),
        # P3: aparece el día 2 (nuevo); P4 está desde el primer día (no es nuevo).
        fila(2, 700_000, 700_000, producto="P3"), fila(0, 600_000, 600_000, producto="P4"),
    ]
    ev = eventos.fact_evento_comercial(fact(spark, filas), P)
    got = sorted((r["producto_key"], r["tipo_evento"], r["fecha_key"]) for r in ev.collect())
    assert got == sorted([
        ("P1", "CAMBIO_PRECIO", key(2)), ("P1", "AGOTADO", key(3)),
        ("P2", "FIN_PROMOCION", key(1)), ("P3", "PRODUCTO_NUEVO", key(2)),
    ])
    cambio = ev.filter("tipo_evento = 'CAMBIO_PRECIO'").first()
    assert (cambio["precio_anterior"], cambio["precio_actual"], cambio["variacion_pct"]) == (1_000_000, 800_000, -0.2)
    assert cambio["dias_desde_anterior"] == 1


def test_descuento_sin_respaldo_avisa_solo_al_empezar(spark):  # noqa: F811
    filas = ([fila(d, 1_000_000, 1_000_000) for d in range(30)]
             + [fila(30, 900_000, 2_000_000), fila(31, 900_000, 2_000_000)])
    ev = eventos.fact_evento_comercial(fact(spark, filas), P).filter("tipo_evento = 'DESCUENTO_SIN_RESPALDO'")
    assert [r["fecha_key"] for r in ev.collect()] == [key(30)]


def test_brecha_no_usa_precios_atipicos(spark):  # noqa: F811
    cols = ("fecha_key int, producto_key string, tienda_key int, precio_venta long, disponible boolean, "
            "metodo_emparejamiento string, motivos_atipico string")
    filas = [(20261119, "P1", 1, 1_000_000, True, "EAN", None),          # Alkosto
             (20261119, "P1", 3, 1_050_000, True, "EAN", None),          # Jumbo
             (20261119, "P1", 4, 3_000_000, True, "EAN", "CAMBIO_BRUSCO")]  # Olímpica, atípico
    b = oro.kpi_brecha_precio(spark.createDataFrame(filas, cols), oro.dim_tienda(spark)).first()
    assert b["n_cadenas"] == 2
    assert b["precio_max"] == 1_050_000
    assert b["brecha_pct"] == pytest.approx(0.05)

# -*- coding: utf-8 -*-
"""Proceso semanal del medallón: bronce/aterrizaje -> bronce/conformidad -> plata -> oro.

En Synapse lo llama el notebook `nb_medallon_semanal` (synapse/notebooks/) tras cargar el código con
`sc.addPyFile(".../codigo/tfm_src.zip")`. En local, las pruebas de tests_spark/ lo ejecutan sobre
una carpeta que imita al lago.
"""
import time

from pyspark.sql import SparkSession

from src.medallon import conformidad, oro, plata
from src.medallon.rutas import SITIOS, Rutas


def ejecutar(spark: SparkSession, base: str, sitios: list[str] = SITIOS) -> dict[str, dict[str, int]]:
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    rutas = Rutas(base)
    resumen = {}
    for nombre, paso in (("conformidad", conformidad.cargar), ("plata", plata.construir), ("oro", oro.construir)):
        t0 = time.monotonic()
        resumen[nombre] = paso(spark, rutas, sitios)
        resumen[nombre]["_segundos"] = round(time.monotonic() - t0)
        print(f"{nombre}: {resumen[nombre]}")
    return resumen

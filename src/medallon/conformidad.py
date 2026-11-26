# -*- coding: utf-8 -*-
"""Bronce: aterrizaje -> conformidad.

Convierte los CSV de la zona de aterrizaje en tablas Delta **sin transformar los datos**: todas las
columnas quedan como texto, igual que en el archivo. Solo se agregan metadatos de carga:
    _archivo_origen   ruta del archivo de origen relativa al lago (`bronce/aterrizaje/...`), para la
                      trazabilidad y la carga incremental; no depende de dónde corra Spark (local o abfss://)
    _fecha_carga      momento de la carga
    fecha             partición AAAA-MM-DD (día de la corrida en Colombia), tomada de la ruta
                      (`crudo/AAAA/MM/DD/...`) o del nombre (`ejecucion_AAAAMMDD_HHMMSS.json`)
La carga es incremental: un archivo ya cargado no se vuelve a cargar.
"""
from delta.tables import DeltaTable
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.utils import AnalysisException

from src.medallon.rutas import SITIOS, Rutas


def leer_csv(spark: SparkSession, patron: str) -> DataFrame | None:
    """CSV de la captura (separador `;`, UTF-8 con o sin BOM), todo como texto. None si no hay archivos."""
    try:
        df = (spark.read.option("header", True).option("sep", ";").option("encoding", "UTF-8")
              .option("quote", '"').option("escape", '"').option("multiLine", True).csv(patron))
    except AnalysisException as e:
        if "Path does not exist" in str(e) or "PATH_NOT_FOUND" in str(e):
            return None
        raise
    return df.toDF(*[c.lstrip("﻿") for c in df.columns])


def leer_json(spark: SparkSession, patron: str) -> DataFrame | None:
    """Un objeto JSON por archivo, todo como texto. None si no hay archivos."""
    try:
        return spark.read.option("multiLine", True).option("primitivesAsString", True).json(patron)
    except AnalysisException as e:
        if "Path does not exist" in str(e) or "PATH_NOT_FOUND" in str(e):
            return None
        raise


RUTA_EN_LAGO = r"(bronce/aterrizaje/.+)$"
FECHA_EN_CARPETA = r"/(\d{4})/(\d{2})/(\d{2})/[^/]+$"
FECHA_EN_NOMBRE = r"_(\d{4})(\d{2})(\d{2})_\d{6}\.json$"


def archivo_origen():
    return F.regexp_extract(F.input_file_name(), RUTA_EN_LAGO, 1)


def con_metadatos(df: DataFrame, patron_fecha: str) -> DataFrame:
    df = df.withColumn("_archivo_origen", archivo_origen()).withColumn("_fecha_carga", F.current_timestamp())
    partes = [F.regexp_extract("_archivo_origen", patron_fecha, i) for i in (1, 2, 3)]
    return df.withColumn("fecha", F.concat_ws("-", *partes))


def cargar_incremental(spark: SparkSession, df: DataFrame | None, patron_fecha: str, destino: str) -> int:
    """Agrega a la tabla Delta `destino` los archivos leídos en `df` que aún no estén cargados."""
    if df is None:
        return 0
    df = con_metadatos(df, patron_fecha)
    if DeltaTable.isDeltaTable(spark, destino):
        cargados = spark.read.format("delta").load(destino).select("_archivo_origen").distinct()
        df = df.join(cargados, "_archivo_origen", "left_anti")
    df = df.cache()
    n = df.count()
    if n:
        (df.write.format("delta").mode("append").option("mergeSchema", "true")
           .partitionBy("fecha").save(destino))
    df.unpersist()
    return n


def cargar_maestro(spark: SparkSession, rutas: Rutas) -> int:
    df = leer_csv(spark, rutas.maestro_csv)
    if df is None:
        return 0
    df = (df.withColumn("_archivo_origen", archivo_origen())
            .withColumn("_fecha_carga", F.current_timestamp()))
    df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").save(rutas.conformidad_maestro)
    return spark.read.format("delta").load(rutas.conformidad_maestro).count()


def cargar(spark: SparkSession, rutas: Rutas, sitios: list[str] = SITIOS) -> dict[str, int]:
    """Carga todo lo nuevo de la zona de aterrizaje. Devuelve filas cargadas por tabla."""
    resumen = {"maestro": cargar_maestro(spark, rutas)}
    for s in sitios:
        resumen[f"{s}/productos"] = cargar_incremental(
            spark, leer_csv(spark, f"{rutas.aterrizaje(s, 'crudo')}/*/*/*/productos_*.csv"),
            FECHA_EN_CARPETA, rutas.conformidad(s, "productos"))
        resumen[f"{s}/ejecuciones"] = cargar_incremental(
            spark, leer_json(spark, f"{rutas.aterrizaje(s, 'ejecuciones')}/ejecucion_*.json"),
            FECHA_EN_NOMBRE, rutas.conformidad(s, "ejecuciones"))
    return resumen

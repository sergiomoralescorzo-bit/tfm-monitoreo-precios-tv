# -*- coding: utf-8 -*-
"""Datos del día para el resumen y las alertas, leídos de la capa oro con Spark (solo lectura).

Devuelve un diccionario serializable que `src/servicios/avisos.py` convierte en mensajes. Se guarda
también en el lago (oro/servicios/avisos/) como evidencia de lo que se envió.
"""
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from src.medallon.rutas import Rutas


def _fecha_iso(fecha_key: int) -> str:
    s = str(fecha_key)
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def leer(spark: SparkSession, base: str, fecha_key: int | None = None) -> dict:
    r = Rutas(base)
    leer_ = lambda t: spark.read.format("delta").load(r.oro(t))  # noqa: E731
    fact = leer_("hechos/fact_precio_diario")
    fecha_key = fecha_key or fact.agg(F.max("fecha_key")).first()[0]
    productos = leer_("dimensiones/dim_producto").select("producto_key", "descripcion", "marca", "pulgadas",
                                                         "referencia")
    tiendas = leer_("dimensiones/dim_tienda")

    eventos = (leer_("hechos/fact_evento_comercial").filter(F.col("fecha_key") == fecha_key)
               .join(productos, "producto_key", "left").join(tiendas, "tienda_key", "left"))
    hoy = fact.filter(F.col("fecha_key") == fecha_key)
    ofertas = hoy.filter("disponible").agg(F.count("*").alias("con_stock"),
                                           F.countDistinct("tienda_key").alias("sitios")).first()

    brecha = leer_("kpis/kpi_brecha_precio")
    anterior = brecha.filter(F.col("fecha_key") < fecha_key).agg(F.max("fecha_key")).first()[0]
    media = lambda k: brecha.filter(F.col("fecha_key") == k).agg(F.avg("brecha_pct")).first()[0] if k else None  # noqa: E731
    comparables = brecha.filter(F.col("fecha_key") == fecha_key).count()

    evaluables = hoy.filter("disponible AND descuento_sin_respaldo IS NOT NULL").join(tiendas.select("tienda_key", "cadena"), "tienda_key")
    detector_por_cadena = [x.asDict() for x in evaluables.groupBy("cadena").agg(
        F.count("*").alias("evaluables"), F.sum(F.col("descuento_sin_respaldo").cast("int")).alias("marcadas"),
        F.avg("descuento_pct").alias("anunciado"), F.avg("descuento_respaldado").alias("respaldado"))
        .orderBy("cadena").collect()]

    ejecuciones = []
    try:
        ej = leer_("hechos/fact_ejecucion").filter(F.col("fecha_key") == fecha_key)
        ultima = ej.groupBy("tienda_key").agg(F.max("id_ejecucion").alias("id_ejecucion"))
        ejecuciones = [x.asDict() for x in ej.join(ultima, ["tienda_key", "id_ejecucion"])
                       .join(tiendas, "tienda_key").select("tienda", "estado", "consultados", "descubiertos")
                       .orderBy("tienda").collect()]
    except Exception:  # sin registro de ejecuciones (ensayos locales)
        pass

    def fila(x):
        d = x.asDict()
        for k, v in list(d.items()):
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        return d

    return {
        "fecha": _fecha_iso(fecha_key),
        "fecha_key": fecha_key,
        "ofertas": {"con_stock": ofertas["con_stock"], "sitios": ofertas["sitios"]},
        "productos_comparables": comparables,
        "brecha": {"media": media(fecha_key), "media_anterior": media(anterior)},
        "marcadas_vigentes": hoy.filter("descuento_sin_respaldo").count(),
        "detector_por_cadena": detector_por_cadena,
        "eventos": [fila(x) for x in eventos.collect()],
        "ejecuciones": ejecuciones,
    }

# -*- coding: utf-8 -*-
"""Eventos comerciales para las alertas y el resumen diario (RF-10; memoria, subapartado 5.3.6.4).

`fact_evento_comercial` (tipo de evento × producto × tienda × día) compara cada oferta con su
observación anterior en la misma tienda (no necesariamente el día anterior: los días sin captura
dejan huecos y `dias_desde_anterior` lo deja ver). Tipos:

    CAMBIO_PRECIO            con existencias en las dos observaciones y |venta / venta anterior − 1| ≥ umbral,
                             salvo que sea un FIN_PROMOCION
    AGOTADO                  tenía existencias y ya no
    FIN_PROMOCION            con existencias, tenía descuento anunciado (lista > venta), ya no lo tiene
                             y el precio de venta subió
    PRODUCTO_NUEVO           primera observación de la oferta en la tienda, con existencias, después del
                             primer día con datos de esa tienda (si no, todo el primer día sería «nuevo»)
    DESCUENTO_SIN_RESPALDO   el detector marca la oferta hoy y no la marcaba en la observación anterior

Se reconstruye completa en cada corrida, como el resto de oro.
"""
from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

from src.medallon.detector import parametros

TIPOS = ["CAMBIO_PRECIO", "AGOTADO", "FIN_PROMOCION", "PRODUCTO_NUEVO", "DESCUENTO_SIN_RESPALDO"]


def fact_evento_comercial(fact: DataFrame, p: dict | None = None) -> DataFrame:
    """`fact` es fact_precio_diario con las columnas del detector."""
    umbral = float((p or parametros())["alertas"]["umbral_cambio_precio"])
    w = Window.partitionBy("producto_key", "tienda_key").orderBy("fecha_key")
    fecha = lambda c: F.to_date(F.col(c).cast("string"), "yyyyMMdd")  # noqa: E731
    df = (fact
          .withColumn("fecha_anterior_key", F.lag("fecha_key").over(w))
          .withColumn("precio_anterior", F.lag("precio_venta").over(w))
          .withColumn("lista_anterior", F.lag("precio_lista").over(w))
          .withColumn("disponible_anterior", F.lag("disponible").over(w))
          .withColumn("sin_respaldo_anterior", F.lag("descuento_sin_respaldo").over(w))
          .withColumn("atipico_anterior", F.lag("motivos_atipico").over(w))
          .withColumn("_primer_dia_tienda", F.min("fecha_key").over(Window.partitionBy("tienda_key")))
          .withColumn("variacion_pct",
                      F.when(F.col("precio_anterior") > 0,
                             F.round(F.col("precio_venta") / F.col("precio_anterior") - 1, 4)))
          .withColumn("dias_desde_anterior", F.datediff(fecha("fecha_key"), fecha("fecha_anterior_key"))))
    con_stock_ambos = F.col("disponible") & F.col("disponible_anterior")
    tenia_promo = F.col("lista_anterior") > F.col("precio_anterior")
    fin_promocion = (con_stock_ambos & tenia_promo & F.col("descuento_pct").isNull()
                     & (F.col("precio_venta") > F.col("precio_anterior")))
    reglas = {
        # Si la subida es el fin de una promoción, se avisa solo como FIN_PROMOCION (un aviso por hecho).
        "CAMBIO_PRECIO": con_stock_ambos & (F.abs(F.col("variacion_pct")) >= umbral)
                         & ~F.coalesce(fin_promocion, F.lit(False)),
        "AGOTADO": F.col("disponible_anterior") & ~F.col("disponible"),
        "FIN_PROMOCION": fin_promocion,
        "PRODUCTO_NUEVO": F.col("fecha_anterior_key").isNull() & F.col("disponible")
                          & (F.col("fecha_key") > F.col("_primer_dia_tienda")),
        "DESCUENTO_SIN_RESPALDO": F.coalesce(F.col("descuento_sin_respaldo"), F.lit(False))
                                  & ~F.coalesce(F.col("sin_respaldo_anterior"), F.lit(False)),
    }
    partes = [df.filter(F.coalesce(cond, F.lit(False))).withColumn("tipo_evento", F.lit(tipo))
              for tipo, cond in reglas.items()]
    eventos = partes[0]
    for parte in partes[1:]:
        eventos = eventos.unionByName(parte)
    return eventos.select(
        "fecha_key", "tipo_evento", "producto_key", "tienda_key", "precio_anterior",
        F.col("precio_venta").alias("precio_actual"), "variacion_pct", "precio_lista",
        F.col("descuento_pct").alias("descuento_anunciado"), "descuento_respaldado", "precio_referencia_30d",
        "dias_observados_30d", "fecha_anterior_key", "dias_desde_anterior",
        # Si el precio de hoy o el anterior está marcado como atípico (src/medallon/atipicos.py), el aviso
        # lo dice: un cambio puede venir de una rareza del sitio (p. ej. Éxito publicando la lista como venta).
        (F.col("motivos_atipico").isNotNull() | F.col("atipico_anterior").isNotNull()).alias("revisar_atipico"),
        "url", "ruta_bronze")

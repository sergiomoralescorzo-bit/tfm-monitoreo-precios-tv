# -*- coding: utf-8 -*-
"""Detector de descuentos sin respaldo en el historial de precios (RF-09; memoria, subapartado 5.3.6.3).

Agrega columnas a `fact_precio_diario`, que comparte su nivel de detalle (producto × tienda × día):

    precio_referencia_30d   menor precio de venta con existencias de la misma oferta (producto y tienda)
                            en los `ventana_dias` días anteriores, sin contar el día evaluado
    dias_observados_30d     días de esa ventana con la oferta observada con existencias
    descuento_respaldado    1 − venta / referencia (negativo si la venta supera a la referencia)
    descuento_sin_respaldo  verdadero si descuento_pct (el anunciado, 1 − venta / lista) supera al
                            respaldado en más de `margen`; nulo si la oferta no es evaluable

Una oferta es evaluable si ese día tiene existencias, anuncia un descuento (lista > venta) y la ventana
tiene al menos `min_dias_observados` días con existencias. Si no, las dos últimas columnas quedan nulas:
la oferta no se marca. El resultado es un indicador sobre el historial observado (una captura diaria),
no una conclusión sobre la conducta de la cadena.
"""
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[2] / "config" / "servicios.yaml"
POR_DEFECTO = {
    "detector": {"ventana_dias": 30, "min_dias_observados": 20, "margen": 0.05},
    "alertas": {"umbral_cambio_precio": 0.10, "max_por_tipo_en_resumen": 5},
}


def parametros(ruta: Path = CONFIG) -> dict:
    """config/servicios.yaml sobre los valores por defecto (sirve aunque falte el archivo o PyYAML)."""
    salida = {k: dict(v) for k, v in POR_DEFECTO.items()}
    try:
        import yaml
        leidos = yaml.safe_load(Path(ruta).read_text(encoding="utf-8")) or {}
    except (FileNotFoundError, ImportError):
        leidos = {}
    for seccion, valores in leidos.items():
        salida.setdefault(seccion, {}).update(valores or {})
    return salida


def agregar_columnas(fact, p: dict | None = None):
    """fact_precio_diario (DataFrame de Spark) con las columnas del detector."""
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    d = (p or parametros())["detector"]
    ventana = int(d["ventana_dias"])
    dia = F.datediff(F.to_date(F.col("fecha_key").cast("string"), "yyyyMMdd"), F.lit("2000-01-01"))
    venta_con_stock = F.when(F.col("disponible") & (F.col("precio_venta") > 0), F.col("precio_venta"))
    w = (Window.partitionBy("producto_key", "tienda_key").orderBy("_dia")
         .rangeBetween(-ventana, -1))
    df = (fact.withColumn("_dia", dia).withColumn("_venta_stock", venta_con_stock)
          .withColumn("precio_referencia_30d", F.min("_venta_stock").over(w))
          .withColumn("dias_observados_30d", F.count("_venta_stock").over(w).cast("int")))
    evaluable = (F.col("disponible") & F.col("descuento_pct").isNotNull()
                 & F.col("precio_referencia_30d").isNotNull()
                 & (F.col("dias_observados_30d") >= int(d["min_dias_observados"])))
    respaldado = F.round(1 - F.col("precio_venta") / F.col("precio_referencia_30d"), 4)
    return (df.withColumn("descuento_respaldado", F.when(evaluable, respaldado))
            .withColumn("descuento_sin_respaldo",
                        F.when(evaluable, F.round(F.col("descuento_pct") - respaldado, 4) > float(d["margen"])))
            .drop("_dia", "_venta_stock"))

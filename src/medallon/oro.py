# -*- coding: utf-8 -*-
"""Oro: modelo estrella (Etapa 1, sección 9.4) y tablas de indicadores. Se reconstruye completo.

    dimensiones/dim_producto      producto_key (GTIN-14, o sitio:sku si no se emparejó) y atributos
    dimensiones/dim_tienda        tienda_key, sitio, cadena (Alkosto y Ktronix son la misma cadena)
    dimensiones/dim_calendario    fecha_key AAAAMMDD, del primer al último día con datos
    hechos/fact_precio_diario     producto × tienda × día, con la ÚLTIMA captura del día (RF-06)
    hechos/fact_ejecucion         corrida × sitio (duración, estados, conteos)
    hechos/fact_evento_comercial  tipo de evento × producto × tienda × día (alertas y resumen, src/medallon/eventos.py)

fact_precio_diario lleva además las columnas del detector de descuentos (src/medallon/detector.py).
    kpis/kpi_brecha_precio        producto × día con ≥2 cadenas: mínimo, máximo, brecha y cadena más barata
    kpis/kpi_calidad_captura      sitio × día (última corrida): completitud y emparejamiento (Etapa 1, sección 10)
"""
from delta.tables import DeltaTable
from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from src.medallon import detector, eventos
from src.medallon.rutas import SITIOS, Rutas
from src.medallon.plata import guardar

TIENDAS = [  # tienda_key fija para que no cambie entre reconstrucciones
    (1, "alkosto", "Alkosto", "Colombiana de Comercio (Alkosto/Ktronix)"),
    (2, "ktronix", "Ktronix", "Colombiana de Comercio (Alkosto/Ktronix)"),
    (3, "jumbo", "Jumbo", "Cencosud (Jumbo)"),
    (4, "olimpica", "Olímpica", "Olímpica"),
    (5, "exito", "Éxito", "Grupo Éxito"),
]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def fecha_key(col):
    return F.date_format(col, "yyyyMMdd").cast("int")


def dim_tienda(spark: SparkSession) -> DataFrame:
    return spark.createDataFrame(TIENDAS, "tienda_key int, sitio string, tienda string, cadena string")


def dim_calendario(spark: SparkSession, desde, hasta) -> DataFrame:
    df = spark.sql(f"SELECT explode(sequence(DATE'{desde}', DATE'{hasta}', INTERVAL 1 DAY)) AS fecha")
    dia_iso = (F.dayofweek("fecha") + 5) % 7 + 1          # 1 = lunes … 7 = domingo
    return df.select(
        fecha_key(F.col("fecha")).alias("fecha_key"), "fecha",
        F.year("fecha").alias("anio"), F.month("fecha").alias("mes"),
        F.element_at(F.array(*[F.lit(m) for m in MESES]), F.month("fecha")).alias("nombre_mes"),
        F.date_format("fecha", "yyyy-MM").alias("anio_mes"),
        F.weekofyear("fecha").alias("semana_iso"),
        F.date_trunc("week", "fecha").cast("date").alias("inicio_semana"),
        dia_iso.alias("dia_semana"),
        F.element_at(F.array(*[F.lit(d) for d in DIAS]), dia_iso).alias("nombre_dia"),
        (dia_iso >= 6).alias("es_fin_de_semana"))


def fact_precio_diario(ofertas: DataFrame, tiendas: DataFrame) -> DataFrame:
    # precio_medio_pago se queda en plata, pero no pasa a oro: ninguna tienda lo publica (decisión del 16-oct).
    ventana = Window.partitionBy("producto_key", "sitio", "fecha_col") \
                    .orderBy(F.col("fecha_captura_utc").desc(), F.col("precio_venta").asc())
    ultima = ofertas.filter("comparable").withColumn("_n", F.row_number().over(ventana)).filter("_n = 1")
    return (ultima.join(F.broadcast(tiendas.select("sitio", "tienda_key")), "sitio")
            .select(fecha_key(F.col("fecha_col")).alias("fecha_key"), "producto_key", "tienda_key",
                    "precio_lista", "precio_venta",
                    F.when(F.col("precio_lista") > F.col("precio_venta"),
                           F.round(1 - F.col("precio_venta") / F.col("precio_lista"), 4)).alias("descuento_pct"),
                    "disponible", "stock", "metodo_emparejamiento", "fecha_captura_utc", "id_ejecucion",
                    F.col("ruta_bronze_lago").alias("ruta_bronze"), "url", "motivos_atipico"))


def fact_ejecucion(ejecuciones: DataFrame, tiendas: DataFrame) -> DataFrame:
    return (ejecuciones.join(F.broadcast(tiendas.select("sitio", "tienda_key")), "sitio")
            .select(fecha_key(F.col("fecha_col")).alias("fecha_key"), "tienda_key", "id_ejecucion", "modo",
                    "inicio", "fin", "duracion_s", "descubiertos", "consultados", "ok", "sin_stock",
                    "no_encontrados", "errores", "bloqueados", "registros", "en_alcance", "estado", "mensaje"))


def kpi_brecha_precio(fact: DataFrame, tiendas: DataFrame) -> DataFrame:
    """Por producto y día, el precio de cada cadena (el menor de sus sitios) y la brecha entre cadenas.
    Solo productos con GTIN vendidos por al menos dos cadenas ese día y con stock. Los precios marcados
    como atípicos (motivos_atipico) no entran: un precio de lista publicado como venta inflaba la brecha
    media del día (19-nov: 6,8 % con dos Caixun de Olímpica y 3,1 % sin ellos)."""
    por_cadena = (fact.filter("disponible AND metodo_emparejamiento <> 'SIN_EMPAREJAR' AND motivos_atipico IS NULL")
                  .join(F.broadcast(tiendas.select("tienda_key", "cadena")), "tienda_key")
                  .groupBy("fecha_key", "producto_key", "cadena").agg(F.min("precio_venta").alias("precio")))
    ventana = Window.partitionBy("fecha_key", "producto_key").orderBy("precio", "cadena")
    return (por_cadena.withColumn("_n", F.row_number().over(ventana))
            .groupBy("fecha_key", "producto_key")
            .agg(F.count("*").alias("n_cadenas"), F.min("precio").alias("precio_min"),
                 F.max("precio").alias("precio_max"), F.round(F.avg("precio"), 0).alias("precio_promedio"),
                 F.first(F.when(F.col("_n") == 1, F.col("cadena")), ignorenulls=True).alias("cadena_mas_barata"))
            .filter("n_cadenas >= 2")
            .withColumn("brecha_abs", F.col("precio_max") - F.col("precio_min"))
            .withColumn("brecha_pct", F.round(F.col("brecha_abs") / F.col("precio_min"), 4)))


def kpi_calidad_captura(ofertas: DataFrame, catalogo: DataFrame, tiendas: DataFrame) -> DataFrame:
    """Por sitio y día, sobre la última corrida del día (como el informe de la Etapa 2).
    Emparejada = oferta en alcance con stock cuyo producto está en el maestro o en ≥2 cadenas ese día."""
    ultima = ofertas.groupBy("sitio", "fecha_col").agg(F.max("id_ejecucion").alias("id_ejecucion"))
    o = ofertas.drop("cadena").join(ultima, ["sitio", "fecha_col", "id_ejecucion"]) \
               .join(F.broadcast(tiendas.select("sitio", "tienda_key", "cadena")), "sitio")
    vendibles = o.filter("comparable AND disponible")
    n_cadenas = (vendibles.filter("gtin14_producto IS NOT NULL").groupBy("fecha_col", "producto_key")
                 .agg(F.countDistinct("cadena").alias("n_cadenas")))
    vendibles = (vendibles.join(n_cadenas, ["fecha_col", "producto_key"], "left")
                 .join(catalogo.select("producto_key", "en_maestro"), "producto_key", "left")
                 .withColumn("emparejada", F.coalesce("en_maestro", F.lit(False))
                             | (F.coalesce("n_cadenas", F.lit(1)) >= 2)))
    con_datos = o.filter(F.col("estado_extraccion").isin("OK", "SIN_STOCK"))
    base = (o.groupBy("fecha_col", "tienda_key").agg(
                F.first("id_ejecucion").alias("id_ejecucion"), F.count("*").alias("registros"),
                F.sum(F.col("estado_extraccion").isin("OK", "SIN_STOCK").cast("int")).alias("registros_con_datos"),
                F.sum(F.col("comparable").cast("int")).alias("tv_en_alcance")))
    completitud = con_datos.groupBy("fecha_col", "tienda_key").agg(
        F.round(F.avg(F.col("completo").cast("double")), 4).alias("completitud_pct"))
    empar = vendibles.groupBy("fecha_col", "tienda_key").agg(
        F.count("*").alias("ofertas_con_stock"),
        F.sum((F.col("metodo_emparejamiento") == "EAN").cast("int")).alias("por_ean"),
        F.sum((F.col("metodo_emparejamiento") == "REFERENCIA").cast("int")).alias("por_referencia"),
        F.sum((F.col("metodo_emparejamiento") == "SIN_EMPAREJAR").cast("int")).alias("sin_emparejar"),
        F.sum(F.col("emparejada").cast("int")).alias("emparejadas"))
    return (base.join(completitud, ["fecha_col", "tienda_key"], "left")
            .join(empar, ["fecha_col", "tienda_key"], "left")
            .withColumn("emparejamiento_pct", F.round(F.col("emparejadas") / F.col("ofertas_con_stock"), 4))
            .withColumn("fecha_key", fecha_key(F.col("fecha_col"))).drop("fecha_col"))


def construir(spark: SparkSession, rutas: Rutas, sitios: list[str] = SITIOS) -> dict[str, int]:
    ofertas = spark.read.format("delta").load(rutas.plata("precios/ofertas")).cache()
    catalogo = spark.read.format("delta").load(rutas.plata("catalogo/productos"))
    tiendas = dim_tienda(spark)
    rango = ofertas.agg(F.min("fecha_col"), F.max("fecha_col")).first()

    p = detector.parametros()
    fact = detector.agregar_columnas(fact_precio_diario(ofertas, tiendas), p).cache()
    resumen = {
        "dimensiones/dim_tienda": guardar(tiendas, rutas.oro("dimensiones/dim_tienda")),
        "dimensiones/dim_producto": guardar(catalogo, rutas.oro("dimensiones/dim_producto")),
        "dimensiones/dim_calendario": guardar(dim_calendario(spark, rango[0], rango[1]),
                                              rutas.oro("dimensiones/dim_calendario")),
        "hechos/fact_precio_diario": guardar(fact, rutas.oro("hechos/fact_precio_diario")),
        "hechos/fact_evento_comercial": guardar(eventos.fact_evento_comercial(fact, p),
                                                rutas.oro("hechos/fact_evento_comercial")),
        "kpis/kpi_brecha_precio": guardar(kpi_brecha_precio(fact, tiendas), rutas.oro("kpis/kpi_brecha_precio")),
        "kpis/kpi_calidad_captura": guardar(kpi_calidad_captura(ofertas, catalogo, tiendas),
                                            rutas.oro("kpis/kpi_calidad_captura")),
    }
    if DeltaTable.isDeltaTable(spark, rutas.plata("control/ejecuciones")):
        ejecuciones = spark.read.format("delta").load(rutas.plata("control/ejecuciones"))
        resumen["hechos/fact_ejecucion"] = guardar(fact_ejecucion(ejecuciones, tiendas),
                                                   rutas.oro("hechos/fact_ejecucion"))
    fact.unpersist()
    ofertas.unpersist()
    return resumen

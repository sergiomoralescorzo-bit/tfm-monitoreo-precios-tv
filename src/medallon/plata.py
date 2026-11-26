# -*- coding: utf-8 -*-
"""Plata: ofertas tipadas, deduplicadas, clasificadas y emparejadas (RF-04, RF-05; Etapa 1, sección 6).

Se reconstruye completo en cada corrida semanal desde bronce/conformidad: el volumen es pequeño
(miles de filas por día) y así el resultado no depende de corridas anteriores.

Regla de emparejamiento: la misma de `src.catalogo.emparejamiento` y del informe de la Etapa 2.
El índice de referencias se arma con el maestro y con las ofertas en alcance que traen GTIN.
El cálculo corre en el driver sobre los productos distintos (unos pocos miles), no por fila.
"""
from functools import reduce

from delta.tables import DeltaTable
from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

from src.catalogo import atributos_tv
from src.catalogo.emparejamiento import IndiceReferencias, clave_de, emparejar
from src.medallon import atipicos
from src.medallon.conformidad import leer_csv
from src.medallon.rutas import SITIOS, Rutas

ESTADOS_CON_DATOS = ["OK", "SIN_STOCK"]
ENTEROS = ["precio_lista", "precio_venta", "precio_medio_pago", "stock"]
BOOLEANOS = ["es_vendedor_propio", "disponible", "en_alcance"]
SEP = "\u0001"


def leer_conformidad(spark: SparkSession, rutas: Rutas, tabla: str, sitios: list[str]) -> DataFrame | None:
    partes = [spark.read.format("delta").load(rutas.conformidad(s, tabla)) for s in sitios
              if DeltaTable.isDeltaTable(spark, rutas.conformidad(s, tabla))]
    if not partes:
        return None
    return reduce(lambda a, b: a.unionByName(b, allowMissingColumns=True), partes)


def _clave_join(*columnas: str):
    return F.concat_ws(SEP, *[F.coalesce(F.col(c).cast("string"), F.lit("")) for c in columnas])


def _clave_py(*valores) -> str:
    return SEP.join("" if v is None else str(v) for v in valores)


def tipar_ofertas(df: DataFrame) -> DataFrame:
    df = (df.withColumn("fecha_captura_utc", F.col("fecha_captura_utc").cast("timestamp"))
            .withColumn("fecha_col", F.to_date(F.substring("fecha_captura_col", 1, 10)))
            .withColumn("hora_captura_col", F.substring("fecha_captura_col", 12, 8))
            .withColumn("pulgadas", F.col("pulgadas").cast("int")))
    for c in ENTEROS:
        df = df.withColumn(c, F.col(c).cast("double").cast("long"))
    for c in BOOLEANOS:
        df = df.withColumn(c, F.lower(F.col(c)) == "true")
    # Reprocesos (src/nube/reproceso.py): de cada tabla de productos se usa solo la última versión
    # (`productos_..._rN.csv`); las anteriores quedan en conformidad para la trazabilidad.
    archivo = F.regexp_replace("_archivo_origen", r"_r\d+\.csv$", ".csv")
    version = F.coalesce(F.regexp_extract("_archivo_origen", r"_r(\d+)\.csv$", 1).cast("int"), F.lit(0))
    df = (df.withColumn("_version", version)
            .withColumn("_ultima", F.max("_version").over(Window.partitionBy(archivo)))
            .filter("_version = _ultima").drop("_version", "_ultima"))
    # Deduplicación: una fila por corrida, sitio, ficha y vendedor (la de la carga más reciente).
    ventana = Window.partitionBy("id_ejecucion", "sitio", "url", "sku_tienda", "vendedor") \
                    .orderBy(F.col("_fecha_carga").desc())
    df = df.withColumn("_n", F.row_number().over(ventana)).filter("_n = 1").drop("_n")
    return (df
        .withColumn("ruta_bronze_lago",
                    F.regexp_replace("ruta_bronze", r"^bronze/([^/]+)/fecha=(\d{4})-(\d{2})-(\d{2})/",
                                     "bronce/aterrizaje/$1/capturas/$2/$3/$4/"))
        .withColumn("completo", F.coalesce(F.col("ean_publicado"), F.col("sku_tienda")).isNotNull()
                    & (F.col("precio_venta") > 0) & F.col("titulo").isNotNull())
        .withColumn("comparable", F.col("estado_extraccion").isin(ESTADOS_CON_DATOS)
                    & F.coalesce(F.col("en_alcance"), F.lit(False)) & (F.col("precio_venta") > 0)))


def indice_referencias(maestro: list, ofertas: list) -> IndiceReferencias:
    indice = IndiceReferencias()
    for m in maestro:
        indice.agregar(m["clave_referencia"], m["gtin14"])
    for o in ofertas:
        if o["gtin14"]:
            indice.agregar(clave_de(o["marca"], o["pulgadas"], o["referencia"]), o["gtin14"])
    return indice


def emparejar_ofertas(spark: SparkSession, ofertas: DataFrame, maestro: DataFrame) -> DataFrame:
    """Agrega `gtin14_producto`, `metodo_emparejamiento` y `producto_key` a las ofertas comparables."""
    cols = ["ean_publicado", "marca", "pulgadas", "referencia"]
    comparables = ofertas.filter("comparable")
    maestro_filas = maestro.select("clave_referencia", "gtin14").collect()
    con_gtin = comparables.select("gtin14", "marca", "pulgadas", "referencia").distinct().collect()
    indice = indice_referencias(maestro_filas, con_gtin)

    filas = []
    for r in comparables.select(*cols).distinct().collect():
        producto, metodo = emparejar(r["ean_publicado"], r["marca"], r["pulgadas"], r["referencia"], indice)
        filas.append((_clave_py(*[r[c] for c in cols]), producto, metodo))
    esquema = T.StructType([T.StructField("_clave", T.StringType()),
                            T.StructField("gtin14_producto", T.StringType()),
                            T.StructField("metodo_emparejamiento", T.StringType())])
    resultado = spark.createDataFrame(filas, esquema)

    return (ofertas.withColumn("_clave", F.when(F.col("comparable"), _clave_join(*cols)))
                   .join(F.broadcast(resultado), "_clave", "left").drop("_clave"))


def aplicar_revision(ofertas: DataFrame, decisiones: DataFrame | None) -> DataFrame:
    """Aplica las decisiones del equipo (bronce/aterrizaje/revision/*.csv) por sitio y sku_tienda:
        CONFIRMAR  se mantiene el emparejamiento automático
        CORREGIR   se asigna el GTIN de la columna `gtin14` (método MANUAL)
        RECHAZAR   la oferta queda SIN_EMPAREJAR
    Si hay varias decisiones para la misma oferta, vale la de `fecha_revision` más reciente.
    Después calcula `producto_key`: el GTIN-14 o, si no hay, `sitio:sku_tienda`."""
    if decisiones is not None:
        ventana = Window.partitionBy("sitio", "sku_tienda").orderBy(F.col("fecha_revision").desc_nulls_last())
        d = (decisiones.withColumn("_n", F.row_number().over(ventana)).filter("_n = 1")
             .select("sitio", "sku_tienda", F.upper(F.trim("decision")).alias("estado_revision"),
                     F.lpad(F.regexp_replace("gtin14", r"\D", ""), 14, "0").alias("_gtin_revision")))
        ofertas = ofertas.join(F.broadcast(d), ["sitio", "sku_tienda"], "left")
        decision = F.when(F.col("comparable"), F.col("estado_revision"))
        ofertas = (ofertas
            .withColumn("gtin14_producto", F.when(decision == "CORREGIR", F.col("_gtin_revision"))
                        .when(decision == "RECHAZAR", F.lit(None)).otherwise(F.col("gtin14_producto")))
            .withColumn("metodo_emparejamiento", F.when(decision == "CORREGIR", "MANUAL")
                        .when(decision == "RECHAZAR", "SIN_EMPAREJAR").otherwise(F.col("metodo_emparejamiento")))
            .drop("_gtin_revision"))
    else:
        ofertas = ofertas.withColumn("estado_revision", F.lit(None).cast("string"))
    return ofertas.withColumn("producto_key", F.when(F.col("comparable"), F.coalesce(
        "gtin14_producto", F.concat_ws(":", "sitio", F.coalesce("sku_tienda", "url")))))


NO_INFORMADA = "No informada"


def rango_pulgadas(col):
    return (F.when(col.isNull(), None).when(col <= 32, "Hasta 32").when(col <= 43, "33 a 43")
             .when(col <= 55, "44 a 55").when(col <= 65, "56 a 65").otherwise("Más de 65"))


def catalogo_productos(spark: SparkSession, ofertas: DataFrame, maestro: DataFrame) -> DataFrame:
    """Un registro por `producto_key`. Atributos del maestro si el GTIN está en él; si no, de la
    oferta más reciente (tecnología y resolución se deducen del título)."""
    ventana = Window.partitionBy("producto_key").orderBy(F.col("fecha_captura_utc").desc())
    ultima = (ofertas.filter("comparable")
              .withColumn("_n", F.row_number().over(ventana)).filter("_n = 1")
              .select("producto_key", "gtin14_producto", "metodo_emparejamiento", "titulo", "marca",
                      "pulgadas", "referencia"))
    esquema = T.StructType([T.StructField("producto_key", T.StringType()),
                            T.StructField("marca_t", T.StringType()),
                            T.StructField("tecnologia_t", T.StringType()),
                            T.StructField("resolucion_t", T.StringType())])
    # La marca se vuelve a deducir del título: las capturas viejas no conocían marcas agregadas después.
    deducidos = spark.createDataFrame(
        [(r["producto_key"], atributos_tv.marca(r["titulo"] or "", r["marca"]),
          atributos_tv.tecnologia(r["titulo"] or ""), atributos_tv.resolucion(r["titulo"] or ""))
         for r in ultima.select("producto_key", "titulo", "marca").collect()], esquema)
    m = maestro.select(F.col("gtin14").alias("gtin14_producto"), F.col("descripcion").alias("descripcion_m"),
                       F.col("marca").alias("marca_m"), F.col("pulgadas").cast("int").alias("pulgadas_m"),
                       F.col("referencia").alias("referencia_m"), F.col("tecnologia").alias("tecnologia_m"),
                       F.col("resolucion").alias("resolucion_m")).dropDuplicates(["gtin14_producto"])
    df = ultima.join(deducidos, "producto_key", "left").join(m, "gtin14_producto", "left")
    en_maestro = F.col("marca_m").isNotNull()
    df = df.select(
        "producto_key",
        F.col("gtin14_producto").alias("gtin14"),
        F.coalesce("descripcion_m", "titulo").alias("descripcion"),
        # 21-nov-2026: sin dato se muestra «No informada» y no un valor en blanco en los segmentadores.
        F.coalesce("marca_m", "marca", "marca_t", F.lit(NO_INFORMADA)).alias("marca"),
        F.coalesce("pulgadas_m", "pulgadas").alias("pulgadas"),
        F.coalesce("referencia_m", "referencia").alias("referencia"),
        F.coalesce("tecnologia_m", "tecnologia_t", F.lit(NO_INFORMADA)).alias("tecnologia"),
        F.coalesce("resolucion_m", "resolucion_t").alias("resolucion"),
        en_maestro.alias("en_maestro"),
        F.when(en_maestro, "maestro").otherwise("tienda").alias("origen_atributos"),
        F.col("gtin14_producto").isNotNull().alias("tiene_gtin"),
    )
    return df.withColumn("rango_pulgadas", rango_pulgadas(F.col("pulgadas")))


def tipar_ejecuciones(df: DataFrame) -> DataFrame:
    for c in ("inicio", "fin"):
        df = df.withColumn(c, F.col(c).cast("timestamp"))
    for c in ("descubiertos", "consultados", "ok", "sin_stock", "no_encontrados", "errores", "bloqueados",
              "registros", "en_alcance"):
        df = df.withColumn(c, F.col(c).cast("int"))
    df = df.withColumn("duracion_s", F.col("duracion_s").cast("double")) \
           .withColumn("fecha_col", F.to_date("fecha"))
    ventana = Window.partitionBy("id_ejecucion", "sitio").orderBy(F.col("_fecha_carga").desc())
    return df.withColumn("_n", F.row_number().over(ventana)).filter("_n = 1").drop("_n", "fecha")


def guardar(df: DataFrame, ruta: str, particion: str | None = None) -> int:
    w = df.write.format("delta").mode("overwrite").option("overwriteSchema", "true")
    if particion:
        w = w.partitionBy(particion)
    w.save(ruta)
    return df.sparkSession.read.format("delta").load(ruta).count()


def construir(spark: SparkSession, rutas: Rutas, sitios: list[str] = SITIOS) -> dict[str, int]:
    # Solo los televisores del maestro en alcance (vigentes, nuevos, sin combos), como en la Etapa 2.
    maestro = spark.read.format("delta").load(rutas.conformidad_maestro).filter(F.lower("en_alcance") == "true")
    crudas = leer_conformidad(spark, rutas, "productos", sitios)
    if crudas is None:
        raise RuntimeError("No hay capturas en bronce/conformidad")
    ofertas = emparejar_ofertas(spark, tipar_ofertas(crudas), maestro)
    ofertas = aplicar_revision(ofertas, leer_csv(spark, rutas.revision_csv))
    base = ofertas.drop("fecha").cache()   # `fecha` de la carpeta; se usa fecha_col (hora de la captura)
    # Control de calidad (Etapa 6): motivos de precio atípico del producto en ese sitio y día.
    ofertas = base.join(F.broadcast(atipicos.motivos_por_dia(spark, base)),
                        ["fecha_col", "producto_key", "sitio"], "left").cache()
    resumen = {"precios/ofertas": guardar(ofertas, rutas.plata("precios/ofertas"), "fecha_col")}

    # Lista de trabajo para el equipo: copia las columnas sitio y sku_tienda al CSV de decisiones.
    ventana = Window.partitionBy("sitio", "sku_tienda").orderBy(F.col("fecha_captura_utc").desc())
    revision = (ofertas.filter(F.col("comparable")
                               & F.col("metodo_emparejamiento").isin("REFERENCIA", "SIN_EMPAREJAR", "MANUAL"))
                .withColumn("_n", F.row_number().over(ventana)).filter("_n = 1")
                .select("producto_key", "metodo_emparejamiento", "gtin14_producto", "sitio", "sku_tienda",
                        "ean_publicado", "titulo", "marca", "pulgadas", "referencia", "url",
                        F.col("fecha_col").alias("ultima_fecha"),
                        F.coalesce("estado_revision", F.lit("PENDIENTE")).alias("estado_revision")))
    resumen["precios/revision_emparejamiento"] = guardar(revision, rutas.plata("precios/revision_emparejamiento"))
    resumen["catalogo/productos"] = guardar(catalogo_productos(spark, ofertas, maestro),
                                            rutas.plata("catalogo/productos"))
    ejecuciones = leer_conformidad(spark, rutas, "ejecuciones", sitios)
    if ejecuciones is not None:
        resumen["control/ejecuciones"] = guardar(tipar_ejecuciones(ejecuciones), rutas.plata("control/ejecuciones"))
    ofertas.unpersist()
    base.unpersist()
    return resumen

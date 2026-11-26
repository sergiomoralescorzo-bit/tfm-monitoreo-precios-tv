# -*- coding: utf-8 -*-
"""Precios atípicos (control de calidad, Etapa 6). Los usan plata (`motivos_atipico`) y la validación.

Se evalúan sobre el precio diario (última captura del día por producto y sitio, igual que
fact_precio_diario) y la marca se copia a todas las ofertas de ese producto, sitio y día:

    SIN_PRECIO / BAJO_RANGO / SOBRE_RANGO   precio de venta ≤ 0, < $200.000 o > $80.000.000
    VENTA_MAYOR_QUE_LISTA                   precio de venta mayor que el de lista
    DESCUENTO_EXCESIVO                      más del 70 % de descuento sobre el precio de lista
    LEJOS_DE_OTRAS_CADENAS                  con stock, fuera de [mediana/2, mediana×2] de al menos otras
                                            2 cadenas con stock el mismo día (con una sola no se sabe
                                            cuál de las dos se aparta; eso ya lo muestra la brecha)
    CAMBIO_BRUSCO                           con stock, más del 50 % de variación frente al día anterior
                                            con stock en el mismo sitio (sin stock, Éxito publica el
                                            precio de lista como precio: no es una oferta real)
"""
from collections import defaultdict

PRECIO_MINIMO = 200_000
PRECIO_MAXIMO = 80_000_000
DESCUENTO_MAXIMO = 0.70
FACTOR_CADENAS = 2.0
MIN_OTRAS_CADENAS = 2
CAMBIO_DIARIO = 0.50


def mediana(valores: list[float]) -> float:
    v = sorted(valores)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def motivos_atipico(precio_venta, precio_lista=None, otras_cadenas: list | None = None,
                    precio_anterior=None) -> list[str]:
    """Motivos por los que un precio es atípico (lista vacía si pasa todos los controles)."""
    if precio_venta is None or precio_venta <= 0:
        return ["SIN_PRECIO"]
    motivos = []
    if precio_venta < PRECIO_MINIMO:
        motivos.append("BAJO_RANGO")
    if precio_venta > PRECIO_MAXIMO:
        motivos.append("SOBRE_RANGO")
    if precio_lista:
        if precio_venta > precio_lista:
            motivos.append("VENTA_MAYOR_QUE_LISTA")
        elif 1 - precio_venta / precio_lista > DESCUENTO_MAXIMO:
            motivos.append("DESCUENTO_EXCESIVO")
    otras = [p for p in (otras_cadenas or []) if p]
    if otras:
        m = mediana(otras)
        if precio_venta < m / FACTOR_CADENAS or precio_venta > m * FACTOR_CADENAS:
            motivos.append("LEJOS_DE_OTRAS_CADENAS")
    if precio_anterior and abs(precio_venta / precio_anterior - 1) > CAMBIO_DIARIO:
        motivos.append("CAMBIO_BRUSCO")
    return motivos


def marcar(filas: list[dict]) -> list[dict]:
    """`filas`: precio diario con fecha, producto_key, sitio, cadena, precio_venta, precio_lista,
    disponible y metodo_emparejamiento. Devuelve las mismas filas con `motivos_atipico` (texto separado
    por comas, o None), `mediana_otras_cadenas` y `precio_anterior`."""
    por_cadena = defaultdict(dict)        # (fecha, producto) -> cadena -> menor precio con stock
    for f in filas:
        if f["disponible"] and f["metodo_emparejamiento"] != "SIN_EMPAREJAR" and f["precio_venta"]:
            c = por_cadena[(f["fecha"], f["producto_key"])]
            c[f["cadena"]] = min(c.get(f["cadena"], f["precio_venta"]), f["precio_venta"])
    anterior = {}
    salida = []
    for f in sorted(filas, key=lambda f: (str(f["producto_key"]), f["sitio"], str(f["fecha"]))):
        otras = [p for c, p in por_cadena.get((f["fecha"], f["producto_key"]), {}).items() if c != f["cadena"]]
        if not f["disponible"] or len(otras) < MIN_OTRAS_CADENAS:
            otras = []
        previo = anterior.get((f["producto_key"], f["sitio"])) if f["disponible"] else None
        motivos = motivos_atipico(f["precio_venta"], f["precio_lista"], otras, previo)
        if f["disponible"] and f["precio_venta"]:
            anterior[(f["producto_key"], f["sitio"])] = f["precio_venta"]
        salida.append({**f, "motivos_atipico": ",".join(motivos) or None,
                       "mediana_otras_cadenas": mediana(otras) if otras else None, "precio_anterior": previo})
    return salida


def motivos_por_dia(spark, ofertas):
    """DataFrame (fecha_col, producto_key, sitio, motivos_atipico) con las combinaciones atípicas.
    `ofertas`: plata con producto_key ya asignado. El cálculo corre en el driver: son unos cientos de
    precios diarios por día."""
    from pyspark.sql import Window
    from pyspark.sql import functions as F
    from pyspark.sql import types as T
    from src.medallon.oro import TIENDAS
    cadena = {sitio: c for _, sitio, _, c in TIENDAS}
    ventana = Window.partitionBy("producto_key", "sitio", "fecha_col") \
                    .orderBy(F.col("fecha_captura_utc").desc(), F.col("precio_venta").asc())
    diario = (ofertas.filter("comparable").withColumn("_n", F.row_number().over(ventana)).filter("_n = 1")
              .select(F.col("fecha_col").alias("fecha"), "producto_key", "sitio", "precio_venta", "precio_lista",
                      "disponible", "metodo_emparejamiento"))
    filas = [{**r.asDict(), "cadena": cadena.get(r["sitio"], r["sitio"])} for r in diario.collect()]
    marcadas = [(f["fecha"], f["producto_key"], f["sitio"], f["motivos_atipico"])
                for f in marcar(filas) if f["motivos_atipico"]]
    esquema = T.StructType([T.StructField("fecha_col", T.DateType()), T.StructField("producto_key", T.StringType()),
                            T.StructField("sitio", T.StringType()), T.StructField("motivos_atipico", T.StringType())])
    return spark.createDataFrame(marcadas, esquema)

# -*- coding: utf-8 -*-
"""Pruebas del medallón (Etapa 3) con Spark 3.4 + Delta 2.4, en Docker (ver Dockerfile de esta carpeta).

1. Datos sintéticos: deduplicación, última captura del día, emparejamiento y brecha entre cadenas.
2. Datos reales de data/ (corridas del 13-oct): el emparejamiento debe coincidir con el informe de la
   Etapa 2 (87,2 % de 735 ofertas) y la conformidad debe ser incremental.
"""
import csv
import shutil
from pathlib import Path

import pytest
from delta import configure_spark_with_delta_pip
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from src.medallon import conformidad, semanal
from src.medallon.rutas import SITIOS, Rutas
from src.nube import lago

PROYECTO = Path(__file__).resolve().parents[1]
DATOS = PROYECTO / "data"
MAESTRO = DATOS / "maestro" / "maestro_televisores.csv"


@pytest.fixture(scope="session")
def spark():
    constructor = (SparkSession.builder.master("local[2]").appName("pruebas-medallon")
                   .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
                   .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
                   .config("spark.sql.shuffle.partitions", "4")
                   .config("spark.ui.enabled", "false"))
    s = configure_spark_with_delta_pip(constructor).getOrCreate()
    s.sparkContext.setLogLevel("ERROR")
    yield s
    s.stop()


def leer(spark, ruta):
    return spark.read.format("delta").load(ruta)


# --------------------------------------------------------------------------- datos sintéticos

CAMPOS = ["id_ejecucion", "fecha_captura_utc", "fecha_captura_col", "cadena", "sitio", "sku_tienda",
          "ean_publicado", "gtin14", "titulo", "marca", "pulgadas", "referencia", "url", "vendedor",
          "es_vendedor_propio", "precio_lista", "precio_venta", "precio_medio_pago", "disponible", "stock",
          "estado_extraccion", "metodo", "ruta_bronze", "mensaje", "en_alcance", "motivo_exclusion"]
EAN = "8806095465937"          # GTIN válido (Samsung)


def oferta(id_, hora, sitio, sku, precio, ean=EAN, titulo="Televisor Samsung 55 pulgadas QLED 4K UN55U8000F",
           referencia="UN55U8000F", en_alcance="True"):
    fecha = f"{id_[:4]}-{id_[4:6]}-{id_[6:8]}"
    return {"id_ejecucion": id_, "fecha_captura_utc": f"{fecha}T{hora}:00.000000Z",
            "fecha_captura_col": f"{fecha}T{hora}:00.000000-05:00", "cadena": sitio, "sitio": sitio,
            "sku_tienda": sku, "ean_publicado": ean, "gtin14": ("0" + ean) if ean else "", "titulo": titulo,
            "marca": "SAMSUNG", "pulgadas": "55", "referencia": referencia, "url": f"https://{sitio}/{sku}",
            "vendedor": sitio, "es_vendedor_propio": "True", "precio_lista": "3000000.0",
            "precio_venta": precio, "precio_medio_pago": "", "disponible": "True", "stock": "",
            "estado_extraccion": "OK", "metodo": "http_json",
            "ruta_bronze": f"bronze/{sitio}/fecha={fecha}/{id_}/00001_{sku}.json.gz", "mensaje": "",
            "en_alcance": en_alcance, "motivo_exclusion": ""}


def escribir(ruta: Path, filas: list[dict], bom: bool = True):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", newline="", encoding="utf-8-sig" if bom else "utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]), delimiter=";")
        w.writeheader()
        w.writerows(filas)


def capturas(raiz: Path, sitio: str, id_: str, filas: list[dict]):
    fecha = f"{id_[:4]}-{id_[4:6]}-{id_[6:8]}"
    escribir(raiz / lago.ruta_en_lago(f"capturas/{sitio}/fecha={fecha}/{id_}.csv"), filas)


@pytest.fixture
def lago_sintetico(tmp_path):
    t1, t2 = "20261014T060000_aaaaaa", "20261014T180000_bbbbbb"
    capturas(tmp_path, "jumbo", t1, [
        oferta(t1, "06:05", "jumbo", "J1", "2500000"),
        oferta(t1, "06:06", "jumbo", "J2", "999000", ean="", titulo="Soporte de pared para TV; 55\"",
               referencia=None, en_alcance="False"),
    ])
    capturas(tmp_path, "jumbo", t2, [oferta(t2, "18:05", "jumbo", "J1", "2400000")])   # última del día
    capturas(tmp_path, "exito", t1, [oferta(t1, "06:10", "exito", "E1", "2000000")])
    capturas(tmp_path, "alkosto", t1, [
        oferta(t1, "06:07", "alkosto", "A1", "2200000", ean="", referencia="UN55U8000FKXZL"),   # por referencia
    ])
    fila = {"id_ejecucion": t1, "sitio": "jumbo", "modo": "seguimiento", "inicio": "2026-10-14T11:00:00Z",
            "fin": "2026-10-14T11:03:00Z", "duracion_s": "180.0", "descubiertos": "2", "consultados": "2",
            "ok": "2", "sin_stock": "0", "no_encontrados": "0", "errores": "0", "bloqueados": "0",
            "registros": "2", "en_alcance": "1", "estado": "EXITOSA", "mensaje": "x"}
    destino = lago.DestinoLocal(tmp_path)
    destino.subir(lago.ejecucion_a_json(fila), lago.ruta_ejecucion("jumbo", t1))
    maestro = tmp_path / "maestro_televisores.csv"
    maestro.write_text(
        "\ufeffean_original;gtin14;descripcion;marca;pulgadas;referencia;tecnologia;resolucion;clave_referencia;en_alcance\n"
        f"{EAN};0{EAN};TV SAMSUNG 55 QLED;SAMSUNG;55;UN55U8000F;QLED;4K;SAMSUNG|55|U8000F;True\n", encoding="utf-8")
    lago.subir_maestro(destino, maestro)
    return tmp_path


def test_medallon_sintetico(spark, lago_sintetico):
    base = lago_sintetico.as_posix()
    r = Rutas(base)
    resumen = semanal.ejecutar(spark, base)
    assert resumen["conformidad"]["jumbo/productos"] == 3
    assert resumen["conformidad"]["jumbo/ejecuciones"] == 1

    # Conformidad: columnas de texto tal cual, sin BOM en el nombre, con metadatos y la fecha de la carpeta.
    conf = leer(spark, r.conformidad("jumbo", "productos"))
    assert "id_ejecucion" in conf.columns and dict(conf.dtypes)["precio_venta"] == "string"
    assert conf.filter("sku_tienda = 'J2'").first()["titulo"] == 'Soporte de pared para TV; 55"'
    assert {f["fecha"] for f in conf.select("fecha").collect()} == {"2026-10-14"}
    assert leer(spark, r.conformidad("jumbo", "ejecuciones")).first()["fecha"] == "2026-10-14"

    ofertas = leer(spark, r.plata("precios/ofertas"))
    metodos = {f["sitio"]: f["metodo_emparejamiento"] for f in ofertas.filter("comparable").collect()}
    assert metodos == {"jumbo": "EAN", "exito": "EAN", "alkosto": "REFERENCIA"}
    assert ofertas.filter("sku_tienda = 'J2'").first()["comparable"] is False
    assert ofertas.filter("sitio = 'exito'").first()["ruta_bronze_lago"] == \
        "bronce/aterrizaje/exito/capturas/2026/10/14/20261014T060000_aaaaaa/00001_E1.json.gz"
    revision = leer(spark, r.plata("precios/revision_emparejamiento")).first()
    assert (revision["sitio"], revision["estado_revision"]) == ("alkosto", "PENDIENTE")

    fact = leer(spark, r.oro("hechos/fact_precio_diario"))
    assert fact.count() == 3                                       # producto × tienda × día
    assert "precio_medio_pago" not in fact.columns                 # vacío en todas las tiendas: no pasa a oro
    jumbo = fact.filter("tienda_key = 3").first()
    assert jumbo["precio_venta"] == 2400000 and jumbo["fecha_key"] == 20261014
    assert fact.select("producto_key").distinct().count() == 1      # los tres son el mismo GTIN
    # Precios atípicos (Etapa 6): columna en plata y en oro; estos precios son normales.
    assert "motivos_atipico" in ofertas.columns
    assert fact.filter("motivos_atipico IS NOT NULL").count() == 0

    brecha = leer(spark, r.oro("kpis/kpi_brecha_precio")).first()
    assert (brecha["n_cadenas"], brecha["precio_min"], brecha["precio_max"]) == (3, 2000000, 2400000)
    assert brecha["cadena_mas_barata"] == "Grupo Éxito" and brecha["brecha_pct"] == 0.2

    producto = leer(spark, r.oro("dimensiones/dim_producto")).first()
    assert (producto["origen_atributos"], producto["tecnologia"], producto["rango_pulgadas"]) == ("maestro", "QLED", "44 a 55")
    cal = leer(spark, r.oro("dimensiones/dim_calendario")).first()
    assert (cal["nombre_dia"], cal["dia_semana"], cal["nombre_mes"]) == ("miércoles", 3, "octubre")
    assert leer(spark, r.oro("hechos/fact_ejecucion")).first()["duracion_s"] == 180.0

    # Revisión manual: el equipo rechaza el emparejamiento por referencia de Alkosto.
    escribir(lago_sintetico / "bronce/aterrizaje/revision/decisiones.csv", [
        {"sitio": "alkosto", "sku_tienda": "A1", "gtin14": "", "decision": "rechazar",
         "revisado_por": "equipo", "fecha_revision": "2026-10-15", "comentario": "otro modelo"}])
    # Incremental: la segunda corrida no vuelve a cargar los mismos archivos.
    assert semanal.ejecutar(spark, base)["conformidad"]["jumbo/productos"] == 0
    assert leer(spark, r.conformidad("jumbo", "productos")).count() == 3
    alkosto = leer(spark, r.plata("precios/ofertas")).filter("sitio = 'alkosto'").first()
    assert (alkosto["metodo_emparejamiento"], alkosto["estado_revision"], alkosto["producto_key"]) == \
        ("SIN_EMPAREJAR", "RECHAZAR", "alkosto:A1")
    assert leer(spark, r.oro("kpis/kpi_brecha_precio")).first()["n_cadenas"] == 2


# --------------------------------------------------------------------------- datos reales

@pytest.fixture(scope="module")
def lago_real(tmp_path_factory):
    capturas = sorted((DATOS / "capturas").glob("*/fecha=*/*.csv"))
    if not capturas or not MAESTRO.exists():
        pytest.skip("sin datos locales en data/")
    raiz = tmp_path_factory.mktemp("lago")
    destino = lago.DestinoLocal(raiz)
    for p in capturas:
        destino.subir(p.read_bytes(), lago.ruta_en_lago(p.relative_to(DATOS).as_posix()))
    for id_ in {p.stem for p in capturas}:
        for sitio, fila in lago.ejecuciones_por_sitio(DATOS, id_).items():
            destino.subir(lago.ejecucion_a_json(fila), lago.ruta_ejecucion(sitio, id_))
    lago.subir_maestro(destino, MAESTRO)
    return raiz


def test_medallon_datos_reales(spark, lago_real):
    base = lago_real.as_posix()
    r = Rutas(base)
    semanal.ejecutar(spark, base)

    calidad = leer(spark, r.oro("kpis/kpi_calidad_captura")).filter("fecha_key = 20261013")
    total = calidad.agg(F.sum("ofertas_con_stock").alias("n"), F.sum("emparejadas").alias("e")).first()
    print(f"\nEmparejamiento 13-oct: {total['e']}/{total['n']} = {total['e'] / total['n']:.1%}")
    assert total["n"] == 735                                    # informe de la Etapa 2
    assert round(total["e"] / total["n"], 3) == 0.872
    assert calidad.filter("completitud_pct < 0.9").count() == 0

    fact = leer(spark, r.oro("hechos/fact_precio_diario"))
    assert fact.count() == fact.select("fecha_key", "producto_key", "tienda_key").distinct().count()
    assert fact.filter("precio_venta IS NULL OR precio_venta <= 0").count() == 0
    atipicos = {f["motivos_atipico"]: f["n"] for f in fact.groupBy("motivos_atipico").agg(F.count("*").alias("n")).collect()}
    print(f"Precios atípicos (datos locales): {atipicos}")
    assert sum(n for m, n in atipicos.items() if m) < fact.count() * 0.05   # control, no ruido
    productos = leer(spark, r.oro("dimensiones/dim_producto"))
    assert fact.join(productos, "producto_key", "left_anti").count() == 0   # integridad referencial
    assert leer(spark, r.oro("kpis/kpi_brecha_precio")).filter("brecha_pct < 0").count() == 0
    assert leer(spark, r.oro("hechos/fact_ejecucion")).count() > 0


# --------------------------------------------------------------------------- job de medallón (opción B)

def test_job_medallon_ciclo_con_lago(spark, lago_sintetico, tmp_path_factory):
    """El job baja, procesa y sube; la segunda corrida usa otra carpeta de trabajo y sigue siendo incremental."""
    from src.nube import tarea_medallon

    destino = lago.DestinoLocal(lago_sintetico)
    nube = Rutas(lago_sintetico.as_posix())
    primera = tarea_medallon.ejecutar(destino, tmp_path_factory.mktemp("trabajo1"), SITIOS, spark)
    assert primera["medallon"]["conformidad"]["jumbo/productos"] == 3 and primera["subida"]["archivos"] > 0
    conf = leer(spark, nube.conformidad("jumbo", "productos"))
    assert {f["_archivo_origen"] for f in conf.select("_archivo_origen").distinct().collect()} == {
        "bronce/aterrizaje/jumbo/crudo/2026/10/14/productos_jumbo_20261014_060000.csv",
        "bronce/aterrizaje/jumbo/crudo/2026/10/14/productos_jumbo_20261014_180000.csv"}
    assert leer(spark, nube.oro("hechos/fact_precio_diario")).count() == 3
    assert not list(lago_sintetico.rglob(".*.crc"))

    segunda = tarea_medallon.ejecutar(destino, tmp_path_factory.mktemp("trabajo2"), SITIOS, spark)
    assert segunda["medallon"]["conformidad"]["jumbo/productos"] == 0
    assert leer(spark, nube.conformidad("jumbo", "productos")).count() == 3
    assert leer(spark, nube.oro("hechos/fact_precio_diario")).count() == 3
    assert len(list((lago_sintetico / tarea_medallon.RESUMENES).glob("medallon_*.json"))) >= 1


def test_plata_usa_la_ultima_version_reprocesada(spark, lago_sintetico):
    """Un reproceso deja `_r1.csv` junto al original: conformidad guarda ambos y plata usa solo el último."""
    t1 = "20261014T060000_aaaaaa"
    crudo = lago_sintetico / lago.ruta_en_lago(f"capturas/exito/fecha=2026-10-14/{t1}.csv")
    escribir(crudo.with_name(crudo.stem + "_r1.csv"), [oferta(t1, "06:10", "exito", "E1", "1900000")])
    base = lago_sintetico.as_posix()
    r = Rutas(base)
    semanal.ejecutar(spark, base)
    assert leer(spark, r.conformidad("exito", "productos")).count() == 2
    exito = leer(spark, r.plata("precios/ofertas")).filter("sitio = 'exito'")
    assert exito.count() == 1 and exito.first()["precio_venta"] == 1900000
    assert leer(spark, r.oro("kpis/kpi_brecha_precio")).first()["precio_min"] == 1900000

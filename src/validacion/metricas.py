# -*- coding: utf-8 -*-
"""Métricas de validación (Etapa 6; Etapa 1, sección 10) sobre plata y oro del lago.

Dos pasos, porque el entorno local (Python 3.14) no tiene Spark y la imagen del medallón no tiene az login:

    1. bajar    (equipo local, con az login): copia plata/ y oro/ del lago a una carpeta y anota las
                rutas de evidencia de bronce (para medir la trazabilidad).
                python -m src.validacion.metricas bajar --lago <carpeta>
    2. calcular (imagen tfm-medallon, Spark 3.4 + Delta 2.4): calcula las métricas y escribe el informe.
                docker run --rm -v "<proyecto>:/app" -v "<carpeta>:/lago" --entrypoint python \
                    <imagen tfm-medallon> -m src.validacion.metricas calcular --lago /lago \
                    --salida /app/data/validacion [--muestra 12]

Métricas automáticas (las metas son las de la Etapa 1):
    completitud      registros con identificador, precio, título y fecha / registros con datos  ≥ 90 %
    cobertura        fichas con datos / fichas vigentes consultadas (sin las retiradas)          ≥ 90 %
    emparejamiento   (a) ofertas emparejadas / ofertas con stock (definición de la Etapa 2)
                     (b) productos en ≥2 cadenas / (esos + productos que la regla no unió)       ≥ 80 %
    identificación   hipótesis 1, en censo y automática: unidos consistentes en marca, pulgadas y
                     referencia / (unidos + productos que una búsqueda sin GTIN halla sin unir)   ≥ 80 %
    precisión        unidos consistentes / unidos                                                ≥ 80 %
    tiempo           duración de la captura diaria + medallón (meta ajustada el 19-nov)        < 150 min
    duplicados y trazabilidad (RNF-04 y RNF-05)
    precios atípicos (control de calidad, ver src/validacion/reglas.py)
La exactitud de precio y la reducción de esfuerzo se miden con el equipo: `--muestra N` deja una muestra
aleatoria de N ofertas por tienda del último día, para contrastarla a mano con el sitio.
"""
import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from src.validacion import reglas

log = logging.getLogger("validacion")

# La transformación se llamó pl_medallon_semanal hasta el 6-nov-2026 (corre a diario desde el 19-oct).
# Se aceptan los dos nombres para que el tiempo de proceso cubra toda la serie.
PIPELINES_MEDALLON = ("pl_medallon_diario", "pl_medallon_semanal")

CAPAS = ["plata", "oro"]
EVIDENCIA = "validacion/rutas_bronce.txt"
PIPELINES = "validacion/pipelines_synapse.json"
METAS = {"completitud": 0.90, "cobertura": 0.90, "emparejamiento": 0.80, "identificacion": 0.80,
         "precision": 0.80, "tiempo_min": 150}


# --------------------------------------------------------------------------- paso 1: bajar

def bajar(destino, raiz: Path, sitios: list[str], synapse: bool = True) -> dict:
    """Copia plata/ y oro/, lista las respuestas de bronce (no baja la evidencia en sí) y guarda las
    corridas de las pipelines de Synapse."""
    from src.nube import lago
    raiz = Path(raiz)
    remotos = {}
    for capa in CAPAS:
        remotos |= destino.listar(capa)
    for remota in sorted(remotos):
        ruta = raiz / remota
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(destino.bajar(remota))
    evidencia = sorted(r for s in sitios for r in destino.listar(f"{lago.ATERRIZAJE}/{s}/capturas"))
    (raiz / EVIDENCIA).parent.mkdir(parents=True, exist_ok=True)
    (raiz / EVIDENCIA).write_text("\n".join(evidencia), encoding="utf-8")
    corridas = pipelines_synapse() if synapse else []
    (raiz / PIPELINES).write_text(json.dumps(corridas, indent=1), encoding="utf-8")
    return {"archivos": len(remotos), "bytes": sum(remotos.values()), "evidencia": len(evidencia),
            "corridas_synapse": len(corridas)}


def pipelines_synapse(espacio: str = "syn-tfm-webscraping", desde: str = "2026-10-01T00:00:00Z") -> list[dict]:
    """Corridas de captura y medallón en Synapse (duración de punta a punta en Azure), con la CLI de Azure."""
    import shutil
    import subprocess
    from datetime import timedelta, timezone
    az = shutil.which("az") or r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
    hasta = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    salida = subprocess.run([az, "synapse", "pipeline-run", "query-by-workspace", "--workspace-name", espacio,
                             "--last-updated-after", desde, "--last-updated-before", hasta, "-o", "json"],
                            capture_output=True, text=True, check=True).stdout
    return [{"pipeline": r["pipelineName"], "estado": r["status"], "inicio_utc": r["runStart"],
             "minutos": round((r.get("durationInMs") or 0) / 60000, 1), "run_id": r["runId"]}
            for r in json.loads(salida)["value"] if r["pipelineName"] in ("pl_captura_diaria",) + PIPELINES_MEDALLON]


# --------------------------------------------------------------------------- paso 2: calcular (Spark)

def _filas(df) -> list[dict]:
    return [r.asDict() for r in df.collect()]


def _pct(a, b):
    return round(a / b, 4) if b else None


def ultima_corrida(ofertas):
    """Ofertas de la última corrida de cada sitio y día (como el informe de la Etapa 2 y oro)."""
    from pyspark.sql import functions as F
    ultima = ofertas.groupBy("sitio", "fecha_col").agg(F.max("id_ejecucion").alias("id_ejecucion"))
    return ofertas.join(ultima, ["sitio", "fecha_col", "id_ejecucion"])


def completitud(ofertas) -> list[dict]:
    from pyspark.sql import functions as F
    con_datos = ultima_corrida(ofertas).filter(F.col("estado_extraccion").isin("OK", "SIN_STOCK"))
    completo = F.col("completo") & F.col("fecha_captura_utc").isNotNull()
    df = (con_datos.groupBy("fecha_col", "sitio")
          .agg(F.count("*").alias("registros"), F.sum(completo.cast("int")).alias("completos"))
          .orderBy("fecha_col", "sitio"))
    return [{**f, "fecha": str(f.pop("fecha_col")), "pct": _pct(f["completos"], f["registros"])} for f in _filas(df)]


def cobertura(ejecuciones, ofertas) -> list[dict]:
    """Fichas (URL distintas) con datos / fichas consultadas que siguen publicadas. Se cuentan fichas y
    no registros porque una ficha puede traer varias ofertas (vendedores), como en Jumbo."""
    from pyspark.sql import Window
    from pyspark.sql import functions as F
    ventana = Window.partitionBy("sitio", "fecha_col").orderBy(F.col("id_ejecucion").desc())
    fichas = (ofertas.filter(F.col("estado_extraccion").isin("OK", "SIN_STOCK"))
              .groupBy("sitio", "id_ejecucion").agg(F.countDistinct("url").alias("con_datos")))
    df = (ejecuciones.withColumn("_n", F.row_number().over(ventana)).filter("_n = 1")
          .join(fichas, ["sitio", "id_ejecucion"], "left")
          .select("fecha_col", "sitio", "id_ejecucion", "modo", "estado", "descubiertos", "consultados",
                  "no_encontrados", "errores", "bloqueados", F.coalesce("con_datos", F.lit(0)).alias("con_datos"))
          .orderBy("fecha_col", "sitio"))
    salida = []
    for f in _filas(df):
        vigentes = (f["consultados"] or 0) - (f["no_encontrados"] or 0)
        salida.append({**f, "fecha": str(f.pop("fecha_col")), "vigentes": vigentes,
                       "pct": _pct(f["con_datos"], vigentes)})
    return salida


def emparejamiento(ofertas, kpi_calidad) -> tuple[list[dict], list[dict], list[dict]]:
    """(resumen por día, productos que la regla no unió, fallos de la identificación). Alkosto y Ktronix
    son la misma cadena. Los atributos y el título son los que publicó cada tienda en su oferta."""
    from pyspark.sql import functions as F
    from src.medallon.oro import TIENDAS
    cadena = {sitio: c for _, sitio, _, c in TIENDAS}
    ofertas_dia = {str(f["fecha_key"]): f for f in _filas(
        kpi_calidad.groupBy("fecha_key").agg(F.sum("emparejadas").alias("emparejadas"),
                                             F.sum("ofertas_con_stock").alias("ofertas_con_stock")))}
    productos = _filas(ultima_corrida(ofertas).filter("comparable AND disponible")
                       .select("fecha_col", "producto_key", "sitio", "marca", "pulgadas", "referencia", "titulo")
                       .distinct())
    por_dia = defaultdict(list)
    for p in productos:
        por_dia[str(p["fecha_col"])].append({**p, "cadena": cadena.get(p["sitio"], p["sitio"])})

    resumen, perdidos, fallos = [], [], []
    for fecha in sorted(por_dia):
        filas = por_dia[fecha]
        cadenas = defaultdict(set)
        for p in filas:
            cadenas[p["producto_key"]].add(p["cadena"])
        en_varias = sum(len(c) >= 2 for c in cadenas.values())
        faltan = reglas.pares_perdidos(filas)
        no_unidos = len({f["clave"] for f in faltan})   # cada clave es un producto real que la regla separó
        perdidos += [{"fecha": fecha, **f} for f in faltan]
        o = ofertas_dia.get(fecha.replace("-", ""), {})
        ident, detalle = reglas.identificacion(filas)
        fallos += [{"fecha": fecha, **d} for d in detalle]
        resumen.append({**ident, "fecha": fecha, "productos": len(cadenas), "en_2_o_mas_cadenas": en_varias,
                        "no_unidos": no_unidos, "pct_productos": _pct(en_varias, en_varias + no_unidos),
                        "ofertas_con_stock": o.get("ofertas_con_stock"), "ofertas_emparejadas": o.get("emparejadas"),
                        "pct_ofertas": _pct(o.get("emparejadas") or 0, o.get("ofertas_con_stock") or 0)})
    return resumen, perdidos, fallos


def tiempos(ejecuciones, carpeta_medallon: Path) -> tuple[list[dict], list[dict]]:
    """(capturas por corrida, corridas del medallón). La captura corre los sitios en paralelo."""
    from pyspark.sql import functions as F
    df = (ejecuciones.groupBy("id_ejecucion")
          .agg(F.min("inicio").alias("inicio"), F.max("fin").alias("fin"), F.first("modo").alias("modo"),
               F.countDistinct("sitio").alias("sitios"), F.max("duracion_s").alias("sitio_mas_lento_s"))
          .orderBy("id_ejecucion"))
    capturas = []
    for f in _filas(df):
        capturas.append({**f, "inicio": str(f["inicio"]), "fin": str(f["fin"]),
                         "minutos": round((f["fin"] - f["inicio"]).total_seconds() / 60, 1)})
    medallon = []
    for ruta in sorted(Path(carpeta_medallon).glob("medallon_*.json")):
        r = json.loads(ruta.read_text(encoding="utf-8"))
        ini, fin = (datetime.fromisoformat(r[k]) for k in ("inicio_utc", "fin_utc"))
        medallon.append({"archivo": ruta.name, "inicio_utc": r["inicio_utc"],
                         "minutos": round((fin - ini).total_seconds() / 60, 1),
                         "spark_s": r.get("medallon", {}).get("_segundos")})
    return capturas, medallon


def atipicos(fact, tiendas, productos) -> list[dict]:
    """Aplica `src.medallon.atipicos` a fact_precio_diario (última captura del día). Se recalcula aquí,
    y no se lee la columna de plata, para validar también datos de antes de que existiera."""
    from pyspark.sql import functions as F
    from src.medallon import atipicos as reglas_precio
    filas = _filas(fact.join(tiendas.select("tienda_key", "sitio", "cadena"), "tienda_key")
                   .join(productos.select("producto_key", "descripcion"), "producto_key", "left")
                   .select(F.col("fecha_key").alias("fecha"), "producto_key", "sitio", "cadena", "precio_lista",
                           "precio_venta", "metodo_emparejamiento", "disponible", "url", "descripcion"))
    return [{**f, "motivos": f.pop("motivos_atipico")} for f in reglas_precio.marcar(filas) if f["motivos_atipico"]]


def control_hechos(fact, evidencia: set[str]) -> dict:
    from pyspark.sql import functions as F
    total = fact.count()
    distintos = fact.select("fecha_key", "producto_key", "tienda_key").distinct().count()
    rutas = [r["ruta_bronze"] for r in fact.select("ruta_bronze").collect()]
    con_ruta = sum(1 for r in rutas if r)
    en_lago = sum(1 for r in rutas if r in evidencia) if evidencia else None
    dias = fact.agg(F.min("fecha_key"), F.max("fecha_key"), F.countDistinct("fecha_key")).first()
    return {"filas": total, "duplicados": total - distintos, "con_ruta_bronze": con_ruta,
            "ruta_existe_en_lago": en_lago, "pct_trazables": _pct(en_lago or 0, total) if evidencia else None,
            "primer_dia": dias[0], "ultimo_dia": dias[1], "dias": dias[2]}


def muestra_exactitud(fact, tiendas, productos, por_tienda: int) -> list[dict]:
    from pyspark.sql import functions as F
    ultimo = fact.agg(F.max("fecha_key")).first()[0]
    filas = _filas(fact.filter((F.col("fecha_key") == ultimo) & F.col("disponible"))
                   .join(tiendas.select("tienda_key", "sitio", "tienda"), "tienda_key")
                   .join(productos.select("producto_key", "descripcion", "marca", "pulgadas", "referencia"), "producto_key", "left")
                   .select("fecha_key", "tienda", "sitio", "producto_key", "descripcion", "marca", "pulgadas", "referencia",
                           "precio_venta", "precio_lista", "fecha_captura_utc", "url"))
    elegidas = reglas.muestra_estratificada(filas, por_tienda, semilla=int(ultimo))
    return [{"n": i, **{k: (str(v) if k == "fecha_captura_utc" else v) for k, v in f.items()},
             "precio_observado": "", "fecha_hora_revision": "", "coincide_S_N": "", "observacion": ""}
            for i, f in enumerate(elegidas, 1)]


def calcular(spark, raiz: Path, muestra: int = 0) -> dict:
    from src.medallon.rutas import Rutas
    raiz = Path(raiz)
    rutas = Rutas(raiz.as_posix())
    leer = lambda ruta: spark.read.format("delta").load(ruta)
    ofertas = leer(rutas.plata("precios/ofertas")).cache()
    ejecuciones = leer(rutas.plata("control/ejecuciones"))
    fact = leer(rutas.oro("hechos/fact_precio_diario")).cache()
    tiendas = leer(rutas.oro("dimensiones/dim_tienda"))
    productos = leer(rutas.oro("dimensiones/dim_producto"))
    evidencia = set((raiz / EVIDENCIA).read_text(encoding="utf-8").split("\n")) if (raiz / EVIDENCIA).exists() else set()

    empar, perdidos, fallos = emparejamiento(ofertas, leer(rutas.oro("kpis/kpi_calidad_captura")))
    capturas, medallon = tiempos(ejecuciones, raiz / "plata" / "control" / "medallon")
    resultado = {
        "completitud": completitud(ofertas),
        "cobertura": cobertura(ejecuciones, ofertas),
        "emparejamiento": empar,
        "no_unidos": perdidos,
        "fallos_identificacion": fallos,
        "capturas": capturas,
        "medallon": medallon,
        "hechos": control_hechos(fact, evidencia),
        "atipicos": atipicos(fact, tiendas, productos),
        "pipelines": json.loads((raiz / PIPELINES).read_text(encoding="utf-8")) if (raiz / PIPELINES).exists() else [],
    }
    if muestra:
        resultado["muestra"] = muestra_exactitud(fact, tiendas, productos, muestra)
    fact.unpersist()
    ofertas.unpersist()
    return resultado


# --------------------------------------------------------------------------- informe

def _tabla(filas: list[dict], columnas: list[str]) -> str:
    def celda(c, v):
        if v is None:
            return ""
        if isinstance(v, float) and (c.startswith("pct") or c == "valor"):   # proporciones -> porcentaje
            return f"{v * 100:.1f} %".replace(".", ",")
        return str(v)
    lineas = ["| " + " | ".join(columnas) + " |", "|" + "---|" * len(columnas)]
    lineas += ["| " + " | ".join(celda(c, f.get(c)) for c in columnas) + " |" for f in filas]
    return "\n".join(lineas)


def _total(filas: list[dict], num: str, den: str):
    return _pct(sum(f[num] or 0 for f in filas), sum(f[den] or 0 for f in filas))


def resumen_metas(r: dict) -> list[dict]:
    """Una fila por métrica con el valor global y si cumple la meta."""
    # Tiempo: si hay corridas de Synapse, la duración de punta a punta de las pipelines (incluye arrancar
    # el contenedor y subir al lago); si no, la del registro de ejecuciones y los resúmenes del medallón.
    exitosas = [p for p in r.get("pipelines", []) if p["estado"] == "Succeeded"]
    cap = [p["minutos"] for p in exitosas if p["pipeline"] == "pl_captura_diaria"]
    med = [p["minutos"] for p in exitosas if p["pipeline"] in PIPELINES_MEDALLON]
    if not cap:
        cap = [c["minutos"] for c in r["capturas"] if c["sitios"] >= 5]
        med = [m["minutos"] for m in r["medallon"]]
    tiempo = (max(cap) if cap else None, max(med) if med else None)
    empar = r["emparejamiento"]
    filas = [
        ("Completitud (RNF-02)", _total(r["completitud"], "completos", "registros"), METAS["completitud"]),
        ("Cobertura (RNF-03)", _total(r["cobertura"], "con_datos", "vigentes"), METAS["cobertura"]),
        ("Emparejamiento por ofertas", _total(empar, "ofertas_emparejadas", "ofertas_con_stock"),
         METAS["emparejamiento"]),
        ("Emparejamiento por productos",
         _pct(sum(e["en_2_o_mas_cadenas"] for e in empar), sum(e["en_2_o_mas_cadenas"] + e["no_unidos"] for e in empar)),
         METAS["emparejamiento"]),
    ]
    if empar and "unidos" in empar[0]:   # hipótesis 1 (memoria v8)
        correctos = sum(e["unidos_consistentes"] for e in empar)
        filas += [
            ("Identificación correcta (H1)",
             _pct(correctos, sum(e["unidos"] + e["no_unidos_candidatos"] for e in empar)), METAS["identificacion"]),
            ("Precisión del emparejamiento", _pct(correctos, sum(e["unidos"] for e in empar)), METAS["precision"]),
        ]
    salida = [{"metrica": n, "valor": v, "meta": f"≥ {m * 100:.0f} %", "cumple": "Sí" if v is not None and v >= m else "No"}
              for n, v, m in filas]
    if tiempo[0] is not None:
        total = tiempo[0] + (tiempo[1] or 0)
        salida.append({"metrica": "Tiempo captura + medallón (RNF-01), peor caso", "valor": f"{total:.1f} min".replace(".", ","),
                       "meta": f"< {METAS['tiempo_min']} min", "cumple": "Sí" if total < METAS["tiempo_min"] else "No"})
    h = r["hechos"]
    salida.append({"metrica": "Duplicados en fact_precio_diario (RNF-04)", "valor": str(h["duplicados"]), "meta": "0",
                   "cumple": "Sí" if h["duplicados"] == 0 else "No"})
    if h["pct_trazables"] is not None:
        salida.append({"metrica": "Trazabilidad a bronce (RNF-05)", "valor": h["pct_trazables"], "meta": "100 %",
                       "cumple": "Sí" if h["ruta_existe_en_lago"] == h["filas"] else "No"})
    return salida


def informe(r: dict) -> str:
    h = r["hechos"]
    conteo = defaultdict(int)
    for a in r["atipicos"]:
        for m in a["motivos"].split(","):
            conteo[m] += 1
    partes = [
        f"# Validación — datos del {h['primer_dia']} al {h['ultimo_dia']} ({h['dias']} días)",
        f"Generado el {datetime.now().strftime('%Y-%m-%d %H:%M')} con `python -m src.validacion.metricas`.",
        "## Resumen frente a las metas (Etapa 1, sección 10)",
        _tabla(resumen_metas(r), ["metrica", "valor", "meta", "cumple"]),
        "## Completitud por sitio y día (última corrida)",
        _tabla(r["completitud"], ["fecha", "sitio", "registros", "completos", "pct"]),
        "## Cobertura por sitio y día (última corrida)",
        _tabla(r["cobertura"], ["fecha", "sitio", "modo", "estado", "descubiertos", "consultados",
                                "no_encontrados", "vigentes", "con_datos", "errores", "bloqueados", "pct"]),
        "## Emparejamiento por día",
        _tabla(r["emparejamiento"], ["fecha", "productos", "en_2_o_mas_cadenas", "no_unidos", "pct_productos",
                                     "ofertas_con_stock", "ofertas_emparejadas", "pct_ofertas"]),
        "`no_unidos`: productos reales que la regla dejó separados (misma marca, pulgadas y referencia "
        "normalizada en dos cadenas, con GTIN distinto). El detalle está en `no_unidos.csv`.",
        "## Identificación correcta y precisión del emparejamiento (hipótesis 1)",
        _tabla(r["emparejamiento"], ["fecha", "unidos", "unidos_consistentes", "no_unidos_candidatos",
                                     "pct_identificacion", "pct_precision"]),
        "Censo de cada día, sin muestra manual. `unidos`: productos con ofertas de dos o más cadenas. "
        "`unidos_consistentes`: sus ofertas no se contradicen en marca, pulgadas ni referencia normalizada "
        "(un atributo que la tienda no publicó no cuenta como contradicción). `no_unidos_candidatos`: "
        "productos que una búsqueda independiente del GTIN encuentra en dos o más cadenas sin unir (misma "
        "marca, pulgadas y referencia compatible, o título muy similar si falta la referencia); cuentan como "
        "fallos. Identificación = consistentes / (unidos + no unidos). Precisión = consistentes / unidos. "
        "El detalle está en `fallos_identificacion.csv`.",
        "## Tiempos",
        _tabla(r["capturas"], ["id_ejecucion", "modo", "sitios", "inicio", "fin", "minutos", "sitio_mas_lento_s"]),
        _tabla(r["medallon"], ["archivo", "inicio_utc", "minutos", "spark_s"]) if r["medallon"] else
        "Sin resúmenes del medallón en plata/control/medallon.",
        "Pipelines de Synapse (de punta a punta en Azure; son las que cuentan para el RNF-01):",
        _tabla(r.get("pipelines", []), ["pipeline", "estado", "inicio_utc", "minutos", "run_id"]),
        "## Hechos: duplicados y trazabilidad",
        _tabla([h], ["filas", "duplicados", "con_ruta_bronze", "ruta_existe_en_lago", "pct_trazables"]),
        "## Precios atípicos (control de calidad)",
        f"{len(r['atipicos'])} de {h['filas']} filas de fact_precio_diario tienen al menos un motivo. "
        "El detalle está en `atipicos.csv`.",
        _tabla([{"motivo": m, "filas": n} for m, n in sorted(conteo.items())], ["motivo", "filas"]),
    ]
    return "\n\n".join(partes) + "\n"


def escribir_csv(ruta: Path, filas: list[dict]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:   # BOM y ';' para abrirlo en Excel
        if not filas:
            return
        w = csv.DictWriter(f, fieldnames=list(filas[0]), delimiter=";")
        w.writeheader()
        w.writerows(filas)


def guardar(r: dict, salida: Path) -> Path:
    salida = Path(salida)
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "metricas.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    escribir_csv(salida / "no_unidos.csv", r["no_unidos"])
    escribir_csv(salida / "atipicos.csv", r["atipicos"])
    escribir_csv(salida / "fallos_identificacion.csv", r.get("fallos_identificacion", []))
    if r.get("muestra"):
        escribir_csv(salida / f"muestra_exactitud_{r['muestra'][0]['fecha_key']}.csv", r["muestra"])
    texto = informe(r)
    (salida / "informe_validacion.md").write_text(texto, encoding="utf-8")
    return salida / "informe_validacion.md"


def main(argv: list[str] | None = None) -> int:
    from src.medallon.rutas import SITIOS
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("accion", choices=["bajar", "calcular"])
    ap.add_argument("--lago", required=True, help="carpeta con la copia local de plata/ y oro/")
    ap.add_argument("--salida", help="calcular: carpeta del informe (por defecto <lago>/validacion)")
    ap.add_argument("--muestra", type=int, default=0, help="calcular: ofertas por tienda para la muestra de exactitud")
    ap.add_argument("--lago-local", help="bajar: carpeta que reemplaza a ADLS (ensayo sin Azure)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("azure").setLevel(logging.WARNING)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.accion == "bajar":
        from src.nube import lago
        destino = lago.DestinoLocal(Path(args.lago_local)) if args.lago_local else lago.destino_desde_entorno()
        print(bajar(destino, Path(args.lago), SITIOS, synapse=not args.lago_local))
        return 0
    from src.nube.tarea_medallon import sesion_spark
    spark = sesion_spark()
    try:
        r = calcular(spark, Path(args.lago), args.muestra)
    finally:
        spark.stop()
    ruta = guardar(r, Path(args.salida or Path(args.lago) / "validacion"))
    print(ruta.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

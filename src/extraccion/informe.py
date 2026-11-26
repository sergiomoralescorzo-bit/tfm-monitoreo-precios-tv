# -*- coding: utf-8 -*-
"""Informe de una corrida de captura: cobertura, completitud y coincidencias entre cadenas.

Uso:
    python -m src.extraccion.informe                      # fecha más reciente: última corrida de cada sitio
    python -m src.extraccion.informe --fecha 2026-10-13
    python -m src.extraccion.informe --id 20261013T223816_ac564b

Escribe informes/informe_{fecha o id}.md bajo la raíz de datos y lo imprime.
Es una medición preliminar: el emparejamiento definitivo se hace en Silver (Etapa 3).
"""
import argparse
import glob
import sys
from pathlib import Path

import pandas as pd

from src.catalogo.emparejamiento import IndiceReferencias, clave_de, emparejar
from src.extraccion.ejecutar import RAIZ_PROYECTO, cargar_config, raiz_datos

MAESTRO = RAIZ_PROYECTO / "data" / "maestro" / "maestro_televisores.csv"
CADENA_CORTA = {"alkosto": "Alkosto/Ktronix", "ktronix": "Alkosto/Ktronix", "jumbo": "Jumbo",
                "olimpica": "Olímpica", "exito": "Éxito"}


def cargar_capturas(raiz: Path, id_ejecucion: str | None = None, fecha: str | None = None) -> pd.DataFrame:
    """Capturas de una corrida (`id_ejecucion`) o, por defecto, la última corrida de cada sitio en
    la fecha indicada (o la más reciente), coherente con "precio diario = última captura del día"."""
    archivos = [Path(a) for a in glob.glob(str(raiz / "capturas" / "*" / "fecha=*" / "*.csv"))]
    if not archivos:
        raise SystemExit(f"No hay capturas en {raiz / 'capturas'}")
    if id_ejecucion:
        elegidos = [a for a in archivos if a.stem == id_ejecucion]
    else:
        fecha = fecha or max(a.parent.name for a in archivos).removeprefix("fecha=")
        del_dia = [a for a in archivos if a.parent.name == f"fecha={fecha}"]
        ultimo: dict[str, Path] = {}
        for a in del_dia:
            sitio = a.parent.parent.name
            if sitio not in ultimo or a.stem > ultimo[sitio].stem:
                ultimo[sitio] = a
        elegidos = list(ultimo.values())
    if not elegidos:
        raise SystemExit("No hay capturas para los filtros indicados")
    df = pd.concat([pd.read_csv(a, sep=";", dtype=str, encoding="utf-8-sig") for a in elegidos], ignore_index=True)
    for c in ("precio_venta", "precio_lista", "pulgadas"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("en_alcance", "es_vendedor_propio", "disponible"):
        df[c] = df[c].eq("True")
    return df


def tabla_md(df: pd.DataFrame) -> str:
    cols = [str(c) for c in df.columns]
    filas = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        filas.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in r.values) + " |")
    return "\n".join(filas)


def construir(df: pd.DataFrame, maestro: pd.DataFrame) -> str:
    corridas = ", ".join(sorted(df["id_ejecucion"].unique()))
    # 1. Estados por sitio
    estados = df.pivot_table(index="sitio", columns="estado_extraccion", values="url", aggfunc="count", fill_value=0)
    estados["total"] = estados.sum(axis=1)

    # 2. Alcance y completitud (sobre registros OK/SIN_STOCK)
    datos = df[df["estado_extraccion"].isin(["OK", "SIN_STOCK"])].copy()
    datos["completo"] = (datos["ean_publicado"].notna() | datos["sku_tienda"].notna()) \
        & datos["precio_venta"].gt(0) & datos["titulo"].notna()
    exclusiones = datos.pivot_table(index="sitio", columns="motivo_exclusion", values="url",
                                    aggfunc="count", fill_value=0)
    alc = datos[datos["en_alcance"]]
    resumen = pd.DataFrame({
        "registros con datos": datos.groupby("sitio").size(),
        "completos %": (datos.groupby("sitio")["completo"].mean() * 100).round(1),
        "TV propios en alcance": alc.groupby("sitio").size(),
        "con stock": alc[alc["disponible"]].groupby("sitio").size(),
        "con EAN %": (alc.groupby("sitio")["ean_publicado"].apply(lambda s: s.notna().mean()) * 100).round(1),
    }).fillna(0)

    # 3. Emparejamiento (en alcance y con stock)
    indice = IndiceReferencias()
    for _, m in maestro.iterrows():
        indice.agregar(m["clave_referencia"], m["gtin14"])
    for _, r in alc.iterrows():
        if isinstance(r["gtin14"], str):
            indice.agregar(clave_de(r["marca"], r["pulgadas"], r["referencia"]), r["gtin14"])
    vend = alc[alc["disponible"]].copy()
    res = [emparejar(r["ean_publicado"], r["marca"], r["pulgadas"], r["referencia"], indice)
           for _, r in vend.iterrows()]
    vend["producto"] = [p for p, _ in res]
    vend["metodo"] = [m for _, m in res]
    vend["cadena"] = vend["sitio"].map(CADENA_CORTA)
    gtins_maestro = set(maestro["gtin14"])
    vend["en_maestro"] = vend["producto"].isin(gtins_maestro)
    cadenas_por_producto = vend.dropna(subset=["producto"]).groupby("producto")["cadena"].nunique()
    vend["n_cadenas"] = vend["producto"].map(cadenas_por_producto).fillna(1).astype(int)
    vend["emparejado"] = vend["en_maestro"] | vend["n_cadenas"].ge(2)
    metodo = vend.pivot_table(index="sitio", columns="metodo", values="url", aggfunc="count", fill_value=0)
    metodo["en maestro"] = vend.groupby("sitio")["en_maestro"].sum()
    metodo["en ≥2 cadenas"] = vend[vend["n_cadenas"] >= 2].groupby("sitio").size()
    metodo["emparejados %"] = (vend.groupby("sitio")["emparejado"].mean() * 100).round(1)
    metodo = metodo.fillna(0)

    productos = vend.dropna(subset=["producto"]).drop_duplicates(["producto", "cadena"])
    dist = productos.groupby("producto")["cadena"].nunique().value_counts().sort_index()
    total_emparejados = vend["emparejado"].mean() * 100 if len(vend) else 0

    partes = [
        f"# Informe de captura — {df['fecha_captura_col'].min()[:10]}",
        f"Corridas: {corridas}",
        f"Fecha de captura (Colombia): {df['fecha_captura_col'].min()[:16]} a {df['fecha_captura_col'].max()[:16]}",
        "## 1. Estados de extracción por sitio", tabla_md(estados.reset_index()),
        "## 2. Alcance y completitud", tabla_md(resumen.astype({c: int for c in resumen.columns if "%" not in c}).reset_index()),
        "Motivos de exclusión (registros con datos):", tabla_md(exclusiones.reset_index()),
        "## 3. Emparejamiento preliminar (TV propios en alcance con stock)", tabla_md(metodo.astype(
            {c: int for c in metodo.columns if "%" not in c}).reset_index()),
        f"**Ofertas emparejadas (con el maestro o con otra cadena): {total_emparejados:.1f} %** "
        f"de {len(vend)} ofertas.",
        "Productos distintos según el número de cadenas que los venden (Alkosto y Ktronix cuentan como una cadena):",
        tabla_md(pd.DataFrame({"cadenas": dist.index, "productos": dist.values})),
    ]
    return "\n\n".join(partes) + "\n"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--id", help="una corrida concreta (id_ejecucion)")
    ap.add_argument("--fecha", help="AAAA-MM-DD; por defecto la más reciente (última corrida de cada sitio)")
    ap.add_argument("--datos", help="carpeta raíz de datos")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # consola de Windows (cp1252)
    raiz = raiz_datos(cargar_config(), args.datos)
    df = cargar_capturas(raiz, args.id, args.fecha)
    maestro = pd.read_csv(MAESTRO, sep=";", dtype=str, encoding="utf-8-sig")
    maestro = maestro[maestro["en_alcance"] == "True"]
    texto = construir(df, maestro)
    nombre = args.id or df["fecha_captura_col"].min()[:10]
    salida = raiz / "informes" / f"informe_{nombre}.md"
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(texto, encoding="utf-8")
    print(texto)
    print(f"Guardado en {salida}")


if __name__ == "__main__":
    main()

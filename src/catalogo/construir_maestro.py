# -*- coding: utf-8 -*-
"""Construye el maestro de televisores desde la hoja DIM_PRODUCTO (División Video, Línea Tv).

Uso:
    python -m src.catalogo.construir_maestro [ruta_excel]

Salida:
    data/maestro/maestro_televisores.csv
    data/maestro/resumen_maestro.txt
"""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.catalogo import atributos_tv as at
from src.catalogo import gtin

RAIZ = Path(__file__).resolve().parents[2]
EXCEL_POR_DEFECTO = RAIZ.parent / "Documentos_iniciales" / "DataFeed-30-09-2026.xlsx"
HOJA = "DIM_PRODUCTO"
SALIDA = RAIZ / "data" / "maestro"
# Tecnologías vigentes. Se excluyen CRT, LCD, Plasma y DLP (descontinuadas).
SUBLINEAS_VIGENTES = ["LED", "LED - BASICO", "LED - QLED - QNED", "OLED", "LED - MINILED"]


def construir(ruta_excel: Path) -> pd.DataFrame:
    df = pd.read_excel(ruta_excel, sheet_name=HOJA, dtype=str)
    df = df[(df["Descr Division"] == "Video") & (df["Descr Linea"] == "Tv")].reset_index(drop=True)
    desc = df["Desc Producto"].map(at.limpiar_descripcion)

    m = pd.DataFrame({
        "ean_original": df["Cod Producto"].map(gtin.limpiar),
        "gtin14": df["Cod Producto"].map(gtin.a_gtin14),
        "descripcion": desc,
        "marca": [at.marca(d, mm) for d, mm in zip(desc, df["Cod Marca-Prove-Alk"])],
        "pulgadas": desc.map(at.pulgadas).astype("Int64"),
        "referencia": desc.map(at.referencia),
        "tecnologia": desc.map(at.tecnologia),
        "resolucion": desc.map(at.resolucion),
        "sublinea": df["Descr Sublinea"],
        "categoria": df["Descr Categoria"],
        "rango_pulgadas": df["Descr Subcategoria"].str.replace('"', "", regex=False),
        "proveedor": df["Descripción Proveedor"],
        "clasif_articulo": df["Cod Clasif Articulo"],
        "es_combo": desc.map(at.es_combo),
        "es_no_nuevo": desc.map(at.es_no_nuevo),
    })
    # Pulgadas desde la referencia cuando la descripción no las trae ("TV SAMSUNG UN50CU8200KXZL").
    sin_pulg = m["pulgadas"].isna()
    m.loc[sin_pulg, "pulgadas"] = m.loc[sin_pulg, "referencia"].map(at.pulgadas_desde_referencia)
    # Tecnología desde la sublínea del maestro cuando el texto no la menciona.
    desde_sublinea = df["Descr Sublinea"].map({"LED": "LED", "LED - BASICO": "LED", "OLED": "OLED",
                                               "LED - MINILED": "Mini LED", "LED - QLED - QNED": "QLED"})
    m["tecnologia"] = m["tecnologia"].fillna(desde_sublinea)
    m["referencia_norm"] = [
        at.referencia_normalizada(r, None if pd.isna(p) else int(p), a)
        for r, p, a in zip(m["referencia"], m["pulgadas"], m["marca"])
    ]
    m["clave_referencia"] = [
        at.clave_referencia(a, None if pd.isna(p) else int(p), r)
        for a, p, r in zip(m["marca"], m["pulgadas"], m["referencia_norm"])
    ]
    m["gtin_valido"] = m["gtin14"].notna()
    m["tecnologia_vigente"] = m["sublinea"].isin(SUBLINEAS_VIGENTES)
    m["en_alcance"] = m["gtin_valido"] & m["tecnologia_vigente"] & ~m["es_combo"] & ~m["es_no_nuevo"]
    return m


def resumen(m: pd.DataFrame) -> str:
    alc = m[m["en_alcance"]]
    dup = alc["clave_referencia"].dropna()
    lineas = [
        f"Maestro de televisores - generado {datetime.now():%Y-%m-%d %H:%M}",
        f"Registros División Video / Línea Tv: {len(m)} (EAN únicos: {m['ean_original'].nunique()})",
        f"GTIN con dígito de control válido: {m['gtin_valido'].sum()}",
        f"Tecnología vigente (LED, QLED/QNED, OLED, Mini LED): {m['tecnologia_vigente'].sum()}",
        f"Combos: {m['es_combo'].sum()} | Demo/exhibición/reacondicionado: {m['es_no_nuevo'].sum()}",
        f"EN ALCANCE: {len(alc)}",
        f"  con marca: {alc['marca'].notna().sum()} | pulgadas: {alc['pulgadas'].notna().sum()} | "
        f"referencia: {alc['referencia'].notna().sum()}",
        f"  claves marca|pulgadas|referencia repetidas: {dup.duplicated(keep=False).sum()}",
        "",
        "En alcance por marca:", alc["marca"].fillna("(sin marca)").value_counts().to_string(),
        "",
        "En alcance por tecnología:", alc["tecnologia"].fillna("(sin dato)").value_counts().to_string(),
        "",
        "En alcance sin marca, pulgadas o referencia (revisar):",
        alc[alc["marca"].isna() | alc["pulgadas"].isna() | alc["referencia"].isna()]["descripcion"].to_string(),
    ]
    return "\n".join(lineas)


def main():
    ruta = Path(sys.argv[1]) if len(sys.argv) > 1 else EXCEL_POR_DEFECTO
    m = construir(ruta)
    SALIDA.mkdir(parents=True, exist_ok=True)
    m.to_csv(SALIDA / "maestro_televisores.csv", index=False, encoding="utf-8-sig", sep=";")
    texto = resumen(m)
    (SALIDA / "resumen_maestro.txt").write_text(texto, encoding="utf-8")
    print(texto.split("\n\nEn alcance sin")[0])


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Construye el maestro de productos Apple a partir de la hoja 'Telefonia Celular'.

Uso:
    python -m src.catalogo.construir_maestro [ruta_excel]

Salida:
    data/maestro/maestro_productos_apple.csv
    data/maestro/resumen_maestro.txt
"""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.catalogo import atributos as at
from src.catalogo import gtin

RAIZ = Path(__file__).resolve().parents[2]
EXCEL_POR_DEFECTO = RAIZ.parent / "Documentos_iniciales" / "DataFeed-30-09-2026.xlsx"
HOJA = "Telefonia Celular"
SALIDA = RAIZ / "data" / "maestro"


def construir(ruta_excel: Path) -> pd.DataFrame:
    df = pd.read_excel(ruta_excel, sheet_name=HOJA, dtype={"Cod Producto": str})
    desc = df["Desc Producto"].map(at.limpiar_descripcion)

    maestro = pd.DataFrame({
        "ean_original": df["Cod Producto"].map(gtin.limpiar),
        "gtin14": df["Cod Producto"].map(gtin.a_gtin14),
        "descripcion": desc,
        "modelo": desc.map(at.modelo),
        "capacidad_gb": desc.map(at.capacidad_gb).astype("Int64"),
        "color": desc.map(at.color),
        "es_demo": desc.map(at.es_demo),
        "es_reacondicionado": desc.map(at.es_reacondicionado),
        "es_operador": df["Descr Categoria"].eq("Operador")
                       | desc.str.contains(r"comcel|tigo|movistar|claro", case=False),
        "categoria": df["Descr Categoria"],
        "clasif_articulo": df["Cod Clasif Articulo"],
        "marca_proveedor": df["Cod Marca-Prove-Alk"],
    })
    maestro["gtin_valido"] = maestro["gtin14"].notna()
    maestro["clave_atributos"] = [
        at.clave_atributos(m, None if pd.isna(c) else int(c), col)
        for m, c, col in zip(maestro["modelo"], maestro["capacidad_gb"], maestro["color"])
    ]
    # En alcance del estudio: equipo nuevo, libre (no operador), con GTIN válido.
    maestro["en_alcance"] = (
        maestro["gtin_valido"] & ~maestro["es_demo"]
        & ~maestro["es_reacondicionado"] & ~maestro["es_operador"]
    )
    return maestro


def resumen(m: pd.DataFrame) -> str:
    alc = m[m["en_alcance"]]
    lineas = [
        f"Maestro de productos Apple - generado {datetime.now():%Y-%m-%d %H:%M}",
        f"Registros en la hoja '{HOJA}': {len(m)}",
        f"EAN únicos: {m['ean_original'].nunique()}",
        f"GTIN con dígito de control válido: {m['gtin_valido'].sum()}",
        f"  12 dígitos (UPC-A): {(m['ean_original'].str.len() == 12).sum()} | "
        f"13 dígitos (EAN-13): {(m['ean_original'].str.len() == 13).sum()}",
        f"Demo: {m['es_demo'].sum()} | Reacondicionados: {m['es_reacondicionado'].sum()} | "
        f"Operador: {m['es_operador'].sum()}",
        f"En alcance (nuevo, libre, GTIN válido): {len(alc)}",
        f"Con modelo identificado: {m['modelo'].notna().sum()} | con capacidad: "
        f"{m['capacidad_gb'].notna().sum()} | con color: {m['color'].notna().sum()}",
        "",
        "SKU en alcance por modelo:",
        alc["modelo"].value_counts().sort_index().to_string(),
        "",
        "Descripciones sin modelo/capacidad/color reconocido (revisar):",
        m[m["modelo"].isna() | m["capacidad_gb"].isna() | m["color"].isna()]["descripcion"].to_string(),
    ]
    return "\n".join(lineas)


def main():
    ruta = Path(sys.argv[1]) if len(sys.argv) > 1 else EXCEL_POR_DEFECTO
    m = construir(ruta)
    SALIDA.mkdir(parents=True, exist_ok=True)
    m.to_csv(SALIDA / "maestro_productos_apple.csv", index=False, encoding="utf-8-sig", sep=";")
    texto = resumen(m)
    (SALIDA / "resumen_maestro.txt").write_text(texto, encoding="utf-8")
    print(texto.split("\n\nDescripciones")[0])


if __name__ == "__main__":
    main()

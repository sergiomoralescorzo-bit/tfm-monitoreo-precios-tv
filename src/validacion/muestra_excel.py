# -*- coding: utf-8 -*-
"""Libro de Excel para la revisión manual de la muestra de exactitud (Etapa 6, sección 4).

Convierte `muestra_exactitud_<fecha>.csv` (lo deja `metricas.py --muestra 12`) en un libro con:
    Revisión        una fila por oferta, con el hipervínculo a la ficha, lo que capturó el sistema y las
                    columnas que llena el equipo (precio de venta y de lista en la página, existencias,
                    producto correcto, revisor, hora y observación). «¿Coincide?» se calcula solo.
    Resumen         porcentajes por tienda y en total, con fórmulas (se actualizan al llenar la revisión).
    Categoría       cuántos televisores muestra la categoría de cada sitio (cobertura externa).
    Instrucciones   cómo revisar.

Uso (el día del corte, apenas termine la corrida y el cálculo de la muestra):
    python -m src.validacion.muestra_excel data/validacion/2026-11-30/muestra_exactitud_20261130.csv
"""
import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

COLOMBIA = ZoneInfo("America/Bogota")
AZUL = PatternFill("solid", fgColor="1F3A5F")
GRIS = PatternFill("solid", fgColor="EEF1F5")
AMARILLO = PatternFill("solid", fgColor="FFF4CC")
VERDE = PatternFill("solid", fgColor="D9EAD3")
ROJO = PatternFill("solid", fgColor="F4CCCC")
BLANCO = Font(color="FFFFFF", bold=True)
LINEA = Border(bottom=Side(style="thin", color="C9CED6"))
PESOS = '"$"#,##0'

# (encabezado, ancho, origen): origen = campo del CSV, "=fórmula" con {f} = fila, o None = lo llena el equipo
COLUMNAS = [
    ("N.º", 5, "n"),
    ("Tienda", 10, "tienda"),
    ("Marca", 11, "marca"),
    ("Pulgadas", 9, "pulgadas"),
    ("Referencia", 16, "referencia"),
    ("Descripción", 38, "descripcion"),
    ("Ficha", 10, "url"),
    ("Capturado (hora Colombia)", 17, "fecha_captura_utc"),
    ("Precio de venta capturado", 14, "precio_venta"),
    ("Precio de lista capturado", 14, "precio_lista"),
    ("Precio de venta en la página", 14, None),
    ("¿Coincide la venta?", 11, '=IF(K{f}="","",IF(K{f}=I{f},"Sí","No"))'),
    ("Precio de lista en la página", 14, None),
    ("¿Coincide la lista?", 11, '=IF(M{f}="","",IF(M{f}=J{f},"Sí","No"))'),
    ("¿Tiene existencias?", 12, None),
    ("¿Es el mismo producto?", 12, None),
    ("Revisor", 12, None),
    ("Fecha y hora de revisión", 17, None),
    ("Observación", 40, None),
]
EQUIPO = [i + 1 for i, (_, _, o) in enumerate(COLUMNAS) if o is None]
FILA0 = 4  # primera fila de datos


def leer_csv(ruta: Path) -> list[dict]:
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def hora_colombia(texto: str) -> datetime | None:
    if not texto:
        return None
    t = datetime.fromisoformat(texto.strip().replace(" ", "T")[:26])
    return t.replace(tzinfo=ZoneInfo("UTC")).astimezone(COLOMBIA).replace(tzinfo=None)


def _numero(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return v or None


def _encabezado(ws, fila: int, textos: list[str]) -> None:
    for c, t in enumerate(textos, 1):
        celda = ws.cell(fila, c, t)
        celda.fill, celda.font = AZUL, BLANCO
        celda.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")


def hoja_revision(ws, filas: list[dict], fecha: str) -> int:
    ws.title = "Revisión"
    ws["A1"] = f"Muestra de exactitud de precios — captura del {fecha}"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = ("Columnas grises: lo que capturó el sistema. Columnas amarillas: lo que anota quien revisa. "
                "«¿Coincide?» se calcula solo. Revisar el mismo día de la captura.")
    ws["A2"].font = Font(italic=True, color="555555")
    _encabezado(ws, FILA0 - 1, [c[0] for c in COLUMNAS])
    ws.row_dimensions[FILA0 - 1].height = 45
    for i, d in enumerate(filas):
        f = FILA0 + i
        for c, (_, _, origen) in enumerate(COLUMNAS, 1):
            celda = ws.cell(f, c)
            if origen is None:
                celda.fill = AMARILLO
            elif origen.startswith("="):
                celda.value = origen.format(f=f)
                celda.alignment = Alignment(horizontal="center")
            elif origen == "url":
                celda.value, celda.hyperlink = "Abrir ficha", d.get("url")
                celda.font = Font(color="0563C1", underline="single")
            elif origen == "fecha_captura_utc":
                celda.value, celda.number_format = hora_colombia(d.get(origen, "")), "dd/mm/yyyy hh:mm"
            elif origen in ("n", "pulgadas", "precio_venta", "precio_lista"):
                celda.value = _numero(d.get(origen))
            else:
                celda.value = d.get(origen) or None
            if origen is not None and not origen.startswith("="):
                celda.fill = GRIS
            celda.border = LINEA
        for c in (9, 10, 11, 13):
            ws.cell(f, c).number_format = PESOS
        ws.cell(f, 18).number_format = "dd/mm/yyyy hh:mm"
    ultima = FILA0 + len(filas) - 1
    for c, (_, ancho, _) in enumerate(COLUMNAS, 1):
        ws.column_dimensions[get_column_letter(c)].width = ancho
    ws.freeze_panes = ws.cell(FILA0, 7)
    ws.auto_filter.ref = f"A{FILA0 - 1}:{get_column_letter(len(COLUMNAS))}{ultima}"

    si_no = DataValidation(type="list", formula1='"Sí,No"', allow_blank=True)
    precio = DataValidation(type="whole", operator="greaterThan", formula1="0", allow_blank=True,
                            error="Escriba el precio sin puntos ni signo $ (por ejemplo, 1499900).")
    ws.add_data_validation(si_no)
    ws.add_data_validation(precio)
    for col in ("O", "P"):
        si_no.add(f"{col}{FILA0}:{col}{ultima}")
    for col in ("K", "M"):
        precio.add(f"{col}{FILA0}:{col}{ultima}")
    for col in ("L", "N"):
        rango = f"{col}{FILA0}:{col}{ultima}"
        ws.conditional_formatting.add(rango, FormulaRule(formula=[f'{col}{FILA0}="Sí"'], fill=VERDE))
        ws.conditional_formatting.add(rango, FormulaRule(formula=[f'{col}{FILA0}="No"'], fill=ROJO))
    return ultima


def hoja_resumen(ws, tiendas: list[str], ultima: int) -> None:
    r = f"'Revisión'!$B${FILA0}:$B${ultima}"
    col = lambda letra: f"'Revisión'!${letra}${FILA0}:${letra}${ultima}"  # noqa: E731
    ws["A1"] = "Resumen de la revisión (se actualiza al llenar la hoja Revisión)"
    ws["A1"].font = Font(bold=True, size=13)
    _encabezado(ws, 3, ["Tienda", "Ofertas", "Revisadas", "Venta coincide", "% venta", "Lista coincide",
                        "% lista", "Mismo producto", "% producto", "Con existencias", "% existencias"])
    for i, t in enumerate(tiendas + ["Total"]):
        f = 4 + i
        filtro = f'{r},"{t}",' if t != "Total" else ""
        cuenta = (lambda c, v: f'COUNTIFS({filtro}{col(c)},"{v}")') if t != "Total" else (
            lambda c, v: f'COUNTIF({col(c)},"{v}")')
        ws.cell(f, 1, t).font = Font(bold=(t == "Total"))
        ws.cell(f, 2, f"=COUNTIF({r},A{f})" if t != "Total" else f"=SUM(B4:B{f - 1})")
        ws.cell(f, 3, f'=COUNTIFS({r},A{f},{col("K")},"<>")' if t != "Total" else f"=SUM(C4:C{f - 1})")
        for c, (letra, valor) in zip((4, 6, 8, 10), (("L", "Sí"), ("N", "Sí"), ("P", "Sí"), ("O", "Sí"))):
            ws.cell(f, c, "=" + cuenta(letra, valor))
            ws.cell(f, c + 1, f'=IF(C{f}=0,"",{get_column_letter(c)}{f}/C{f})').number_format = "0.0%"
    for c, ancho in zip("ABCDEFGHIJK", (12, 9, 10, 10, 9, 10, 9, 10, 10, 11, 11)):
        ws.column_dimensions[c].width = ancho
    n = 4 + len(tiendas) + 2
    ws.cell(n, 1, "Meta de exactitud de precio: ≥ 80 % (Etapa 1). Con 60 casos, un 90 % tiene un margen "
                  "de unos ±8 puntos (95 %).").font = Font(italic=True, color="555555")
    ws.cell(n + 1, 1, "«Revisadas» cuenta las filas con precio de venta anotado.").font = Font(italic=True,
                                                                                                color="555555")


def hoja_categoria(ws, tiendas: list[str]) -> None:
    ws["A1"] = "Cobertura externa: televisores que muestra la categoría de cada sitio"
    ws["A1"].font = Font(bold=True, size=13)
    _encabezado(ws, 3, ["Tienda", "Televisores en la categoría", "Fecha y hora", "Revisor", "Observación"])
    for i, t in enumerate(tiendas):
        ws.cell(4 + i, 1, t)
        for c in range(2, 6):
            ws.cell(4 + i, c).fill = AMARILLO
    for c, ancho in zip("ABCDE", (12, 16, 17, 12, 40)):
        ws.column_dimensions[c].width = ancho


def hoja_instrucciones(ws) -> None:
    pasos = [
        "Cómo revisar",
        "1. Revise el mismo día de la captura: los precios cambian y la comparación pierde valor con los días.",
        "2. En la hoja Revisión, abra cada ficha con «Abrir ficha».",
        "3. Precio de venta en la página: el precio principal que paga cualquier cliente, sin descuentos por "
        "medio de pago (tarjeta propia, cupones). Escríbalo sin puntos ni signo $.",
        "4. Precio de lista en la página: el precio tachado. Si la página no muestra uno, escriba el mismo "
        "precio de venta.",
        "5. ¿Tiene existencias? y ¿Es el mismo producto? (marca, pulgadas y referencia): elija Sí o No.",
        "6. Anote su nombre, la fecha y hora de la revisión y, si algo no coincide, la causa probable en "
        "Observación (por ejemplo, cambió la promoción después de las 06:00 o la ficha ya no existe).",
        "7. Las columnas «¿Coincide?» y la hoja Resumen se calculan solas.",
        "8. En la hoja Categoría, anote cuántos televisores muestra la categoría de cada sitio.",
    ]
    for i, t in enumerate(pasos, 1):
        ws.cell(i, 1, t).font = Font(bold=(i == 1), size=13 if i == 1 else 11)
        ws.cell(i, 1).alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 110


def escribir(filas: list[dict], destino: Path) -> Path:
    fecha_key = str(filas[0].get("fecha_key", "")) if filas else ""
    fecha = f"{fecha_key[6:]}/{fecha_key[4:6]}/{fecha_key[:4]}" if len(fecha_key) == 8 else fecha_key
    tiendas = list(dict.fromkeys(d["tienda"] for d in filas))
    wb = Workbook()
    ultima = hoja_revision(wb.active, filas, fecha)
    hoja_resumen(wb.create_sheet("Resumen"), tiendas, ultima)
    hoja_categoria(wb.create_sheet("Categoría"), tiendas)
    hoja_instrucciones(wb.create_sheet("Instrucciones"))
    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)
    return destino


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", type=Path, help="muestra_exactitud_<fecha>.csv")
    ap.add_argument("--salida", type=Path, help="por defecto, el mismo nombre con .xlsx")
    args = ap.parse_args(argv)
    filas = leer_csv(args.csv)
    destino = escribir(filas, args.salida or args.csv.with_suffix(".xlsx"))
    print(f"{len(filas)} ofertas -> {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

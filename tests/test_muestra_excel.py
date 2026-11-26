# -*- coding: utf-8 -*-
"""Libro de Excel de la muestra de exactitud (src/validacion/muestra_excel.py)."""
from openpyxl import load_workbook

from src.validacion import muestra_excel as mx


def filas():
    base = {"fecha_key": "20261130", "sitio": "alkosto", "producto_key": "08806099025090", "marca": "SAMSUNG",
            "pulgadas": "55", "referencia": "QN55QN70H", "descripcion": "TV SAMSUNG 55", "precio_venta": "2699900",
            "precio_lista": "5339900", "fecha_captura_utc": "2026-11-30 11:06:05.245470",
            "url": "https://www.alkosto.com/tv/p/8806099025090"}
    return [dict(base, n="1", tienda="Alkosto"), dict(base, n="2", tienda="Éxito", sitio="exito")]


def test_libro_con_hipervinculos_formulas_y_resumen(tmp_path):
    ruta = mx.escribir(filas(), tmp_path / "m.xlsx")
    wb = load_workbook(ruta)
    assert wb.sheetnames == ["Revisión", "Resumen", "Categoría", "Instrucciones"]
    ws = wb["Revisión"]
    f = mx.FILA0
    assert ws.cell(f, 7).hyperlink.target == "https://www.alkosto.com/tv/p/8806099025090"
    assert ws.cell(f, 8).value.hour == 6                       # 11:06 UTC = 06:06 en Colombia
    assert ws.cell(f, 9).value == 2699900
    assert ws.cell(f, 12).value == f'=IF(K{f}="","",IF(K{f}=I{f},"Sí","No"))'
    assert [ws.cell(f - 1, c).value for c in mx.EQUIPO][:2] == ["Precio de venta en la página",
                                                                  "Precio de lista en la página"]
    resumen = wb["Resumen"]
    assert [resumen.cell(r, 1).value for r in (4, 5, 6)] == ["Alkosto", "Éxito", "Total"]
    assert "'Revisión'!$B$4:$B$5" in resumen.cell(4, 2).value
    assert [wb["Categoría"].cell(r, 1).value for r in (4, 5)] == ["Alkosto", "Éxito"]

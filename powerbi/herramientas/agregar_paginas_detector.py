# -*- coding: utf-8 -*-
"""Páginas «Descuentos» y «Eventos del día» (memoria, Tabla 21; 19-nov-2026).

Agrega al PBIP existente, sin regenerarlo (el equipo editó el informe en Desktop):
  - modelo: columnas del detector en fact_precio_diario, tabla fact_evento_comercial con sus relaciones
    y medidas de las dos páginas;
  - informe: dos páginas armadas copiando visuales que ya funcionan en la página «calidad»
    (encabezado, segmentadores de fecha y tienda, tarjetas, gráfico de columnas y tabla).

Es idempotente: si ya existen las columnas, la tabla o las páginas, no las duplica.
Uso:  .venv/Scripts/python powerbi/herramientas/agregar_paginas_detector.py
Después: abrir el .pbip en Power BI Desktop y Actualizar (las vistas de Synapse ya tienen los datos).
"""
import copy
import hashlib
import json
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
MODELO = RAIZ / "TFM_Precios.SemanticModel" / "definition"
PAGINAS = RAIZ / "TFM_Precios.Report" / "definition" / "pages"
NS = uuid.UUID("6f1c2d9e-3b7a-4c55-9e0d-1a2b3c4d5e6f")       # el mismo de generar_pbip.py


def tag(*partes: str) -> str:
    return str(uuid.uuid5(NS, "/".join(partes)))


def nombre(*partes: str) -> str:
    return hashlib.sha1("/".join(partes).encode()).hexdigest()[:20]


# ============================================================================ modelo

def columna(tabla, nombre_, tipo, formato=None, oculta=False, categoria=None):
    lineas = [f"\tcolumn {nombre_}", f"\t\tdataType: {tipo}"]
    if formato:
        lineas.append(f"\t\tformatString: {formato}")
    if oculta:
        lineas.append("\t\tisHidden")
    if categoria:
        lineas.append(f"\t\tdataCategory: {categoria}")
    lineas += [f"\t\tlineageTag: {tag(tabla, nombre_)}", "\t\tsummarizeBy: none", f"\t\tsourceColumn: {nombre_}",
               "", "\t\tannotation SummarizationSetBy = User", ""]
    return "\n".join(lineas) + "\n"


def medida(tabla, nombre_, expresion, formato, carpeta, descripcion=None):
    cabeza = f"\t/// {descripcion}\n" if descripcion else ""
    return (f"{cabeza}\tmeasure '{nombre_}' = {expresion}\n\t\tformatString: {formato}\n"
            f"\t\tdisplayFolder: {carpeta}\n\t\tlineageTag: {tag(tabla, 'medida', nombre_)}\n\n")


F = "fact_precio_diario"
MEDIDAS_DETECTOR = [
    ("Ofertas evaluables", f"CALCULATE ( COUNTROWS ( {F} ), NOT ISBLANK ( {F}[descuento_sin_respaldo] ) )", "#,0",
     "Ofertas con existencias, descuento anunciado y al menos 20 días observados en la ventana de 30."),
    ("Descuentos sin respaldo", f"CALCULATE ( COUNTROWS ( {F} ), {F}[descuento_sin_respaldo] = TRUE () )", "#,0",
     "Ofertas cuyo descuento anunciado supera al respaldado en más de 5 puntos porcentuales."),
    ("% sin respaldo", "DIVIDE ( [Descuentos sin respaldo], [Ofertas evaluables] )", "0.0%",
     "Descuentos sin respaldo sobre ofertas evaluables."),
    ("Descuento anunciado (evaluables)",
     f"CALCULATE ( AVERAGE ( {F}[descuento_pct] ), NOT ISBLANK ( {F}[descuento_sin_respaldo] ) )", "0.0%",
     "1 − venta / lista, promedio de las ofertas evaluables."),
    ("Descuento respaldado promedio", f"AVERAGE ( {F}[descuento_respaldado] )", "0.0%",
     "1 − venta / menor precio de los 30 días anteriores, promedio de las ofertas evaluables."),
]


def modelo() -> list[str]:
    hechos = []
    ruta = MODELO / "tables" / f"{F}.tmdl"
    t = ruta.read_text(encoding="utf-8")
    if "column descuento_sin_respaldo" not in t:
        bloque = "".join(medida(F, n, e, fmt, "Detector", d) for n, e, fmt, d in MEDIDAS_DETECTOR)
        bloque += (columna(F, "precio_referencia_30d", "int64", "\\$ #,0")
                   + columna(F, "dias_observados_30d", "int64", "0")
                   + columna(F, "descuento_respaldado", "double", "0.0%")
                   + columna(F, "descuento_sin_respaldo", "boolean"))
        marca = f"\tpartition {F} = m"
        assert marca in t
        ruta.write_text(t.replace(marca, bloque + marca, 1), encoding="utf-8")
        hechos.append("columnas y medidas del detector en fact_precio_diario")

    E = "fact_evento_comercial"
    ruta = MODELO / "tables" / f"{E}.tmdl"
    if not ruta.exists():
        cols = [("fecha_key", "int64", None, True, None), ("tipo_evento", "string", None, False, None),
                ("producto_key", "string", None, True, None), ("tienda_key", "int64", None, True, None),
                ("precio_anterior", "int64", "\\$ #,0", False, None), ("precio_actual", "int64", "\\$ #,0", False, None),
                ("variacion_pct", "double", "0.0%", False, None), ("precio_lista", "int64", "\\$ #,0", False, None),
                ("descuento_anunciado", "double", "0.0%", False, None),
                ("descuento_respaldado", "double", "0.0%", False, None),
                ("precio_referencia_30d", "int64", "\\$ #,0", False, None),
                ("dias_observados_30d", "int64", "0", False, None), ("fecha_anterior_key", "int64", "0", True, None),
                ("dias_desde_anterior", "int64", "0", False, None), ("revisar_atipico", "boolean", None, False, None),
                ("url", "string", None, False, "WebUrl"), ("ruta_bronze", "string", None, True, None)]
        tipos = [("Cambios de precio", "CAMBIO_PRECIO"), ("Agotados", "AGOTADO"), ("Fin de promoción", "FIN_PROMOCION"),
                 ("Productos nuevos", "PRODUCTO_NUEVO"), ("Descuentos sin respaldo nuevos", "DESCUENTO_SIN_RESPALDO")]
        texto = (f"/// Eventos comerciales de las alertas y el resumen diario (src/medallon/eventos.py): tipo × producto × "
                 f"tienda × día.\ntable {E}\n\tlineageTag: {tag(E)}\n\n"
                 + medida(E, "Eventos", f"COUNTROWS ( {E} )", "#,0", "Eventos")
                 + "".join(medida(E, n, f"CALCULATE ( [Eventos], {E}[tipo_evento] = \"{v}\" )", "#,0", "Eventos")
                           for n, v in tipos)
                 + "".join(columna(E, *c) for c in cols)
                 + f"\tpartition {E} = m\n\t\tmode: import\n\t\tsource =\n\t\t\t\tlet\n"
                   f"\t\t\t\t    Origen = Sql.Database(Servidor, BaseDatos),\n"
                   f"\t\t\t\t    Vista = Origen{{[Schema = \"oro\", Item = \"{E}\"]}}[Data]\n"
                   f"\t\t\t\tin\n\t\t\t\t    Vista\n\n\tannotation PBI_ResultType = Table\n\n")
        ruta.write_text(texto, encoding="utf-8")
        rel = MODELO / "relationships.tmdl"
        r = rel.read_text(encoding="utf-8")
        for col, dest in (("fecha_key", "dim_calendario.fecha_key"), ("producto_key", "dim_producto.producto_key"),
                          ("tienda_key", "dim_tienda.tienda_key")):
            r = r.rstrip("\n") + f"\n\nrelationship {tag(E, 'rel', col)}\n\tfromColumn: {E}.{col}\n\ttoColumn: {dest}\n"
        rel.write_text(r, encoding="utf-8")
        mod = MODELO / "model.tmdl"
        m = mod.read_text(encoding="utf-8")
        m = m.replace("ref table kpi_calidad_captura\n", f"ref table kpi_calidad_captura\nref table {E}\n", 1)
        m = m.replace('"kpi_calidad_captura"]', f'"kpi_calidad_captura", "{E}"]', 1)
        mod.write_text(m, encoding="utf-8")
        hechos.append("tabla fact_evento_comercial con 3 relaciones")
    return hechos


# ============================================================================ informe

def leer(pagina, visual):
    return json.loads((PAGINAS / pagina / "visuals" / visual / "visual.json").read_text(encoding="utf-8"))


PLANTILLA = {"encabezado": ("calidad", "a59332c617d757c2ba96"), "fecha": ("calidad", "1b1cb5c5644c5ab2a673"),
             "tienda": ("calidad", "b7039802602d55679cde"), "tarjeta": ("calidad", "746b2fddcedf58a9bf64"),
             "columnas": ("calidad", "2f2a5f87763e57b1a3f9"), "tabla": ("calidad", "2960e41323e85a13ac12")}


def campo(entidad, propiedad, medida_=False, titulo=None, activo=False):
    tipo = "Measure" if medida_ else "Column"
    p = {"field": {tipo: {"Expression": {"SourceRef": {"Entity": entidad}}, "Property": propiedad}},
         "queryRef": f"{entidad}.{propiedad}", "nativeQueryRef": propiedad}
    if titulo:
        p["displayName"] = titulo
    if activo:
        p["active"] = True
    return p


def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def colocar(v, pagina, clave, x, y, w, h, z):
    v["name"] = nombre(pagina, clave)
    v["position"] = {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z}
    return v


def encabezado(pagina, texto):
    v = copy.deepcopy(leer(*PLANTILLA["encabezado"]))
    v["visual"]["objects"]["general"][0]["properties"]["paragraphs"][0]["textRuns"][0]["value"] = texto
    return colocar(v, pagina, "encabezado", 0, 0, 1280, 64, 1000)


def segmentador(pagina, cual, x, w, z):
    return colocar(copy.deepcopy(leer(*PLANTILLA[cual])), pagina, f"seg-{cual}", x, 76, w, 64, z)


def tarjeta(pagina, entidad, medida_, titulo, ayuda, x, w, z):
    v = copy.deepcopy(leer(*PLANTILLA["tarjeta"]))
    v["visual"]["query"]["queryState"]["Values"]["projections"] = [campo(entidad, medida_, True, titulo)]
    o = v["visual"]["visualContainerObjects"]
    o["title"][0]["properties"]["text"] = lit(f"'{titulo}'")
    o["visualHeaderTooltip"][0]["properties"]["text"] = lit("'" + ayuda.replace("'", "''") + "'")
    return colocar(v, pagina, f"tarjeta-{medida_}", x, 152, w, 84, z)


def columnas(pagina, clave, categoria, y_medida, titulo, x, w, z):
    v = copy.deepcopy(leer(*PLANTILLA["columnas"]))
    v["visual"]["query"]["queryState"] = {"Category": {"projections": [campo(*categoria, activo=True)]},
                                          "Y": {"projections": [campo(*y_medida, medida_=True)]}}
    objetos = v["visual"].get("objects", {})
    v["visual"]["objects"] = {k: val for k, val in objetos.items() if k == "labels"}   # sin colores por serie viejos
    v["visual"]["visualContainerObjects"]["title"][0]["properties"]["text"] = lit(f"'{titulo}'")
    return colocar(v, pagina, clave, x, 248, w, 214, z)


def tabla(pagina, proyecciones, titulo, z):
    v = copy.deepcopy(leer(*PLANTILLA["tabla"]))
    v["visual"]["query"]["queryState"] = {"Values": {"projections": proyecciones}}
    v["visual"].pop("objects", None)
    v["visual"]["visualContainerObjects"]["title"][0]["properties"]["text"] = lit(f"'{titulo}'")
    return colocar(v, pagina, "tabla", 24, 474, 1232, 222, z)


def escribir_pagina(pagina, titulo, visuales):
    carpeta = PAGINAS / pagina
    if carpeta.exists():
        return False
    (carpeta / "visuals").mkdir(parents=True)
    (carpeta / "page.json").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json",
        "name": pagina, "displayName": titulo, "displayOption": "FitToPage", "height": 720, "width": 1280},
        ensure_ascii=False, indent=2), encoding="utf-8")
    for v in visuales:
        d = carpeta / "visuals" / v["name"]
        d.mkdir()
        (d / "visual.json").write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def informe() -> list[str]:
    hechos = []
    E = "fact_evento_comercial"
    xs = [24, 231, 438, 645, 852, 1059]
    if escribir_pagina("descuentos", "Descuentos", [
        encabezado("descuentos", "Descuentos sin respaldo en el historial de 30 días"),
        segmentador("descuentos", "fecha", 24, 598, 2000),
        segmentador("descuentos", "tienda", 634, 622, 3000),
        *[tarjeta("descuentos", F, n, t, a, xs[i], 195 if i < 4 else 197, 10000 + i * 1000)
          for i, (n, t, a) in enumerate([
              ("Ofertas evaluables", "Ofertas evaluables", "Con existencias, descuento anunciado y al menos 20 días observados en los 30 anteriores."),
              ("Descuentos sin respaldo", "Sin respaldo", "Descuento anunciado mayor que el respaldado en más de 5 puntos porcentuales."),
              ("% sin respaldo", "% sin respaldo", "Descuentos sin respaldo sobre ofertas evaluables. Es una comparación con el historial observado, no una conclusión sobre la cadena."),
              ("Descuento anunciado (evaluables)", "Anunciado", "Promedio de 1 − venta / lista en las ofertas evaluables."),
              ("Descuento respaldado promedio", "Respaldado", "Promedio de 1 − venta / menor precio de venta con existencias en los 30 días anteriores.")])],
        columnas("descuentos", "por-tienda", ("dim_tienda", "tienda"), (F, "% sin respaldo"),
                 "% sin respaldo por tienda", 24, 604, 20000),
        columnas("descuentos", "por-dia", ("dim_calendario", "fecha"), (F, "Descuentos sin respaldo"),
                 "Descuentos sin respaldo por día", 640, 616, 21000),
        tabla("descuentos", [
            campo("dim_calendario", "fecha", titulo="Fecha"), campo("dim_tienda", "tienda", titulo="Tienda"),
            campo("dim_producto", "marca", titulo="Marca"), campo("dim_producto", "referencia", titulo="Referencia"),
            campo(F, "precio_lista", titulo="Precio de lista"), campo(F, "precio_venta", titulo="Precio de venta"),
            campo(F, "precio_referencia_30d", titulo="Referencia 30 días"),
            campo(F, "descuento_pct", titulo="Anunciado"), campo(F, "descuento_respaldado", titulo="Respaldado"),
            campo(F, "url", titulo="Página"),
            campo(F, "Descuentos sin respaldo", True, "Marcas")],   # la medida deja solo las filas marcadas
            "Ofertas marcadas (solo filas con descuento sin respaldo)", 22000),
    ]):
        hechos.append("página Descuentos")

    tarjetas_ev = [("Eventos", "Eventos", "Todos los eventos del periodo filtrado."),
                   ("Cambios de precio", "Cambios de precio", "Cambio del precio de venta de 10 % o más, con existencias en las dos observaciones."),
                   ("Agotados", "Agotados", "Ofertas que tenían existencias y dejaron de tenerlas."),
                   ("Fin de promoción", "Fin de promoción", "El descuento anunciado desapareció y el precio de venta subió."),
                   ("Productos nuevos", "Nuevos", "Primera observación de la oferta en la tienda, con existencias."),
                   ("Descuentos sin respaldo nuevos", "Sin respaldo (nuevos)", "Ofertas que el detector empezó a marcar ese día.")]
    if escribir_pagina("eventos", "Eventos del día", [
        encabezado("eventos", "Eventos comerciales del día"),
        segmentador("eventos", "fecha", 24, 598, 2000),
        segmentador("eventos", "tienda", 634, 622, 3000),
        *[tarjeta("eventos", E, n, t, a, xs[i], 197 if i == 5 else 195, 10000 + i * 1000)
          for i, (n, t, a) in enumerate(tarjetas_ev)],
        columnas("eventos", "por-tipo", (E, "tipo_evento"), (E, "Eventos"), "Eventos por tipo", 24, 604, 20000),
        columnas("eventos", "por-tienda", ("dim_tienda", "tienda"), (E, "Eventos"), "Eventos por tienda", 640, 616, 21000),
        tabla("eventos", [
            campo("dim_calendario", "fecha", titulo="Fecha"), campo(E, "tipo_evento", titulo="Evento"),
            campo("dim_tienda", "tienda", titulo="Tienda"), campo("dim_producto", "marca", titulo="Marca"),
            campo("dim_producto", "referencia", titulo="Referencia"),
            campo(E, "precio_anterior", titulo="Antes"), campo(E, "precio_actual", titulo="Ahora"),
            campo(E, "variacion_pct", titulo="Variación"), campo(E, "revisar_atipico", titulo="Revisar (atípico)"),
            campo(E, "url", titulo="Página"), campo(E, "Eventos", True, "Eventos")],
            "Detalle de los eventos", 22000),
    ]):
        hechos.append("página Eventos del día")

    ruta = PAGINAS / "pages.json"
    p = json.loads(ruta.read_text(encoding="utf-8"))
    for nueva in ("descuentos", "eventos"):
        if nueva not in p["pageOrder"]:
            p["pageOrder"].append(nueva)
    ruta.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
    return hechos


if __name__ == "__main__":
    hechos = modelo() + informe()
    print("Agregado: " + (", ".join(hechos) if hechos else "nada (ya estaba)"))

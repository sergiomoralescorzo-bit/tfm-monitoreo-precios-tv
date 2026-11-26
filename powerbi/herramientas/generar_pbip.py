"""Genera el proyecto Power BI (PBIP: modelo TMDL + informe PBIR) de la Etapa 5 a partir de una especificación.

Uso (desde la raíz del proyecto):
    python powerbi/herramientas/generar_pbip.py powerbi
    python powerbi/herramientas/validar_pbir.py powerbi     # valida los JSON contra los esquemas de Microsoft (requiere jsonschema)

ATENCIÓN: borra y vuelve a crear TFM_Precios.SemanticModel y TFM_Precios.Report. Sirve para el andamiaje inicial
(16-oct-2026); si el equipo ya editó el informe en Power BI Desktop, esos cambios se pierden. Después de editar en
Desktop, la fuente de verdad son los archivos del PBIP, no este script.
"""
import json
import shutil
import sys
import uuid
from pathlib import Path

NOMBRE = "TFM_Precios"
NS = uuid.UUID("6f1c2d9e-3b7a-4c55-9e0d-1a2b3c4d5e6f")
ESQ = "https://developer.microsoft.com/json-schemas/fabric"


def tag(*partes: str) -> str:
    return str(uuid.uuid5(NS, "/".join(partes)))


# ----------------------------------------------------------------------------- modelo
# (columna, tipo, opciones) — tipos TMDL: string, int64, double, boolean, dateTime
TABLAS = {
    "dim_producto": [
        ("producto_key", "string", {"oculta": 1}), ("gtin14", "string", {}), ("descripcion", "string", {}),
        ("marca", "string", {}), ("pulgadas", "int64", {"resumen": "none"}), ("rango_pulgadas", "string", {}),
        ("referencia", "string", {}), ("tecnologia", "string", {}), ("resolucion", "string", {}),
        ("en_maestro", "boolean", {}), ("origen_atributos", "string", {}), ("tiene_gtin", "boolean", {}),
    ],
    "dim_tienda": [
        ("tienda_key", "int64", {"oculta": 1}), ("sitio", "string", {}), ("tienda", "string", {}), ("cadena", "string", {}),
    ],
    "dim_calendario": [
        ("fecha_key", "int64", {"oculta": 1}), ("fecha", "dateTime", {"fecha": 1, "clave": 1}),
        ("anio", "int64", {"resumen": "none"}), ("mes", "int64", {"resumen": "none", "oculta": 1}),
        ("nombre_mes", "string", {"orden": "mes"}), ("anio_mes", "string", {}),
        ("semana_iso", "int64", {"resumen": "none"}), ("inicio_semana", "dateTime", {"fecha": 1}),
        ("dia_semana", "int64", {"resumen": "none", "oculta": 1}), ("nombre_dia", "string", {"orden": "dia_semana"}),
        ("es_fin_de_semana", "boolean", {}),
    ],
    "fact_precio_diario": [
        ("fecha_key", "int64", {"oculta": 1}), ("producto_key", "string", {"oculta": 1}), ("tienda_key", "int64", {"oculta": 1}),
        ("precio_lista", "int64", {"resumen": "none", "formato": "\\$ #,0"}),
        ("precio_venta", "int64", {"resumen": "none", "formato": "\\$ #,0"}),
        ("descuento_pct", "double", {"resumen": "none", "formato": "0.0%"}),
        ("disponible", "boolean", {}), ("stock", "int64", {"resumen": "none"}),
        ("metodo_emparejamiento", "string", {}), ("fecha_captura_utc", "dateTime", {"formato": "General Date"}),
        ("id_ejecucion", "string", {}), ("ruta_bronze", "string", {}), ("url", "string", {"categoria": "WebUrl"}),
        ("motivos_atipico", "string", {}),
    ],
    "fact_ejecucion": [
        ("fecha_key", "int64", {"oculta": 1}), ("tienda_key", "int64", {"oculta": 1}), ("id_ejecucion", "string", {}),
        ("modo", "string", {}), ("inicio", "dateTime", {"formato": "General Date"}), ("fin", "dateTime", {"formato": "General Date"}),
        ("duracion_s", "double", {"resumen": "none", "formato": "#,0"}),
        ("descubiertos", "int64", {}), ("consultados", "int64", {}), ("ok", "int64", {}), ("sin_stock", "int64", {}),
        ("no_encontrados", "int64", {}), ("errores", "int64", {}), ("bloqueados", "int64", {}), ("registros", "int64", {}),
        ("en_alcance", "int64", {}), ("estado", "string", {}), ("mensaje", "string", {}),
    ],
    "kpi_brecha_precio": [
        ("fecha_key", "int64", {"oculta": 1}), ("producto_key", "string", {"oculta": 1}), ("n_cadenas", "int64", {"resumen": "none"}),
        ("precio_min", "int64", {"resumen": "none", "formato": "\\$ #,0"}), ("precio_max", "int64", {"resumen": "none", "formato": "\\$ #,0"}),
        ("precio_promedio", "int64", {"resumen": "none", "formato": "\\$ #,0"}), ("cadena_mas_barata", "string", {}),
        ("brecha_abs", "int64", {"resumen": "none", "formato": "\\$ #,0"}), ("brecha_pct", "double", {"resumen": "none", "formato": "0.0%"}),
    ],
    "kpi_calidad_captura": [
        ("fecha_key", "int64", {"oculta": 1}), ("tienda_key", "int64", {"oculta": 1}), ("id_ejecucion", "string", {}),
        ("registros", "int64", {}), ("registros_con_datos", "int64", {}), ("tv_en_alcance", "int64", {}),
        ("completitud_pct", "double", {"resumen": "none", "formato": "0.0%"}), ("ofertas_con_stock", "int64", {}),
        ("por_ean", "int64", {}), ("por_referencia", "int64", {}), ("sin_emparejar", "int64", {}), ("emparejadas", "int64", {}),
        ("emparejamiento_pct", "double", {"resumen": "none", "formato": "0.0%"}),
    ],
}

DESCRIPCIONES = {
    "dim_producto": "Televisores: GTIN-14 o sitio:sku si no se emparejó, con atributos del maestro o de la tienda.",
    "dim_tienda": "Sitios capturados y su cadena (Alkosto y Ktronix son la misma cadena).",
    "dim_calendario": "Días con datos, del primero al último.",
    "fact_precio_diario": "Producto × tienda × día, con la última captura del día (RF-06). Trazable hasta bronce (ruta_bronze).",
    "fact_ejecucion": "Una fila por corrida y sitio (RF-07).",
    "kpi_brecha_precio": "Producto × día con al menos 2 cadenas y stock: mínimo, máximo y brecha entre cadenas.",
    "kpi_calidad_captura": "Tienda × día (última corrida): completitud y emparejamiento (Etapa 1, sección 10).",
}

# (tabla, nombre, carpeta, formato, expresión DAX)
MEDIDAS = [
    ("fact_precio_diario", "Ofertas", "Precios", "#,0", "COUNTROWS ( fact_precio_diario )"),
    ("fact_precio_diario", "Productos", "Precios", "#,0", "DISTINCTCOUNT ( fact_precio_diario[producto_key] )"),
    ("fact_precio_diario", "Precio mínimo", "Precios", "\\$ #,0",
     "CALCULATE ( MIN ( fact_precio_diario[precio_venta] ), fact_precio_diario[disponible] = TRUE () )"),
    ("fact_precio_diario", "Precio promedio", "Precios", "\\$ #,0",
     "CALCULATE ( AVERAGE ( fact_precio_diario[precio_venta] ), fact_precio_diario[disponible] = TRUE () )"),
    ("fact_precio_diario", "Precio máximo", "Precios", "\\$ #,0",
     "CALCULATE ( MAX ( fact_precio_diario[precio_venta] ), fact_precio_diario[disponible] = TRUE () )"),
    ("fact_precio_diario", "Descuento promedio", "Precios", "0.0%", "AVERAGE ( fact_precio_diario[descuento_pct] )"),
    ("fact_precio_diario", "Última fecha con precio", "Precios", "0",
     "CALCULATE ( MAX ( fact_precio_diario[fecha_key] ), ALLSELECTED ( dim_calendario ), fact_precio_diario[disponible] = TRUE () )"),
    ("fact_precio_diario", "Precio mínimo último día", "Precios", "\\$ #,0",
     "VAR _fecha = [Última fecha con precio]\nRETURN\n    CALCULATE ( [Precio mínimo], dim_calendario[fecha_key] = _fecha )"),
    ("fact_precio_diario", "Tienda más barata", "Precios", None,
     "VAR _fecha = [Última fecha con precio]\nVAR _precio = [Precio mínimo último día]\nRETURN\n"
     "    IF (\n        NOT ISBLANK ( _precio ),\n        CONCATENATEX (\n            FILTER (\n"
     "                VALUES ( dim_tienda[tienda] ),\n                CALCULATE (\n"
     "                    COUNTROWS ( fact_precio_diario ),\n                    dim_calendario[fecha_key] = _fecha,\n"
     "                    fact_precio_diario[precio_venta] = _precio,\n"
     "                    fact_precio_diario[disponible] = TRUE ()\n                ) > 0\n            ),\n"
     "            dim_tienda[tienda],\n            \", \",\n            dim_tienda[tienda], ASC\n        )\n    )"),
    ("fact_precio_diario", "Tiendas con oferta", "Precios", "#,0",
     "CALCULATE ( DISTINCTCOUNT ( fact_precio_diario[tienda_key] ), fact_precio_diario[disponible] = TRUE () )"),
    ("kpi_brecha_precio", "Productos comparados", "Brecha entre cadenas", "#,0",
     "DISTINCTCOUNT ( kpi_brecha_precio[producto_key] )"),
    ("kpi_brecha_precio", "Brecha promedio %", "Brecha entre cadenas", "0.0%", "AVERAGE ( kpi_brecha_precio[brecha_pct] )"),
    ("kpi_brecha_precio", "Brecha máxima %", "Brecha entre cadenas", "0.0%", "MAX ( kpi_brecha_precio[brecha_pct] )"),
    ("kpi_brecha_precio", "Brecha último día %", "Brecha entre cadenas", "0.0%",
     "VAR _fecha = [Última fecha con precio]\nRETURN\n"
     "    CALCULATE ( MAX ( kpi_brecha_precio[brecha_pct] ), dim_calendario[fecha_key] = _fecha )"),
    ("kpi_brecha_precio", "Brecha promedio $", "Brecha entre cadenas", "\\$ #,0", "AVERAGE ( kpi_brecha_precio[brecha_abs] )"),
    ("kpi_brecha_precio", "Veces más barata", "Brecha entre cadenas", "#,0", "COUNTROWS ( kpi_brecha_precio )"),
    ("kpi_calidad_captura", "Emparejamiento %", "Calidad", "0.0%",
     "DIVIDE ( SUM ( kpi_calidad_captura[emparejadas] ), SUM ( kpi_calidad_captura[ofertas_con_stock] ) )"),
    ("kpi_calidad_captura", "Completitud %", "Calidad", "0.0%",
     "DIVIDE (\n    SUMX ( kpi_calidad_captura, kpi_calidad_captura[completitud_pct] * kpi_calidad_captura[registros_con_datos] ),\n"
     "    SUM ( kpi_calidad_captura[registros_con_datos] )\n)"),
    ("kpi_calidad_captura", "Registros capturados", "Calidad", "#,0", "SUM ( kpi_calidad_captura[registros] )"),
    ("fact_precio_diario", "Precios atípicos", "Calidad", "#,0",
     "CALCULATE ( COUNTROWS ( fact_precio_diario ), NOT ISBLANK ( fact_precio_diario[motivos_atipico] ) )"),
    ("fact_ejecucion", "Ejecuciones", "Ejecuciones", "#,0", "COUNTROWS ( fact_ejecucion )"),
    ("fact_ejecucion", "Ejecuciones fallidas", "Ejecuciones", "#,0",
     "CALCULATE ( COUNTROWS ( fact_ejecucion ), fact_ejecucion[estado] = \"FALLIDA\" )"),
    ("fact_ejecucion", "Tasa de éxito", "Ejecuciones", "0.0%",
     "DIVIDE ( CALCULATE ( COUNTROWS ( fact_ejecucion ), fact_ejecucion[estado] = \"EXITOSA\" ), COUNTROWS ( fact_ejecucion ) )"),
    ("fact_ejecucion", "Duración promedio (min)", "Ejecuciones", "#,0.0", "AVERAGE ( fact_ejecucion[duracion_s] ) / 60"),
]

RELACIONES = [
    ("fact_precio_diario", "fecha_key", "dim_calendario"), ("fact_precio_diario", "producto_key", "dim_producto"),
    ("fact_precio_diario", "tienda_key", "dim_tienda"), ("fact_ejecucion", "fecha_key", "dim_calendario"),
    ("fact_ejecucion", "tienda_key", "dim_tienda"), ("kpi_brecha_precio", "fecha_key", "dim_calendario"),
    ("kpi_brecha_precio", "producto_key", "dim_producto"), ("kpi_calidad_captura", "fecha_key", "dim_calendario"),
    ("kpi_calidad_captura", "tienda_key", "dim_tienda"),
]


def nombre_tmdl(n: str) -> str:
    return n if n.replace("_", "").isalnum() and n.isascii() else "'" + n.replace("'", "''") + "'"


def tabla_tmdl(tabla: str) -> str:
    l = [f"/// {DESCRIPCIONES[tabla]}", f"table {tabla}", f"\tlineageTag: {tag(tabla)}"]
    if tabla == "dim_calendario":
        l.append("\tdataCategory: Time")
    l.append("")
    for nombre, carpeta_medida in [(m[1], m) for m in MEDIDAS if m[0] == tabla]:
        _, _, carpeta, formato, dax = carpeta_medida
        lineas = dax.split("\n")
        if len(lineas) == 1:
            l.append(f"\tmeasure {nombre_tmdl(nombre)} = {dax}")
        else:
            l.append(f"\tmeasure {nombre_tmdl(nombre)} =")
            l += [f"\t\t\t{x}" for x in lineas]
        if formato:
            l.append(f"\t\tformatString: {formato}")
        l.append(f"\t\tdisplayFolder: {carpeta}")
        l.append(f"\t\tlineageTag: {tag(tabla, 'medida', nombre)}")
        l.append("")
    for col, tipo, op in TABLAS[tabla]:
        l.append(f"\tcolumn {col}")
        l.append(f"\t\tdataType: {tipo}")
        if op.get("clave"):
            l.append("\t\tisKey")
        if op.get("fecha"):
            l.append("\t\tformatString: Short Date")
        elif op.get("formato"):
            l.append(f"\t\tformatString: {op['formato']}")
        elif tipo == "int64":
            l.append("\t\tformatString: 0")
        if op.get("oculta"):
            l.append("\t\tisHidden")
        if op.get("categoria"):
            l.append(f"\t\tdataCategory: {op['categoria']}")
        l.append(f"\t\tlineageTag: {tag(tabla, col)}")
        resumen = op.get("resumen", "none" if tipo != "int64" and tipo != "double" else "sum")
        if op.get("oculta"):
            resumen = "none"
        l.append(f"\t\tsummarizeBy: {resumen}")
        l.append(f"\t\tsourceColumn: {col}")
        if op.get("orden"):
            l.append(f"\t\tsortByColumn: {op['orden']}")
        l.append("")
        if op.get("fecha"):
            l.append("\t\tannotation UnderlyingDateTimeDataType = Date")
            l.append("")
        l.append("\t\tannotation SummarizationSetBy = User")
        l.append("")
    l += [
        f"\tpartition {tabla} = m",
        "\t\tmode: import",
        "\t\tsource =",
        "\t\t\t\tlet",
        "\t\t\t\t    Origen = Sql.Database(Servidor, BaseDatos),",
        f"\t\t\t\t    Vista = Origen{{[Schema = \"oro\", Item = \"{tabla}\"]}}[Data]",
        "\t\t\t\tin",
        "\t\t\t\t    Vista",
        "",
        "\tannotation PBI_ResultType = Table",
        "",
    ]
    return "\n".join(l)


def escribir(ruta: Path, texto: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8", newline="\n")


def json_a(ruta: Path, datos: dict) -> None:
    escribir(ruta, json.dumps(datos, ensure_ascii=False, indent=2) + "\n")


def modelo(base: Path) -> None:
    sm = base / f"{NOMBRE}.SemanticModel"
    json_a(sm / "definition.pbism", {"$schema": f"{ESQ}/item/semanticModel/definitionProperties/1.0.0/schema.json",
                                     "version": "4.2", "settings": {}})
    d = sm / "definition"
    escribir(d / "database.tmdl", "database\n\tcompatibilityLevel: 1601\n\n")
    orden = ["Servidor", "BaseDatos", *TABLAS]
    escribir(d / "model.tmdl", "\n".join([
        "model Model",
        "\tculture: es-CO",
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tsourceQueryCulture: es-CO",
        "\tdataAccessOptions",
        "\t\tlegacyRedirects",
        "\t\treturnErrorValuesAsNull",
        "",
        f"annotation PBI_QueryOrder = {json.dumps(orden)}",
        "",
        "annotation __PBI_TimeIntelligenceEnabled = 0",
        "",
        *[f"ref table {t}" for t in TABLAS],
        "",
    ]))
    escribir(d / "expressions.tmdl", "\n".join([
        "/// Endpoint de Synapse SQL serverless (Etapa 4).",
        'expression Servidor = "syn-tfm-webscraping-ondemand.sql.azuresynapse.net" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]',
        f"\tlineageTag: {tag('Servidor')}",
        "",
        "\tannotation PBI_ResultType = Text",
        "",
        "/// Base de datos con las vistas del modelo estrella (esquema oro).",
        'expression BaseDatos = "tfm_oro" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]',
        f"\tlineageTag: {tag('BaseDatos')}",
        "",
        "\tannotation PBI_ResultType = Text",
        "",
    ]))
    for t in TABLAS:
        escribir(d / "tables" / f"{t}.tmdl", tabla_tmdl(t))
    rel = []
    for desde, col, hacia in RELACIONES:
        rel += [f"relationship {tag('rel', desde, col)}", f"\tfromColumn: {desde}.{col}", f"\ttoColumn: {hacia}.{col}", ""]
    escribir(d / "relationships.tmdl", "\n".join(rel))


# ----------------------------------------------------------------------------- informe
def campo(ref: str) -> dict:
    """'tabla.columna' o 'tabla.[Medida]' -> proyección PBIR."""
    tabla, prop = ref.split(".", 1)
    if prop.startswith("["):
        nombre = prop[1:-1]
        return {"field": {"Measure": {"Expression": {"SourceRef": {"Entity": tabla}}, "Property": nombre}},
                "queryRef": f"{tabla}.{nombre}", "nativeQueryRef": nombre}
    return {"field": {"Column": {"Expression": {"SourceRef": {"Entity": tabla}}, "Property": prop}},
            "queryRef": f"{tabla}.{prop}", "nativeQueryRef": prop}


def lit(v) -> dict:
    if isinstance(v, bool):
        return {"expr": {"Literal": {"Value": "true" if v else "false"}}}
    if isinstance(v, (int, float)):
        return {"expr": {"Literal": {"Value": f"{v}D"}}}
    return {"expr": {"Literal": {"Value": "'" + str(v).replace("'", "''") + "'"}}}


def visual(pagina: str, i: int, tipo: str, pos: tuple, roles: dict, titulo: str | None = None,
           objetos: dict | None = None, orden: tuple | None = None) -> tuple[str, dict]:
    x, y, w, h = pos
    nombre = tag(pagina, str(i)).replace("-", "")[:20]
    v = {"visualType": tipo, "drillFilterOtherVisuals": True}
    if roles:
        v["query"] = {"queryState": {r: {"projections": [campo(c) for c in cs]} for r, cs in roles.items()}}
        if orden:
            ref, direccion = orden
            p = campo(ref)["field"]
            v["query"]["sortDefinition"] = {"sort": [{"field": p, "direction": direccion}], "isDefaultSort": False}
    if objetos:
        v["objects"] = objetos
    if titulo:
        v["visualContainerObjects"] = {"title": [{"properties": {"show": lit(True), "text": lit(titulo)}}]}
    return nombre, {"$schema": f"{ESQ}/item/report/definition/visualContainer/2.7.0/schema.json", "name": nombre,
                    "position": {"x": x, "y": y, "z": i * 1000, "height": h, "width": w, "tabOrder": i * 1000},
                    "visual": v}


def texto(pagina: str, i: int, pos: tuple, titulo: str, subtitulo: str) -> tuple[str, dict]:
    parrafos = [{"textRuns": [{"value": titulo, "textStyle": {"fontWeight": "bold", "fontSize": "18pt"}}]},
                {"textRuns": [{"value": subtitulo, "textStyle": {"fontSize": "10pt", "color": "#605E5C"}}]}]
    return visual(pagina, i, "textbox", pos, {}, objetos={"general": [{"properties": {"paragraphs": parrafos}}]})


def segmentador(pagina, i, pos, ref, titulo, modo="Dropdown"):
    return visual(pagina, i, "slicer", pos, {"Values": [ref]}, titulo,
                  objetos={"data": [{"properties": {"mode": lit(modo)}}]})


FILTROS = [("dim_calendario.fecha", "Fecha", "Between"), ("dim_producto.marca", "Marca", "Dropdown"),
           ("dim_producto.rango_pulgadas", "Pulgadas", "Dropdown"), ("dim_producto.tecnologia", "Tecnología", "Dropdown")]


def filtros(pagina: str, inicio: int, y: int = 80, tienda: bool = True) -> list:
    lista = FILTROS + ([("dim_tienda.tienda", "Tienda", "Dropdown")] if tienda else [])
    ancho = (1280 - 40 - 10 * (len(lista) - 1)) // len(lista)
    return [segmentador(pagina, inicio + k, (20 + k * (ancho + 10), y, ancho, 64), ref, t, modo)
            for k, (ref, t, modo) in enumerate(lista)]


def tarjetas(pagina: str, inicio: int, medidas: list, y: int = 160) -> list:
    ancho = (1280 - 40 - 10 * (len(medidas) - 1)) // len(medidas)
    return [visual(pagina, inicio + k, "card", (20 + k * (ancho + 10), y, ancho, 100), {"Values": [m]}, t)
            for k, (m, t) in enumerate(medidas)]


PAGINAS = [
    ("resumen", "Resumen de precios", lambda p: [
        texto(p, 1, (20, 10, 1240, 60), "Precios de televisores en 4 cadenas colombianas",
              "Alkosto, Ktronix, Jumbo, Olímpica y Éxito · última captura de cada día · fuente: Synapse SQL serverless (tfm_oro)"),
        *filtros(p, 2),
        *tarjetas(p, 10, [("fact_precio_diario.[Productos]", "Productos con precio"),
                          ("fact_precio_diario.[Ofertas]", "Ofertas"),
                          ("fact_precio_diario.[Precio promedio]", "Precio promedio"),
                          ("kpi_brecha_precio.[Brecha promedio %]", "Brecha promedio entre cadenas"),
                          ("kpi_calidad_captura.[Emparejamiento %]", "Emparejamiento")]),
        visual(p, 20, "tableEx", (20, 270, 1240, 440),
               {"Values": ["dim_producto.descripcion", "dim_producto.marca", "dim_producto.pulgadas",
                           "dim_producto.tecnologia", "fact_precio_diario.[Precio mínimo último día]",
                           "fact_precio_diario.[Tienda más barata]", "fact_precio_diario.[Tiendas con oferta]",
                           "kpi_brecha_precio.[Brecha último día %]"]},
               "Menor precio por producto (último día con precio en el periodo)",
               orden=("fact_precio_diario.[Tiendas con oferta]", "Descending")),
    ]),
    ("brecha", "Brecha entre cadenas", lambda p: [
        texto(p, 1, (20, 10, 1240, 60), "Brecha de precio entre cadenas",
              "Productos con GTIN vendidos por al menos 2 cadenas el mismo día, con stock · brecha = (máximo − mínimo) / mínimo"),
        *filtros(p, 2, tienda=False),
        *tarjetas(p, 10, [("kpi_brecha_precio.[Productos comparados]", "Productos comparados"),
                          ("kpi_brecha_precio.[Brecha promedio %]", "Brecha promedio"),
                          ("kpi_brecha_precio.[Brecha máxima %]", "Brecha máxima"),
                          ("kpi_brecha_precio.[Brecha promedio $]", "Diferencia promedio (COP)")]),
        visual(p, 20, "clusteredBarChart", (20, 270, 410, 440),
               {"Category": ["dim_producto.marca"], "Y": ["kpi_brecha_precio.[Brecha promedio %]"]},
               "Brecha promedio por marca", orden=("kpi_brecha_precio.[Brecha promedio %]", "Descending")),
        visual(p, 21, "clusteredColumnChart", (440, 270, 400, 210),
               {"Category": ["dim_producto.rango_pulgadas"], "Y": ["kpi_brecha_precio.[Brecha promedio %]"]},
               "Brecha promedio por tamaño"),
        visual(p, 22, "donutChart", (440, 490, 400, 220),
               {"Category": ["kpi_brecha_precio.cadena_mas_barata"], "Y": ["kpi_brecha_precio.[Veces más barata]"]},
               "Cadena con el menor precio (producto × día)"),
        visual(p, 23, "tableEx", (850, 270, 410, 440),
               {"Values": ["dim_producto.descripcion", "kpi_brecha_precio.[Brecha máxima %]",
                           "kpi_brecha_precio.[Brecha promedio $]"]},
               "Productos con mayor brecha", orden=("kpi_brecha_precio.[Brecha máxima %]", "Descending")),
    ]),
    ("evolucion", "Evolución diaria", lambda p: [
        texto(p, 1, (20, 10, 1240, 60), "Evolución diaria de precios",
              "Precio de venta con stock · una línea por tienda · use los filtros para seguir una marca, un tamaño o un producto"),
        *filtros(p, 2),
        segmentador(p, 8, (20, 150, 1240, 64), "dim_producto.descripcion", "Producto"),
        visual(p, 20, "lineChart", (20, 225, 830, 485),
               {"Category": ["dim_calendario.fecha"], "Y": ["fact_precio_diario.[Precio promedio]"],
                "Series": ["dim_tienda.tienda"]},
               "Precio promedio por tienda"),
        visual(p, 21, "lineChart", (860, 225, 400, 240),
               {"Category": ["dim_calendario.fecha"], "Y": ["kpi_brecha_precio.[Brecha promedio %]"]},
               "Brecha promedio entre cadenas"),
        visual(p, 22, "lineChart", (860, 475, 400, 235),
               {"Category": ["dim_calendario.fecha"], "Y": ["fact_precio_diario.[Productos]"],
                "Series": ["dim_tienda.tienda"]},
               "Productos con precio por tienda"),
    ]),
    ("calidad", "Calidad de la captura", lambda p: [
        texto(p, 1, (20, 10, 1240, 60), "Calidad de la captura",
              "Métricas de validación de la Etapa 1 (sección 10): completitud ≥ 90 %, emparejamiento ≥ 80 %, ejecución < 60 min"),
        segmentador(p, 2, (20, 80, 400, 64), "dim_calendario.fecha", "Fecha", "Between"),
        segmentador(p, 3, (430, 80, 300, 64), "dim_tienda.tienda", "Tienda"),
        *tarjetas(p, 10, [("kpi_calidad_captura.[Completitud %]", "Completitud"),
                          ("kpi_calidad_captura.[Emparejamiento %]", "Emparejamiento"),
                          ("fact_ejecucion.[Tasa de éxito]", "Ejecuciones exitosas"),
                          ("fact_ejecucion.[Duración promedio (min)]", "Duración promedio (min)"),
                          ("fact_ejecucion.[Ejecuciones fallidas]", "Ejecuciones fallidas"),
                          ("fact_precio_diario.[Precios atípicos]", "Precios atípicos")]),
        visual(p, 20, "clusteredColumnChart", (20, 270, 610, 210),
               {"Category": ["dim_tienda.tienda"], "Y": ["kpi_calidad_captura.[Emparejamiento %]",
                                                         "kpi_calidad_captura.[Completitud %]"]},
               "Emparejamiento y completitud por tienda"),
        visual(p, 21, "clusteredColumnChart", (640, 270, 620, 210),
               {"Category": ["dim_calendario.fecha"], "Y": ["kpi_calidad_captura.[Registros capturados]"],
                "Series": ["dim_tienda.tienda"]},
               "Registros capturados por día"),
        visual(p, 22, "tableEx", (20, 490, 1240, 220),
               {"Values": ["dim_calendario.fecha", "dim_tienda.tienda", "fact_ejecucion.id_ejecucion",
                           "fact_ejecucion.modo", "fact_ejecucion.estado", "fact_ejecucion.duracion_s",
                           "fact_ejecucion.registros", "fact_ejecucion.ok", "fact_ejecucion.sin_stock",
                           "fact_ejecucion.errores", "fact_ejecucion.bloqueados"]},
               "Ejecuciones (RF-07)"),
    ]),
]


def informe(base: Path) -> None:
    rp = base / f"{NOMBRE}.Report"
    json_a(rp / "definition.pbir", {"$schema": f"{ESQ}/item/report/definitionProperties/2.0.0/schema.json",
                                    "version": "4.0",
                                    "datasetReference": {"byPath": {"path": f"../{NOMBRE}.SemanticModel"}}})
    d = rp / "definition"
    json_a(d / "version.json", {"$schema": f"{ESQ}/item/report/definition/versionMetadata/1.0.0/schema.json",
                                "version": "2.0.0"})
    json_a(d / "report.json", {"$schema": f"{ESQ}/item/report/definition/report/3.2.0/schema.json",
                               "themeCollection": {}, "settings": {"useStylableVisualContainerHeader": True,
                                                                   "exportDataMode": "AllowSummarized"}})
    json_a(d / "pages" / "pages.json", {"$schema": f"{ESQ}/item/report/definition/pagesMetadata/1.0.0/schema.json",
                                        "pageOrder": [p[0] for p in PAGINAS], "activePageName": PAGINAS[0][0]})
    for nombre, titulo, contenido in PAGINAS:
        pd = d / "pages" / nombre
        json_a(pd / "page.json", {"$schema": f"{ESQ}/item/report/definition/page/2.1.0/schema.json", "name": nombre,
                                  "displayName": titulo, "displayOption": "FitToPage", "height": 720, "width": 1280})
        for vn, vj in contenido(nombre):
            json_a(pd / "visuals" / vn / "visual.json", vj)


def main() -> None:
    base = Path(sys.argv[1])
    for sub in (f"{NOMBRE}.SemanticModel", f"{NOMBRE}.Report"):
        shutil.rmtree(base / sub, ignore_errors=True)
    json_a(base / f"{NOMBRE}.pbip", {"$schema": f"{ESQ}/pbip/pbipProperties/1.0.0/schema.json", "version": "1.0",
                                     "artifacts": [{"report": {"path": f"{NOMBRE}.Report"}}],
                                     "settings": {"enableAutoRecovery": True}})
    escribir(base / ".gitignore", "**/.pbi/localSettings.json\n**/.pbi/cache.abf\nherramientas/.cache_esquemas/\n")
    modelo(base)
    informe(base)
    print("Generado en", base)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Rediseño visual del informe TFM_Precios (20-oct-2026): tema propio, página de inicio, menú superior
persistente, cuadrícula común, colores fijos por tienda, filtros sincronizados y ayudas en los indicadores.

Trabaja sobre los archivos PBIR existentes (no regenera el informe) y es idempotente: puede ejecutarse de nuevo.
Uso:  .venv/Scripts/python powerbi/herramientas/redisenar_informe.py
Después: Power BI Desktop → aplicar cambios externos (o volver a abrir el .pbip).
"""
import hashlib
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1] / "TFM_Precios.Report"
PAGINAS = RAIZ / "definition" / "pages"
ESQ_VISUAL = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.7.0/schema.json"
ESQ_PAGINA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json"
TEMA = "TFM_Tema.json"

# ------------------------------------------------------------------ paleta (provisional, sin marca principal)
C = {
    "marino": "#14365D", "marino_hover": "#1F4A7A", "secundario": "#4A6B8A", "secundario_claro": "#9FB4C9",
    "fondo": "#F4F6F9", "superficie": "#FFFFFF", "borde": "#E1E6ED", "texto": "#1B2A3A", "texto_2": "#5B6B7C",
    "menu_texto": "#C9D6E8", "enlace": "#1F5AA6",
    "ok": "#1E7B34", "alerta": "#B54708", "error": "#B42318", "sin_datos": "#8A94A3",
}
TIENDAS = {"Alkosto": "#1F5AA6", "Ktronix": "#5FA8E8", "Jumbo": "#7A4FB5", "Olímpica": "#C2367A", "Éxito": "#E0A100"}
CADENAS = {"Colombiana de Comercio (Alkosto/Ktronix)": "#1F5AA6", "Cencosud (Jumbo)": "#7A4FB5",
           "Olímpica": "#C2367A", "Grupo Éxito": "#E0A100"}

# ------------------------------------------------------------------ cuadrícula 1280 × 720
M = 24                      # margen
ENC = (0, 64)               # banda de encabezado (y, alto)
FIL = (76, 64)              # fila de filtros
KPI = (152, 84)             # fila de indicadores
CONT = 248                  # inicio del contenido
FONDO_Y = 696               # borde inferior del contenido
ANCHO = 1280
BOTON_RESET = (1106, 88, 150, 40)

# Botones de menú escritos a mano: Power BI Desktop 2.159 los mostró vacíos (20-oct), así que se desactivan.
# La navegación persistente se hará con el navegador de páginas nativo, creado en Desktop.
MENU_BOTONES = False
MENU = [("inicio", "Inicio"), ("resumen", "Vista general"), ("brecha", "Brechas"),
        ("evolucion", "Evolución"), ("calidad", "Calidad")]
TITULOS = {"inicio": "Monitoreo de precios de televisores", "resumen": "Vista general",
           "brecha": "Brecha entre cadenas", "evolucion": "Evolución diaria", "calidad": "Calidad de la captura"}

AYUDAS = {  # tooltips de los indicadores (por texto de la tarjeta)
    "Productos": "Televisores distintos con precio en el periodo y con los filtros seleccionados.",
    "Registros": "Filas de precio diario: una por producto, tienda y día (la última captura del día).",
    "Precio más bajo": "Menor precio de venta con stock en el periodo y con los filtros seleccionados, en pesos colombianos.",
    "Brecha promedio": "Promedio de (precio más alto − precio más bajo) / precio más bajo, por producto y día, "
                       "entre cadenas que venden el mismo televisor con stock.",
    "Emparejamiento": "Porcentaje de ofertas con stock identificadas como un producto del maestro de televisores "
                      "(por EAN o por referencia). Meta: 80 %.",
    "Productos comparados": "Televisores vendidos con stock por al menos 2 cadenas el mismo día.",
    "Diferencia promedio (COP)": "Diferencia promedio en pesos entre la cadena más cara y la más barata, "
                                 "para el mismo televisor y día.",
    "Brecha máxima": "Mayor brecha porcentual observada en un producto y día del periodo.",
    "Ejecuciones exitosas": "Porcentaje de capturas por tienda que terminaron en EXITOSA.",
    "Completitud": "Porcentaje de registros con precio, título y EAN o SKU. Meta: 90 %.",
    "Precios atípicos": "Precios marcados por los controles de calidad (descuento excesivo, cambio brusco, "
                        "fuera de rango…). 0 = ninguno; en blanco = sin datos.",
    "Ejecuciones fallidas": "Capturas por tienda que no obtuvieron ningún precio. 0 = ninguna falló; "
                            "en blanco = sin ejecuciones en el periodo.",
    "Duración promedio (min)": "Tiempo promedio de la captura de cada tienda, en minutos.",
}

TITULOS_VISUALES = {  # títulos más cortos y directos
    "Cadena con el menor precio (producto × día)": "Cadena con el menor precio",
    "Brecha promedio entre cadenas": "Brecha promedio por día",
    "Ejecuciones (RF-07)": "Detalle de ejecuciones",
}
COLUMNAS_EJECUCIONES = {
    "dim_calendario.fecha": "Fecha", "dim_tienda.tienda": "Tienda", "fact_ejecucion.id_ejecucion": "Ejecución",
    "fact_ejecucion.modo": "Modo", "fact_ejecucion.estado": "Estado", "fact_ejecucion.duracion_s": "Duración (s)",
    "fact_ejecucion.registros": "Registros", "fact_ejecucion.ok": "OK", "fact_ejecucion.sin_stock": "Sin stock",
    "fact_ejecucion.errores": "Errores", "fact_ejecucion.bloqueados": "Bloqueos",
}


# ------------------------------------------------------------------ utilidades
def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def txt(s):
    return lit("'" + s.replace("'", "''") + "'")


def color(c):
    return {"solid": {"color": lit(f"'{c}'")}}


def nombre(*partes):
    return hashlib.sha1("|".join(partes).encode()).hexdigest()[:20]


def leer(f):
    return json.loads(f.read_text(encoding="utf-8"))


def escribir(f, d):
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def contenedor(nombre_v, x, y, w, h, z, visual):
    return {"$schema": ESQ_VISUAL, "name": nombre_v,
            "position": {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z}, "visual": visual}


def parrafo(texto, tam, color_t, negrita=False, alinear="left", fuente="Segoe UI"):
    estilo = {"fontSize": f"{tam}pt", "color": color_t, "fontFamily": fuente}
    if negrita:
        estilo["fontWeight"] = "bold"
    return {"textRuns": [{"value": texto, "textStyle": estilo}], "horizontalTextAlignment": alinear}


def caja_texto(parrafos, fondo=None, borde=None):
    v = {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": parrafos}}]},
         "visualContainerObjects": {
             "background": [{"properties": {"show": lit("true" if fondo else "false"),
                                            **({"color": color(fondo), "transparency": lit("0D")} if fondo else {})}}],
             "border": [{"properties": {"show": lit("true" if borde else "false"),
                                        **({"color": color(borde), "radius": lit("10D")} if borde else {})}}],
             "padding": [{"properties": {k: lit("14D" if fondo else "0D") for k in ("top", "bottom", "left", "right")}}],
         },
         "drillFilterOtherVisuals": True}
    return v


def boton_navegacion(destino, texto, activo):
    """Botón del menú superior. El de la página actual queda resaltado (sección activa)."""
    estados = []
    if activo:
        estados.append({"properties": {"show": lit("true"), "fillColor": color(C["superficie"]),
                                       "transparency": lit("0D")}, "selector": {"id": "default"}})
    else:
        estados += [
            {"properties": {"show": lit("false")}, "selector": {"id": "default"}},
            {"properties": {"show": lit("true"), "fillColor": color(C["marino_hover"]), "transparency": lit("0D")},
             "selector": {"id": "hover"}},
        ]
    texto_props = {"show": lit("true"), "text": txt(texto), "fontSize": lit("10D"), "bold": lit("true"),
                   "fontColor": color(C["marino"] if activo else C["menu_texto"]), "horizontalAlignment": txt("center")}
    textos = [{"properties": texto_props, "selector": {"id": "default"}}]
    if not activo:
        textos.append({"properties": {"fontColor": color(C["superficie"])}, "selector": {"id": "hover"}})
    v = {"visualType": "actionButton",
         "objects": {"icon": [{"properties": {"shapeType": txt("blank"), "show": lit("false")}, "selector": {"id": "default"}}],
                     "text": textos, "fill": estados,
                     "outline": [{"properties": {"show": lit("false")}, "selector": {"id": "default"}}]},
         "visualContainerObjects": {
             "background": [{"properties": {"show": lit("false")}}],
             "border": [{"properties": {"show": lit("false")}}],
             "visualLink": [{"properties": {"show": lit("true"), "type": txt("PageNavigation"),
                                            "navigationSection": txt(destino)}}]},
         "drillFilterOtherVisuals": True}
    if activo:  # la sección activa no navega (ya estamos en ella)
        v["visualContainerObjects"]["visualLink"][0]["properties"]["show"] = lit("false")
    return v


def boton_superpuesto(destino):
    """Botón transparente sobre una tarjeta de la página de inicio: la hace clicable y le da estado al pasar."""
    return {"visualType": "actionButton",
            "objects": {"icon": [{"properties": {"shapeType": txt("blank"), "show": lit("false")}, "selector": {"id": "default"}}],
                        "text": [{"properties": {"show": lit("false")}, "selector": {"id": "default"}}],
                        "outline": [{"properties": {"show": lit("false")}, "selector": {"id": "default"}}],
                        "fill": [{"properties": {"show": lit("false")}, "selector": {"id": "default"}},
                                 {"properties": {"show": lit("true"), "fillColor": color(C["marino"]),
                                                 "transparency": lit("92D")}, "selector": {"id": "hover"}}]},
            "visualContainerObjects": {
                "background": [{"properties": {"show": lit("false")}}],
                "border": [{"properties": {"show": lit("false")}}],
                "visualLink": [{"properties": {"show": lit("true"), "type": txt("PageNavigation"),
                                               "navigationSection": txt(destino)}}]},
            "drillFilterOtherVisuals": True}


def poner_encabezado(pagina, visuales):
    """Banda azul con el título de la página y el menú superior persistente."""
    vdir = PAGINAS / pagina / "visuals"
    titulo = next((d for d in visuales if d["visual"]["visualType"] == "textbox" and d["position"]["y"] < 20), None)
    nombre_t = titulo["name"] if titulo else nombre(pagina, "titulo")
    vt = caja_texto([parrafo(TITULOS[pagina], 18, C["superficie"], negrita=True, fuente="Segoe UI Semibold")],
                    fondo=C["marino"])
    vt["visualContainerObjects"]["padding"] = [{"properties": {"top": lit("12D"), "bottom": lit("8D"),
                                                               "left": lit("24D"), "right": lit("8D")}}]
    escribir(vdir / nombre_t / "visual.json", contenedor(nombre_t, 0, ENC[0], ANCHO, ENC[1], 1000, vt))
    poner_actualizacion(pagina)
    if not MENU_BOTONES:
        return
    ancho_b, sep = 128, 8
    x = ANCHO - M - len(MENU) * ancho_b - (len(MENU) - 1) * sep
    for i, (destino, texto) in enumerate(MENU):
        n = nombre(pagina, "menu", destino)
        escribir(vdir / n / "visual.json",
                 contenedor(n, x + i * (ancho_b + sep), 14, ancho_b, 36, 40000 + i, boton_navegacion(destino, texto, destino == pagina)))


def poner_actualizacion(pagina):
    """Tarjeta en el extremo derecho de la banda azul con la fecha y hora de la última captura cargada (21-oct)."""
    medida = "Última actualización"
    v = {"visualType": "card",
         "query": {"queryState": {"Values": {"projections": [{
             "field": {"Measure": {"Expression": {"SourceRef": {"Entity": "fact_precio_diario"}}, "Property": medida}},
             "queryRef": f"fact_precio_diario.{medida}", "nativeQueryRef": medida, "displayName": medida}]}}},
         "objects": {
             "labels": [{"properties": {"color": color(C["superficie"]), "fontSize": lit("14D"),
                                        "fontFamily": txt("Segoe UI Semibold")}}],
             "categoryLabels": [{"properties": {"show": lit("true"), "color": color(C["menu_texto"]),
                                                "fontSize": lit("9D")}}]},
         "visualContainerObjects": {
             "title": [{"properties": {"show": lit("false")}}],
             "background": [{"properties": {"show": lit("false")}}],
             "border": [{"properties": {"show": lit("false")}}],
             "padding": [{"properties": {k: lit("0D") for k in ("top", "bottom", "left", "right")}}],
             "visualHeader": [{"properties": {"show": lit("false")}}]},
         "drillFilterOtherVisuals": True}
    n = nombre(pagina, "actualizacion")
    ancho = 220
    escribir(PAGINAS / pagina / "visuals" / n / "visual.json",
             contenedor(n, ANCHO - M - ancho, ENC[0] + 8, ancho, ENC[1] - 16, 1100, v))


def repartir(x0, x1, pesos, sep=12):
    """Divide [x0, x1] en columnas proporcionales a `pesos`. Devuelve [(x, ancho), ...]."""
    util = x1 - x0 - sep * (len(pesos) - 1)
    total = sum(pesos)
    res, x = [], x0
    for i, p in enumerate(pesos):
        w = round(util * p / total) if i < len(pesos) - 1 else x1 - x
        res.append((x, w))
        x += w + sep
    return res


def mover(d, x, y, w, h):
    d["position"].update({"x": x, "y": y, "width": w, "height": h})


def campo(d):
    proy = d["visual"].get("query", {}).get("queryState", {})
    return [p["queryRef"] for r in proy.values() for p in r["projections"]]


def titulo_de(d):
    return (d["visual"].get("visualContainerObjects", {}).get("title", [{}])[0].get("properties", {})
            .get("text", {}).get("expr", {}).get("Literal", {}).get("Value", "").strip("'"))


def colores_por(d, entidad, propiedad, mapa):
    sel = []
    for valor, c in mapa.items():
        sel.append({"properties": {"fill": color(c)}, "selector": {"data": [{"scopeId": {"Comparison": {
            "ComparisonKind": 0,
            "Left": {"Column": {"Expression": {"SourceRef": {"Entity": entidad}}, "Property": propiedad}},
            "Right": {"Literal": {"Value": "'" + valor.replace("'", "''") + "'"}}}}}]}})
    d["visual"].setdefault("objects", {})["dataPoint"] = sel


# ------------------------------------------------------------------ 1. tema
def tema():
    t = {
        "name": "TFM Precios",
        "dataColors": [C["secundario"], C["secundario_claro"], "#1F5AA6", "#7A4FB5", "#C2367A", "#E0A100",
                       "#5FA8E8", "#2E8B8B", "#8C6D46", "#6B7A8F"],
        "foreground": C["texto"], "foregroundNeutralSecondary": C["texto_2"], "foregroundNeutralTertiary": C["sin_datos"],
        "background": C["superficie"], "backgroundLight": C["fondo"], "backgroundNeutral": C["borde"],
        "tableAccent": C["marino"], "good": C["ok"], "neutral": C["alerta"], "bad": C["error"],
        "maximum": C["marino"], "center": C["secundario_claro"], "minimum": "#EEF2F7",
        "textClasses": {
            "callout": {"fontSize": 22, "fontFace": "Segoe UI Semibold", "color": C["marino"]},
            "title": {"fontSize": 12, "fontFace": "Segoe UI Semibold", "color": C["texto"]},
            "header": {"fontSize": 12, "fontFace": "Segoe UI Semibold", "color": C["texto"]},
            "label": {"fontSize": 10, "fontFace": "Segoe UI", "color": C["texto_2"]},
        },
        "visualStyles": {
            "*": {"*": {
                "background": [{"show": True, "color": {"solid": {"color": C["superficie"]}}, "transparency": 0}],
                "border": [{"show": True, "color": {"solid": {"color": C["borde"]}}, "radius": 8, "width": 1}],
                "dropShadow": [{"show": False}],
                "padding": [{"top": 8, "bottom": 8, "left": 12, "right": 12}],
                "title": [{"fontSize": 12, "fontFamily": "Segoe UI Semibold", "fontColor": {"solid": {"color": C["texto"]}},
                           "titleWrap": True}],
                "categoryAxis": [{"fontSize": 10, "fontFamily": "Segoe UI", "showAxisTitle": False}],
                "valueAxis": [{"fontSize": 10, "fontFamily": "Segoe UI", "showAxisTitle": False,
                               "gridlineColor": {"solid": {"color": C["borde"]}}}],
                "legend": [{"fontSize": 10, "fontFamily": "Segoe UI", "position": "Top"}],
                "labels": [{"fontSize": 10, "fontFamily": "Segoe UI"}],
            }},
            "page": {"*": {"background": [{"color": {"solid": {"color": C["fondo"]}}, "transparency": 0}],
                           "outspace": [{"color": {"solid": {"color": "#E9EDF2"}}}]}},
            "card": {"*": {
                "labels": [{"fontSize": 22, "fontFamily": "Segoe UI Semibold", "color": {"solid": {"color": C["marino"]}}}],
                "categoryLabels": [{"show": True, "fontSize": 10, "fontFamily": "Segoe UI",
                                    "color": {"solid": {"color": C["texto_2"]}}}]}},
            "slicer": {"*": {
                "items": [{"fontSize": 10, "fontFamily": "Segoe UI"}],
                "title": [{"fontSize": 10, "fontFamily": "Segoe UI Semibold", "fontColor": {"solid": {"color": C["texto_2"]}}}],
                "padding": [{"top": 4, "bottom": 4, "left": 10, "right": 10}]}},
            "tableEx": {"*": {
                "columnHeaders": [{"fontSize": 10, "fontFamily": "Segoe UI Semibold",
                                   "fontColor": {"solid": {"color": C["marino"]}},
                                   "backColor": {"solid": {"color": "#EEF2F7"}}, "wordWrap": True}],
                "values": [{"fontSize": 10, "fontFamily": "Segoe UI", "backColorSecondary": {"solid": {"color": "#F8FAFC"}}}],
                "total": [{"totals": False}]}},
            "textbox": {"*": {"background": [{"show": False}], "border": [{"show": False}]}},
            "actionButton": {"*": {"background": [{"show": False}], "border": [{"show": False}]}},
        },
    }
    destino = RAIZ / "StaticResources" / "RegisteredResources" / TEMA
    escribir(destino, t)
    rep = RAIZ / "definition" / "report.json"
    r = leer(rep)
    r["themeCollection"] = {"customTheme": {"name": TEMA, "type": "RegisteredResources",
                                            "reportVersionAtImport": {"visual": "2.7.0", "page": "2.1.0", "report": "3.3.0"}}}
    r["resourcePackages"] = [{"name": "RegisteredResources", "type": "RegisteredResources",
                              "items": [{"name": TEMA, "path": TEMA, "type": "CustomTheme"}]}]
    escribir(rep, r)


# ------------------------------------------------------------------ 2. página de inicio
def inicio():
    p = PAGINAS / "inicio"
    escribir(p / "page.json", {"$schema": ESQ_PAGINA, "name": "inicio", "displayName": "Inicio",
                               "displayOption": "FitToPage", "height": 720, "width": 1280})
    poner_encabezado("inicio", [])
    v = p / "visuals"
    intro = caja_texto([
        parrafo("¿Qué quiere consultar?", 16, C["texto"], negrita=True, fuente="Segoe UI Semibold"),
        parrafo("Precios de televisores capturados cada día en Alkosto, Ktronix, Jumbo, Olímpica y Éxito. "
                "Elija una sección.", 11, C["texto_2"])])
    escribir(v / nombre("inicio", "intro") / "visual.json",
             contenedor(nombre("inicio", "intro"), M, 84, 900, 64, 1500, intro))
    secciones = [
        ("resumen", "📊", "Vista general", "Precio más bajo de cada televisor, la tienda que lo ofrece y el enlace a su ficha."),
        ("brecha", "⚖️", "Brechas entre cadenas", "Cuánto cambia el precio del mismo televisor entre cadenas, por marca y por tamaño."),
        ("evolucion", "📈", "Evolución diaria", "Cómo se movieron los precios y la brecha día a día, por tienda y por producto."),
        ("calidad", "✅", "Calidad de los datos", "Completitud, emparejamiento, precios atípicos y resultado de cada captura."),
    ]
    w, h = (ANCHO - 2 * M - 16) // 2, 214
    for i, (destino, icono, titulo, desc) in enumerate(secciones):
        x = M + (i % 2) * (w + 16)
        y = 164 + (i // 2) * (h + 16)
        tarjeta = caja_texto([
            parrafo(icono, 26, C["marino"]),
            parrafo(titulo, 18, C["marino"], negrita=True, fuente="Segoe UI Semibold"),
            parrafo(desc, 11, C["texto_2"]),
            parrafo(" ", 6, C["texto_2"]),
            parrafo("Abrir sección  →", 10, C["enlace"], negrita=True)], fondo=C["superficie"], borde=C["borde"])
        tarjeta["visualContainerObjects"]["padding"] = [{"properties": {k: lit("20D") for k in ("top", "bottom", "left", "right")}}]
        nt = nombre("inicio", "tarjeta", destino)
        escribir(v / nt / "visual.json", contenedor(nt, x, y, w, h, 2000 + i, tarjeta))
        nb = nombre("inicio", "ir", destino)
        escribir(v / nb / "visual.json", contenedor(nb, x, y, w, h, 3000 + i, boton_superpuesto(destino)))
    # Colores de las tiendas (la misma correspondencia en todas las páginas).
    corridas = [{"value": "Colores por tienda:   ", "textStyle": {"fontSize": "10pt", "color": C["texto_2"], "fontFamily": "Segoe UI"}}]
    for t, c in TIENDAS.items():
        corridas.append({"value": "■ ", "textStyle": {"fontSize": "12pt", "color": c}})
        corridas.append({"value": f"{t}     ", "textStyle": {"fontSize": "10pt", "color": C["texto"], "fontFamily": "Segoe UI"}})
    leyenda = caja_texto([{"textRuns": corridas},
                          parrafo("Fuente: Azure Synapse SQL serverless (tfm_oro) · captura diaria a las 06:00 (hora de Colombia)",
                                  9, C["sin_datos"])])
    nl = nombre("inicio", "leyenda")
    escribir(v / nl / "visual.json", contenedor(nl, M, 640, ANCHO - 2 * M, 56, 1600, leyenda))
    pp = PAGINAS / "pages.json"
    d = leer(pp)
    d["pageOrder"] = ["inicio"] + [x for x in d["pageOrder"] if x != "inicio"]
    d["activePageName"] = "inicio"
    escribir(pp, d)


# ------------------------------------------------------------------ 3. páginas existentes
GRUPOS_SINCRONIZADOS = {"dim_calendario.fecha": "fecha", "dim_producto.marca": "marca", "dim_producto.pulgadas": "pulgadas",
                        "dim_producto.tecnologia": "tecnologia", "dim_tienda.tienda": "tienda"}
ORDEN_FILTROS = ["dim_calendario.fecha", "dim_producto.marca", "dim_producto.pulgadas", "dim_producto.tecnologia",
                 "dim_tienda.tienda", "dim_producto.descripcion"]
PESO_FILTRO = {"dim_calendario.fecha": 1.3, "dim_producto.descripcion": 2.2}


def pagina(nombre_p, disposicion):
    vdir = PAGINAS / nombre_p / "visuals"
    archivos = {f: leer(f) for f in vdir.glob("*/visual.json")}
    visuales = list(archivos.values())
    poner_encabezado(nombre_p, visuales)
    archivos = {f: leer(f) for f in vdir.glob("*/visual.json")}

    # Filtros: en una fila, en orden de relevancia, sincronizados entre páginas y con el botón de restablecer al final.
    seg = [(f, d) for f, d in archivos.items() if d["visual"]["visualType"] == "slicer"]
    for f, d in seg:
        q = campo(d)[0]
        if q == "dim_producto.rango_pulgadas":  # pulgadas exactas en todas las páginas
            p = d["visual"]["query"]["queryState"]["Values"]["projections"][0]
            p["field"]["Column"]["Property"] = "pulgadas"
            p["queryRef"], p["nativeQueryRef"] = "dim_producto.pulgadas", "pulgadas"
            q = "dim_producto.pulgadas"
        if q in GRUPOS_SINCRONIZADOS:
            d["visual"]["syncGroup"] = {"groupName": GRUPOS_SINCRONIZADOS[q], "fieldChanges": True, "filterChanges": True}
    seg.sort(key=lambda fd: ORDEN_FILTROS.index(campo(fd[1])[0]))
    for (f, d), (x, w) in zip(seg, repartir(M, BOTON_RESET[0] - 12, [PESO_FILTRO.get(campo(d)[0], 1) for _, d in seg])):
        mover(d, x, FIL[0], w, FIL[1])
    for f, d in archivos.items():
        v = d["visual"]
        if v["visualType"] == "actionButton" and v.get("visualContainerObjects", {}).get("visualLink", [{}])[0] \
                .get("properties", {}).get("type", {}).get("expr", {}).get("Literal", {}).get("Value") == "'ClearAllSlicers'":
            mover(d, *BOTON_RESET)
            v["objects"]["text"][0]["properties"]["fontColor"] = color(C["marino"])
            v["objects"]["icon"][0]["properties"]["lineColor"] = color(C["marino"])
            v["objects"]["icon"][0]["properties"]["shapeType"] = txt("clearAllSlicers")
            v["objects"]["outline"][0]["properties"]["lineColor"] = color(C["borde"])
            v.setdefault("visualContainerObjects", {})["background"] = [{"properties": {
                "show": lit("true"), "color": color(C["superficie"]), "transparency": lit("0D")}}]

    # Indicadores: fila de tarjetas con ayuda contextual (sin la de última actualización, que va en la banda).
    tarjetas = sorted([(f, d) for f, d in archivos.items()
                       if d["visual"]["visualType"] == "card" and d["position"]["y"] >= FIL[0]],
                      key=lambda fd: fd[1]["position"]["x"])
    for (f, d), (x, w) in zip(tarjetas, repartir(M, ANCHO - M, [1] * len(tarjetas))):
        mover(d, x, KPI[0], w, KPI[1])
        etiqueta = d["visual"]["query"]["queryState"]["Values"]["projections"][0].get("displayName", "")
        vco = d["visual"].setdefault("visualContainerObjects", {})
        if etiqueta in AYUDAS:
            vco["visualHeader"] = [{"properties": {"show": lit("true"), "showTooltipButton": lit("true")}}]
            vco["visualHeaderTooltip"] = [{"properties": {"type": txt("Text"), "text": txt(AYUDAS[etiqueta])}}]

    # Contenido: títulos cortos, colores por tienda y la disposición propia de la página.
    for f, d in archivos.items():
        v = d["visual"]
        t = titulo_de(d)
        if t in TITULOS_VISUALES:
            v["visualContainerObjects"]["title"][0]["properties"]["text"] = txt(TITULOS_VISUALES[t])
        q = campo(d)
        if v["visualType"] in ("lineChart", "clusteredColumnChart", "clusteredBarChart") and "dim_tienda.tienda" in q:
            colores_por(d, "dim_tienda", "tienda", TIENDAS)
        if v["visualType"] == "donutChart" and "kpi_brecha_precio.cadena_mas_barata" in q:
            colores_por(d, "kpi_brecha_precio", "cadena_mas_barata", CADENAS)
        if v["visualType"] == "clusteredColumnChart" and "kpi_calidad_captura.Emparejamiento %" in q:
            v.setdefault("objects", {})["dataPoint"] = [
                {"properties": {"fill": color(C["marino"])}, "selector": {"metadata": "kpi_calidad_captura.Emparejamiento %"}},
                {"properties": {"fill": color(C["secundario_claro"])}, "selector": {"metadata": "kpi_calidad_captura.Completitud %"}}]
            v["objects"]["labels"] = [{"properties": {"show": lit("true")}}]
        if v["visualType"] == "tableEx" and "fact_ejecucion.id_ejecucion" in q:
            for p in v["query"]["queryState"]["Values"]["projections"]:
                p["displayName"] = COLUMNAS_EJECUCIONES.get(p["queryRef"], p.get("displayName"))
        for cf in v.get("objects", {}).get("columnFormatting", []):  # barras de datos con el color secundario
            if "dataBars" in cf["properties"]:
                cf["properties"]["dataBars"]["positiveColor"] = color(C["secundario"])
        if d["name"] in disposicion:
            mover(d, *disposicion[d["name"]])

    for f, d in archivos.items():
        escribir(f, d)


DISPOSICION = {
    "resumen": {"ac9a8ec9c91d5177922e": (M, CONT, ANCHO - 2 * M, FONDO_Y - CONT)},
    "brecha": {
        "b99758730668588ba0a7": (M, CONT, 400, FONDO_Y - CONT),           # brecha por marca
        "c0ada46ba92f539cb1d5": (436, CONT, 400, FONDO_Y - CONT),         # brecha por tamaño (tabla)
        "7f6f622cbabc5875a7fc": (848, CONT, 408, 210),                    # cadena con el menor precio
        "f0398d793e845d91be34": (848, CONT + 222, 408, FONDO_Y - CONT - 222),  # productos con mayor brecha
    },
    "evolucion": {
        "fbce8102f259504dae03": (M, KPI[0], 812, FONDO_Y - KPI[0]),       # precio promedio por tienda
        "ba67f1ce5f8b5c729475": (848, KPI[0], 408, 266),                  # brecha promedio por día
        "21ac6733e4d45d95913a": (848, KPI[0] + 278, 408, FONDO_Y - KPI[0] - 278),  # productos con precio por tienda
    },
    "calidad": {
        "2f2a5f87763e57b1a3f9": (M, CONT, 604, 214),                      # emparejamiento y completitud
        "80c9e248b9685411bbf9": (640, CONT, ANCHO - M - 640, 214),        # registros por día
        "2960e41323e85a13ac12": (M, CONT + 226, ANCHO - 2 * M, FONDO_Y - CONT - 226),  # detalle de ejecuciones
    },
}

if __name__ == "__main__":
    tema()
    inicio()
    for nombre_p, disp in DISPOSICION.items():
        pagina(nombre_p, disp)
    print("rediseño aplicado")

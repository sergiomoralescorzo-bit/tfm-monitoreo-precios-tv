# -*- coding: utf-8 -*-
"""Observaciones del equipo al tablero (19-nov-2026), aplicadas sobre el PBIP sin regenerarlo:

1. Fecha y hora de la última actualización más pequeña y en formato de 12 horas (a. m. / p. m.).
2. Inicio: se quita la línea «Fuente: Azure Synapse SQL serverless…».
3. La leyenda «tienda ● Alkosto ● Éxito…» no se repite en cada gráfico: se oculta y cada página con
   colores por tienda lleva una sola clave de colores en la banda superior.
4. «Eventos por tipo» pasa a barras horizontales para que los nombres de los tipos no salgan cortados.
5. Las barras por tienda usan el color fijo de cada tienda.

Es idempotente. Uso:  .venv/Scripts/python powerbi/herramientas/ajustar_observaciones_19nov.py
Después: Power BI Desktop → volver a abrir el .pbip; en Fabric: infra/fabric.py --pasos modelo,informe
"""
import hashlib
import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PAGINAS = RAIZ / "TFM_Precios.Report" / "definition" / "pages"
TMDL = RAIZ / "TFM_Precios.SemanticModel" / "definition" / "tables" / "fact_precio_diario.tmdl"
ESQ_VISUAL = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.7.0/schema.json"

TIENDAS = {"Alkosto": "#1F5AA6", "Ktronix": "#5FA8E8", "Jumbo": "#7A4FB5", "Olímpica": "#C2367A", "Éxito": "#E0A100"}
PAGINAS_CON_CLAVE = ["evolucion", "calidad", "descuentos", "eventos"]


def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def color(c):
    return {"solid": {"color": lit(f"'{c}'")}}


def leer(f):
    return json.loads(f.read_text(encoding="utf-8"))


def escribir(f, d):
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def consultas(v):
    qs = v.get("query", {}).get("queryState", {})
    return {rol: [p["queryRef"] for p in r["projections"]] for rol, r in qs.items()}


def colores_por_tienda(v):
    v.setdefault("objects", {})["dataPoint"] = [
        {"properties": {"fill": color(c)}, "selector": {"data": [{"scopeId": {"Comparison": {
            "ComparisonKind": 0,
            "Left": {"Column": {"Expression": {"SourceRef": {"Entity": "dim_tienda"}}, "Property": "tienda"}},
            "Right": {"Literal": {"Value": f"'{t}'"}}}}}]}} for t, c in TIENDAS.items()]


# ------------------------------------------------------------------ 1. medida de la última actualización
MEDIDA_NUEVA = """\tmeasure 'Última actualización' =
\t\t\tVAR _ultima = CALCULATE ( MAX ( fact_precio_diario[fecha_captura_utc] ), ALL ( fact_precio_diario ) )
\t\t\tVAR _local = _ultima - 5 / 24
\t\t\tVAR _hora = HOUR ( _local )
\t\t\tRETURN
\t\t\t    IF (
\t\t\t        NOT ISBLANK ( _ultima ),
\t\t\t        FORMAT ( _local, "dd/mm/yyyy" ) & "  " & ( MOD ( _hora + 11, 12 ) + 1 ) & ":"
\t\t\t            & FORMAT ( MINUTE ( _local ), "00" ) & IF ( _hora < 12, " a. m.", " p. m." )
\t\t\t    )
"""


def medida():
    texto = TMDL.read_text(encoding="utf-8-sig")
    fin = "\r\n" if "\r\n" in texto else "\n"
    patron = r"\tmeasure 'Última actualización' =\r?\n(?:\t\t\t[^\r\n]*\r?\n)+"
    if not re.search(patron, texto):
        raise SystemExit("No se encontró la medida 'Última actualización'")
    texto = re.sub(patron, lambda _: MEDIDA_NUEVA.replace("\n", fin), texto, count=1)
    TMDL.write_text(texto, encoding="utf-8")


def tarjetas_actualizacion():
    for f in PAGINAS.glob("*/visuals/*/visual.json"):
        d = leer(f)
        v = d["visual"]
        if v["visualType"] == "card" and "fact_precio_diario.Última actualización" in sum(consultas(v).values(), []):
            v["objects"]["labels"][0]["properties"]["fontSize"] = lit("10D")
            v["objects"]["labels"][0]["properties"]["fontFamily"] = lit("'Segoe UI'")
            v["objects"]["categoryLabels"][0]["properties"]["fontSize"] = lit("8D")
            escribir(f, d)


# ------------------------------------------------------------------ 2. sin la línea de la fuente en Inicio
def sin_fuente():
    for f in (PAGINAS / "inicio" / "visuals").glob("*/visual.json"):
        texto = f.read_text(encoding="utf-8")
        if "Fuente: Azure Synapse" not in texto:
            continue
        d = leer(f)
        props = d["visual"]["objects"]["general"][0]["properties"]
        props["paragraphs"] = [p for p in props["paragraphs"]
                               if not any("Fuente: Azure Synapse" in r.get("value", "") for r in p.get("textRuns", []))]
        d["position"]["height"] = 32
        d["position"]["y"] = 656
        escribir(f, d)


# ------------------------------------------------------------------ 3 y 5. leyendas y colores por tienda
def leyendas_y_colores():
    for f in PAGINAS.glob("*/visuals/*/visual.json"):
        d = leer(f)
        v = d["visual"]
        q = consultas(v)
        if v["visualType"] not in ("lineChart", "clusteredColumnChart", "clusteredBarChart"):
            continue
        cambio = False
        if "dim_tienda.tienda" in q.get("Series", []):          # leyenda por tienda: se quita
            v.setdefault("objects", {})["legend"] = [{"properties": {"show": lit("false")}}]
            cambio = True
        if q.get("Category") == ["dim_tienda.tienda"] and len(q.get("Y", [])) == 1:   # una barra por tienda
            colores_por_tienda(v)
            cambio = True
        if cambio:
            escribir(f, d)


def clave_colores(pagina):
    """Clave de colores por tienda en una pastilla blanca dentro de la banda superior."""
    corridas = []
    for t, c in TIENDAS.items():
        corridas.append({"value": "■ ", "textStyle": {"fontSize": "11pt", "color": c}})
        corridas.append({"value": f"{t}    ", "textStyle": {"fontSize": "9pt", "color": "#1B2A3A", "fontFamily": "Segoe UI"}})
    n = hashlib.sha1(f"{pagina}/clave_tiendas".encode()).hexdigest()[:20]
    d = {"$schema": ESQ_VISUAL, "name": n,
         "position": {"x": 600, "y": 16, "z": 1050, "width": 420, "height": 32, "tabOrder": 1050},
         "visual": {"visualType": "textbox",
                    "objects": {"general": [{"properties": {"paragraphs": [
                        {"textRuns": corridas, "horizontalTextAlignment": "center"}]}}]},
                    "visualContainerObjects": {
                        "background": [{"properties": {"show": lit("true"), "color": color("#FFFFFF"),
                                                       "transparency": lit("0D")}}],
                        "border": [{"properties": {"show": lit("true"), "color": color("#FFFFFF"), "radius": lit("16D")}}],
                        "padding": [{"properties": {"top": lit("4D"), "bottom": lit("0D"), "left": lit("8D"),
                                                    "right": lit("8D")}}],
                        "title": [{"properties": {"show": lit("false")}}],
                        "visualHeader": [{"properties": {"show": lit("false")}}]}},
         "howCreated": "InsertVisualButton"}
    escribir(PAGINAS / pagina / "visuals" / n / "visual.json", d)


# ------------------------------------------------------------------ 4. eventos por tipo en barras horizontales
def eventos_por_tipo():
    for f in (PAGINAS / "eventos" / "visuals").glob("*/visual.json"):
        d = leer(f)
        v = d["visual"]
        if consultas(v).get("Category") != ["fact_evento_comercial.tipo_evento"]:
            continue
        v["visualType"] = "clusteredBarChart"
        v.setdefault("objects", {})["categoryAxis"] = [{"properties": {
            "maxMarginFactor": lit("60L"), "fontSize": lit("9D"), "showAxisTitle": lit("false")}}]
        v["objects"]["valueAxis"] = [{"properties": {"showAxisTitle": lit("false")}}]
        escribir(f, d)


if __name__ == "__main__":
    medida()
    tarjetas_actualizacion()
    sin_fuente()
    leyendas_y_colores()
    for p in PAGINAS_CON_CLAVE:
        clave_colores(p)
    eventos_por_tipo()
    print("observaciones del 19-nov aplicadas")

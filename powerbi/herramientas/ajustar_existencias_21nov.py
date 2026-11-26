# -*- coding: utf-8 -*-
"""Filas sin existencias en la tabla de Resumen (21-nov-2026), aplicado sobre el PBIP sin regenerarlo.

La tabla «Menor precio por producto» muestra el precio del último día con existencias. Si un producto no tuvo
existencias en la última captura del periodo (agotado o ya no publicado), su fila muestra un precio y un enlace
de días anteriores. Esas filas se pintan de rojo suave en todas sus columnas, con un formato condicional que usa
la medida «Color fila sin existencias» (rojo o en blanco). El título de la tabla lo explica.

Es idempotente. Uso:  .venv/Scripts/python powerbi/herramientas/ajustar_existencias_21nov.py
Después: Power BI Desktop → volver a abrir el .pbip; en Fabric: infra/fabric.py --pasos modelo,informe
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generar_pbip import tag  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
TMDL = RAIZ / "TFM_Precios.SemanticModel" / "definition" / "tables" / "fact_precio_diario.tmdl"
VISUAL = RAIZ / "TFM_Precios.Report" / "definition" / "pages" / "resumen" / "visuals" / "ac9a8ec9c91d5177922e" / "visual.json"

ROJO_SUAVE = "#FDE2E2"
# Ajuste del 21-nov (2): el rojo es «sin existencias del vendedor propio». En Éxito, la ficha puede mostrar
# unidades de un vendedor del marketplace, que el alcance excluye. En esas filas el enlace se reemplaza por
# «Sin existencias», para que nadie tome la oferta de un tercero como precio de la tienda.
TITULO = ("Menor precio por producto · en rojo: sin existencias del vendedor propio de la tienda "
          "(puede haber oferta de terceros en la página)")
ENLACE_ANTES = ("\t\t\t        NOT ISBLANK ( _precio ),\n"
                "\t\t\t        MAXX ( TOPN ( 1, _filas, dim_tienda[tienda], ASC ), fact_precio_diario[url] )\n")
ENLACE_DESPUES = ("\t\t\t        NOT ISBLANK ( _precio ),\n"
                  "\t\t\t        IF (\n"
                  "\t\t\t            [Sin existencias en la última captura] = 1,\n"
                  "\t\t\t            \"Sin existencias\",\n"
                  "\t\t\t            MAXX ( TOPN ( 1, _filas, dim_tienda[tienda], ASC ), fact_precio_diario[url] )\n"
                  "\t\t\t        )\n")
MEDIDAS = {
    "Sin existencias en la última captura": (
        "VAR _ultima = CALCULATE ( MAX ( fact_precio_diario[fecha_key] ), ALLSELECTED ( dim_calendario ), "
        "REMOVEFILTERS ( dim_producto ) )\n"
        "VAR _fecha = [Última fecha con precio]\n"
        "RETURN\n"
        "    IF ( NOT ISBLANK ( _fecha ), IF ( _fecha < _ultima, 1, 0 ) )",
        "0", "Producto que tuvo existencias en el periodo pero no en la última captura (agotado o ya no publicado)."),
    "Color fila sin existencias": (
        f"IF ( [Sin existencias en la última captura] = 1, \"{ROJO_SUAVE}\" )",
        None, "Color de fondo de la fila en la tabla de Resumen: rojo suave si no hay existencias en la última captura."),
}


def medidas() -> list[str]:
    texto = TMDL.read_text(encoding="utf-8")
    nuevas = []
    bloque = ""
    for nombre, (dax, formato, descripcion) in MEDIDAS.items():
        if f"measure '{nombre}'" in texto:
            continue
        bloque += f"\t/// {descripcion}\n\tmeasure '{nombre}' =\n" + "".join(f"\t\t\t{x}\n" for x in dax.split("\n"))
        if formato:
            bloque += f"\t\tformatString: {formato}\n"
        bloque += f"\t\tdisplayFolder: Precios\n\t\tlineageTag: {tag('fact_precio_diario', 'medida', nombre)}\n\n"
        nuevas.append(nombre)
    if bloque:
        ancla = "\tmeasure 'Tiendas con oferta'"
        assert texto.count(ancla) == 1, "no se encontró dónde insertar las medidas"
        texto = texto.replace(ancla, bloque + ancla)
    if ENLACE_ANTES in texto:
        assert texto.count(ENLACE_ANTES) == 1
        texto = texto.replace(ENLACE_ANTES, ENLACE_DESPUES)
        nuevas.append("Enlace tienda más barata (con «Sin existencias»)")
    if nuevas:
        TMDL.write_text(texto, encoding="utf-8")
    return nuevas


def regla(query_ref: str) -> dict:
    medida = {"Measure": {"Expression": {"SourceRef": {"Entity": "fact_precio_diario"}},
                          "Property": "Color fila sin existencias"}}
    return {"properties": {"backColor": {"solid": {"color": {"expr": medida}}}},
            "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": query_ref}}


def tabla() -> bool:
    v = json.loads(VISUAL.read_text(encoding="utf-8"))
    antes = json.dumps(v, ensure_ascii=False)
    refs = [p["queryRef"] for p in v["visual"]["query"]["queryState"]["Values"]["projections"]]
    valores = v["visual"].setdefault("objects", {}).setdefault("values", [])
    valores[:] = [x for x in valores if "backColor" not in x.get("properties", {})]  # reglas anteriores de este script
    valores += [regla(r) for r in refs]
    v["visual"]["visualContainerObjects"]["title"][0]["properties"]["text"] = {"expr": {"Literal": {"Value": f"'{TITULO}'"}}}
    despues = json.dumps(v, ensure_ascii=False)
    if despues != antes:
        VISUAL.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
    return despues != antes


if __name__ == "__main__":
    n = medidas()
    print("medidas agregadas: " + ", ".join(n) if n else "medidas ya existían")
    print("tabla actualizada" if tabla() else "tabla sin cambios")

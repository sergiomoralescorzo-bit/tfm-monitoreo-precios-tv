# -*- coding: utf-8 -*-
"""Brecha del último día en la tabla de Resumen (21-nov-2026), aplicada sobre el PBIP sin regenerarlo.

La tabla «Menor precio por producto» mostraba «Brecha máxima %», que es la mayor brecha del producto en todo el
periodo, junto a «Precio más bajo», que es del último día con precio. Se agrega la medida «Brecha último día %»
(la brecha de ese mismo día) y la columna de la tabla pasa a usarla con el título «Brecha entre cadenas».
«Brecha máxima %» se mantiene para la página Brecha, donde sí se busca el máximo del periodo.

Es idempotente. Uso:  .venv/Scripts/python powerbi/herramientas/ajustar_brecha_21nov.py
Después: Power BI Desktop → volver a abrir el .pbip; en Fabric: infra/fabric.py --pasos modelo,informe
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generar_pbip import tag  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
TMDL = RAIZ / "TFM_Precios.SemanticModel" / "definition" / "tables" / "kpi_brecha_precio.tmdl"
VISUAL = RAIZ / "TFM_Precios.Report" / "definition" / "pages" / "resumen" / "visuals" / "ac9a8ec9c91d5177922e" / "visual.json"

NOMBRE = "Brecha último día %"
ANTERIOR = "Brecha máxima %"
TITULO = "Brecha entre cadenas"
MEDIDA = (f"\tmeasure '{NOMBRE}' =\n"
          "\t\t\tVAR _fecha = [Última fecha con precio]\n"
          "\t\t\tRETURN\n"
          "\t\t\t    CALCULATE ( MAX ( kpi_brecha_precio[brecha_pct] ), dim_calendario[fecha_key] = _fecha )\n"
          "\t\tformatString: 0.0%\n"
          "\t\tdisplayFolder: Brecha entre cadenas\n"
          f"\t\tlineageTag: {tag('kpi_brecha_precio', 'medida', NOMBRE)}\n\n")


def medida() -> bool:
    texto = TMDL.read_text(encoding="utf-8")
    if f"measure '{NOMBRE}'" in texto:
        return False
    ancla = "\tmeasure 'Brecha promedio $'"
    assert texto.count(ancla) == 1, "no se encontró dónde insertar la medida"
    TMDL.write_text(texto.replace(ancla, MEDIDA + ancla), encoding="utf-8")
    return True


def tabla() -> bool:
    v = json.loads(VISUAL.read_text(encoding="utf-8"))
    cambio = False
    for p in v["visual"]["query"]["queryState"]["Values"]["projections"]:
        m = p["field"].get("Measure", {})
        if m.get("Property") == ANTERIOR and m["Expression"]["SourceRef"]["Entity"] == "kpi_brecha_precio":
            m["Property"] = NOMBRE
            p["queryRef"] = f"kpi_brecha_precio.{NOMBRE}"
            p["nativeQueryRef"] = NOMBRE
            p["displayName"] = TITULO
            cambio = True
    for f in v.get("filterConfig", {}).get("filters", []):   # tarjeta de filtro de la columna en el panel
        m = f["field"].get("Measure", {})
        if m.get("Property") == ANTERIOR and m["Expression"]["SourceRef"]["Entity"] == "kpi_brecha_precio":
            m["Property"] = NOMBRE
            cambio = True
    if cambio:
        VISUAL.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
    return cambio


if __name__ == "__main__":
    print("medida agregada" if medida() else "medida ya existía")
    print("tabla actualizada" if tabla() else "tabla ya usaba la medida")

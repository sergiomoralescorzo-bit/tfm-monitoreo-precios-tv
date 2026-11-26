# -*- coding: utf-8 -*-
"""Pruebas de las definiciones de pipelines de Synapse y de la plantilla de notificaciones (sin Azure)."""
import json
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
PIPELINES = RAIZ / "synapse" / "pipelines"


def cargar(nombre: str) -> dict:
    return json.loads((PIPELINES / f"{nombre}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("nombre", ["pl_captura_diaria", "pl_medallon_diario", "pl_medallon_synapse"])
def test_cada_actividad_principal_avisa_y_falla(nombre):
    acts = {a["name"]: a for a in cargar(nombre)["properties"]["activities"]}
    principales = [n for n in acts if not n.startswith(("Avisar fallo - ", "Fallo - "))]
    assert principales
    for x in principales:
        aviso, fallo = acts[f"Avisar fallo - {x}"], acts[f"Fallo - {x}"]
        assert aviso["dependsOn"] == [{"activity": x, "dependencyConditions": ["Failed"]}]
        assert aviso["typeProperties"]["pipeline"]["referenceName"] == "pl_notificar_fallo"
        assert aviso["typeProperties"]["parameters"]["error"]["value"] == f"@activity('{x}').error.message"
        # el Fail corre aunque el aviso falle, para que la pipeline nunca quede en Succeeded
        assert fallo["type"] == "Fail"
        assert set(fallo["dependsOn"][0]["dependencyConditions"]) == {"Succeeded", "Failed"}


def test_notificar_fallo_no_guarda_la_url_firmada():
    texto = (PIPELINES / "pl_notificar_fallo.json").read_text(encoding="utf-8")
    web = cargar("pl_notificar_fallo")["properties"]["activities"][0]
    assert web["typeProperties"]["url"] == "__URL_NOTIFICACION__"
    assert web["policy"]["secureInput"] is True
    assert "sig=" not in texto and "logic.azure.com" not in texto
    assert "base64(" in web["typeProperties"]["body"]["value"]


def test_plantilla_de_notificaciones():
    plantilla = json.loads((RAIZ / "infra" / "notificaciones.json").read_text(encoding="utf-8"))
    tipos = {r["type"] for r in plantilla["resources"]}
    assert tipos == {"Microsoft.Web/connections", "Microsoft.Logic/workflows",
                     "Microsoft.Insights/actionGroups", "Microsoft.Insights/metricAlerts"}
    alerta = next(r for r in plantilla["resources"] if r["type"] == "Microsoft.Insights/metricAlerts")
    criterio = alerta["properties"]["criteria"]["allOf"][0]
    assert criterio["metricName"] == "IntegrationPipelineRunsEnded"
    assert {"name": "Result", "operator": "Include", "values": ["Failed"]} in criterio["dimensions"]
    assert plantilla["parameters"]["teamsWebhook"]["type"] == "securestring"


def test_plantilla_de_vigilancia():
    plantilla = json.loads((RAIZ / "infra" / "vigilancia.json").read_text(encoding="utf-8"))
    flujo = plantilla["resources"][0]
    assert flujo["identity"]["type"] == "SystemAssigned"
    assert plantilla["parameters"]["urlAviso"]["type"] == "securestring"
    definicion = flujo["properties"]["definition"]
    rec = definicion["triggers"]["Diario_0930"]["recurrence"]
    assert rec["timeZone"] == "SA Pacific Standard Time" and rec["schedule"] == {"hours": [9], "minutes": [30]}
    assert "pl_medallon_diario" in definicion["actions"]["Vigiladas"]["inputs"]
    consulta = definicion["actions"]["Por_pipeline"]["actions"]["Consultar"]["inputs"]
    assert consulta["authentication"]["audience"] == "https://dev.azuresynapse.net"
    assert {"operand": "Status", "operator": "Equals", "values": ["Succeeded"]} in consulta["body"]["filters"]
    assert "sig=" not in json.dumps(plantilla)


def test_un_solo_disparador_inicia_el_orquestador_antes_de_su_primera_hora():
    disparadores = sorted(p.stem for p in (RAIZ / "synapse" / "triggers").glob("*.json"))
    assert disparadores == ["tr_orquestador_diario"]
    d = json.loads((RAIZ / "synapse" / "triggers" / "tr_orquestador_diario.json").read_text(encoding="utf-8"))
    assert [p["pipelineReference"]["referenceName"] for p in d["properties"]["pipelines"]] == ["pl_orquestador_diario"]
    rec = d["properties"]["typeProperties"]["recurrence"]
    assert rec["frequency"] == "Day" and rec["schedule"]["hours"] == [6]
    # Con startTime igual a la primera hora programada, Synapse no ejecutó el 18-oct-2026.
    assert rec["startTime"].endswith("T00:00:00")


def test_orquestador_reintenta_y_corre_el_medallon_aunque_falle_la_captura():
    # 12-nov-2026: Éxito bloqueado por Cloudflare dejó la captura en Failed y oro sin datos de ningún sitio.
    # 19-nov-2026: cada etapa se reintenta hasta 2 veces, con 20 min de pausa (probado en Synapse con pipelines
    # de prueba: 3 intentos, 2 pausas, medallón ejecutado y Failed al final).
    acts = {a["name"]: a for a in cargar("pl_orquestador_diario")["properties"]["activities"]}
    for ciclo, hija, ok, var in [("Captura con reintentos", "pl_captura_diaria", "captura_ok", "intentos_captura"),
                                 ("Medallon con reintentos", "pl_medallon_diario", "medallon_ok", "intentos_medallon")]:
        u = acts[ciclo]
        assert u["type"] == "Until"
        assert u["typeProperties"]["expression"]["value"] == (
            f"@or(variables('{ok}'), greaterOrEquals(length(variables('{var}')), 3))")
        dentro = {a["name"]: a for a in u["typeProperties"]["activities"]}
        ejecutar = next(a for a in dentro.values() if a["type"] == "ExecutePipeline")
        assert ejecutar["typeProperties"]["pipeline"]["referenceName"] == hija
        assert ejecutar["typeProperties"]["waitOnCompletion"]
        espera = next(a for a in dentro.values() if a["type"] == "IfCondition")
        assert espera["dependsOn"] == [{"activity": ejecutar["name"], "dependencyConditions": ["Failed"]}]
        assert espera["typeProperties"]["ifTrueActivities"][0]["typeProperties"]["waitTimeInSeconds"] == 1200
    assert acts["Medallon con reintentos"]["dependsOn"] == [
        {"activity": "Captura con reintentos", "dependencyConditions": ["Completed"]}]
    final = acts["Resultado final"]
    assert final["typeProperties"]["ifFalseActivities"][0]["type"] == "Fail"


def test_ningun_literal_de_expresion_termina_en_parentesis():
    # 20-nov-2026: «' intento)'» dentro de un if() hizo que Synapse rechazara pl_orquestador_diario al iniciar
    # (InvalidTemplate, «Unable to parse expression») y ese día no corrió la captura. Los paréntesis van en
    # literales aparte del plural, como «') y medallón '».
    for archivo in sorted((RAIZ / "synapse" / "pipelines").glob("*.json")):
        texto = json.dumps(json.loads(archivo.read_text(encoding="utf-8")), ensure_ascii=False)
        assert ")'" not in texto, archivo.name

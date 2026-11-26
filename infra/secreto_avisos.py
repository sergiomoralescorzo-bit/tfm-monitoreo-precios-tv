# -*- coding: utf-8 -*-
"""Guarda la URL de la Logic App la-tfm-avisos como secreto `url-avisos` del job del medallón.

La URL lleva '&' y `az.cmd` la corta al pasarla como argumento (cmd.exe lo toma como separador),
así que se usa la API REST con el cuerpo en un archivo. Lo llama `desplegar.ps1 -Pasos avisos`.
Uso: python infra/secreto_avisos.py [grupo] [job] [logic_app]
Por defecto toma TFM_GRUPO, TFM_JOB_MEDALLON y TFM_LOGIC_APP_AVISOS, o los nombres del despliegue del TFM.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

GRUPO = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TFM_GRUPO", "RG-TFM-WEBSCRAPING")
JOB = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("TFM_JOB_MEDALLON", "caj-tfm-medallon")
LOGIC_APP = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("TFM_LOGIC_APP_AVISOS", "la-tfm-avisos")
API = "2024-03-01"


def az(*args: str) -> str:
    r = subprocess.run(["az", *args], capture_output=True, text=True, encoding="utf-8", shell=sys.platform == "win32")
    if r.returncode != 0:
        raise SystemExit(f"Falló az {args[:3]}: {r.stderr.strip()[:300]}")
    return r.stdout


sub = az("account", "show", "--query", "id", "-o", "tsv").strip()
base = f"https://management.azure.com/subscriptions/{sub}/resourceGroups/{GRUPO}/providers"
url = json.loads(az("rest", "--method", "post", "--uri",
                    f"{base}/Microsoft.Logic/workflows/{LOGIC_APP}/triggers/manual/listCallbackUrl?api-version=2019-05-01"))["value"]
job = json.loads(az("rest", "--method", "get", "--uri", f"{base}/Microsoft.App/jobs/{JOB}?api-version={API}"))
otros = [s for s in job["properties"]["configuration"].get("secrets") or [] if s["name"] != "url-avisos"]
if otros:
    raise SystemExit(f"El job tiene otros secretos ({[s['name'] for s in otros]}): este script no conoce sus valores")
cuerpo = {"location": job["location"], "identity": job.get("identity"),
          "properties": {"environmentId": job["properties"]["environmentId"],
                         "configuration": {**job["properties"]["configuration"],
                                           "secrets": [{"name": "url-avisos", "value": url}]},
                         "template": job["properties"]["template"]}}
with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
    json.dump(cuerpo, f)
try:
    az("rest", "--method", "put", "--uri", f"{base}/Microsoft.App/jobs/{JOB}?api-version={API}",
       "--body", f"@{f.name}", "-o", "none")
finally:
    Path(f.name).unlink(missing_ok=True)
print(f"Secreto url-avisos actualizado en {JOB} ({len(url)} caracteres)")

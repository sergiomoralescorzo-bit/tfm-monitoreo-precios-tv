# -*- coding: utf-8 -*-
"""Montaje del tablero en Microsoft Fabric sobre la capa oro (alternativa A, sesión 19 de la bitácora).

Los datos se quedan en ADLS: el lakehouse solo tiene accesos directos (shortcuts) de esquema a
oro/{dimensiones,hechos,kpis}, leídos con la identidad del área de trabajo. La captura, el medallón y
Synapse no cambian. Cada paso es idempotente: si el elemento ya existe, lo reutiliza.

Pasos (en orden):
    identidad   crea la identidad del área de trabajo (Fabric)
    permiso     le da Storage Blob Data Reader sobre la cuenta del lago (Azure; requiere Owner del grupo)
    conexion    conexión a ADLS con la identidad del área (Fabric la prueba al crearla)
    lakehouse   lakehouse (lh_tfm_oro por defecto) con esquemas
    atajos      accesos directos de esquema dimensiones, hechos y kpis
    revisar     sincroniza el punto de conexión SQL y lista las tablas que ve el lakehouse
    modelo      modelo semántico TFM_Precios en Direct Lake, convertido del TMDL del PBIP al desplegar
    informe     informe TFM_Precios (PBIR del PBIP) conectado a ese modelo

Uso (con `az login` hecho por un administrador del área de trabajo):
    .venv/Scripts/python infra/fabric.py --area "TFM Monitoreo Precios"
    .venv/Scripts/python infra/fabric.py --area <id del área> --pasos atajos,revisar

Nombres de recursos: los valores por defecto son los del despliegue del TFM. Para otra suscripción se cambian
con las variables de entorno TFM_GRUPO, TFM_CUENTA, TFM_CONTENEDOR, TFM_LAKEHOUSE y TFM_CONEXION_FABRIC.
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
from azure.identity import AzureCliCredential

API = "https://api.fabric.microsoft.com/v1"
CUENTA = os.environ.get("TFM_CUENTA", "sttfmwebscraping")
CONTENEDOR = os.environ.get("TFM_CONTENEDOR", "datalake-tfm")
GRUPO = os.environ.get("TFM_GRUPO", "RG-TFM-WEBSCRAPING")
SERVIDOR = f"https://{CUENTA}.dfs.core.windows.net"
LAKEHOUSE = os.environ.get("TFM_LAKEHOUSE", "lh_tfm_oro")
CONEXION = os.environ.get("TFM_CONEXION_FABRIC", "adls-tfm-oro")
ESQUEMAS = ["dimensiones", "hechos", "kpis"]
PASOS = ["identidad", "permiso", "conexion", "lakehouse", "atajos", "revisar", "modelo", "informe"]
PBIP = Path(__file__).resolve().parents[1] / "powerbi"
NOMBRE = "TFM_Precios"
# Tabla del modelo -> esquema del lakehouse (acceso directo a oro/<esquema>)
ESQUEMA_DE = {"dim_producto": "dimensiones", "dim_tienda": "dimensiones", "dim_calendario": "dimensiones",
              "fact_precio_diario": "hechos", "fact_ejecucion": "hechos", "fact_evento_comercial": "hechos",
              "kpi_brecha_precio": "kpis", "kpi_calidad_captura": "kpis"}
# Columnas cuyo tipo en Delta difiere del de la vista de Synapse (la vista hace CAST)
TIPOS_DELTA = {("kpi_brecha_precio", "precio_promedio"): "double"}


class Fabric:
    def __init__(self):
        self.cred = AzureCliCredential()
        self.http = httpx.Client(timeout=120)

    def _cabeceras(self) -> dict:
        return {"Authorization": f"Bearer {self.cred.get_token('https://api.fabric.microsoft.com/.default').token}"}

    def pedir(self, metodo: str, ruta: str, cuerpo: dict | None = None, ok=(200, 201, 202)) -> dict:
        r = self.http.request(metodo, ruta if ruta.startswith("http") else API + ruta, json=cuerpo,
                              headers=self._cabeceras())
        if r.status_code == 202 and r.headers.get("Location"):        # operación larga
            return self._esperar(r)
        if r.status_code not in ok:
            raise RuntimeError(f"{metodo} {ruta}: HTTP {r.status_code} {r.text[:800]}")
        return r.json() if r.content else {}

    def _esperar(self, r) -> dict:
        ubicacion = r.headers["Location"]
        while True:
            time.sleep(int(r.headers.get("Retry-After", 5)))
            r = self.http.get(ubicacion, headers=self._cabeceras())
            estado = (r.json() if r.content else {}).get("status")
            if estado in ("Succeeded", None) and r.status_code == 200:
                resultado = self.http.get(ubicacion + "/result", headers=self._cabeceras())
                return resultado.json() if resultado.status_code == 200 and resultado.content else {}
            if estado in ("Failed", "Undefined"):
                raise RuntimeError(f"Operación fallida: {r.text[:800]}")

    def todos(self, ruta: str) -> list[dict]:
        salida, url = [], API + ruta
        while url:
            d = self.pedir("GET", url)
            salida += d.get("value", [])
            url = d.get("continuationUri")
        return salida


def buscar_area(f: Fabric, area: str) -> dict:
    for w in f.todos("/workspaces"):
        if area in (w["id"], w["displayName"]) or w["displayName"].rstrip(". ") == area.rstrip(". "):
            return f.pedir("GET", f"/workspaces/{w['id']}")
    raise SystemExit(f"No encuentro el área de trabajo «{area}» con esta cuenta (¿es administrador?).")


def paso_identidad(f: Fabric, w: dict) -> dict:
    if not w.get("workspaceIdentity"):
        print("Creando la identidad del área de trabajo…")
        f.pedir("POST", f"/workspaces/{w['id']}/provisionIdentity")
        w = f.pedir("GET", f"/workspaces/{w['id']}")
    ident = w["workspaceIdentity"]
    print(f"Identidad del área: aplicación {ident['applicationId']}, entidad de servicio {ident['servicePrincipalId']}")
    return w


def az(*args: str) -> str:
    r = subprocess.run(["az", *args, "-o", "tsv"], capture_output=True, text=True, shell=sys.platform == "win32")
    if r.returncode != 0:
        raise RuntimeError(f"az {' '.join(args[:3])}: {r.stderr.strip()[:500]}")
    return r.stdout.strip()


def paso_permiso(w: dict) -> None:
    sp = w["workspaceIdentity"]["servicePrincipalId"]
    alcance = az("storage", "account", "show", "-n", CUENTA, "-g", GRUPO, "--query", "id")
    ya = az("role", "assignment", "list", "--assignee", sp, "--scope", alcance, "--role", "Storage Blob Data Reader",
            "--query", "[].id")
    if ya:
        print("La identidad ya tiene Storage Blob Data Reader sobre la cuenta.")
        return
    az("role", "assignment", "create", "--assignee-object-id", sp, "--assignee-principal-type", "ServicePrincipal",
       "--role", "Storage Blob Data Reader", "--scope", alcance, "--query", "id")
    print("Storage Blob Data Reader asignado (puede tardar unos minutos en aplicarse).")


def paso_conexion(f: Fabric) -> str:
    for c in f.todos("/connections"):
        if c.get("displayName") == CONEXION:
            print(f"Conexión {CONEXION} ya existe: {c['id']}")
            return c["id"]
    cuerpo = {
        "connectivityType": "ShareableCloud",
        "displayName": CONEXION,
        "privacyLevel": "Organizational",
        "connectionDetails": {"type": "AzureDataLakeStorage", "creationMethod": "AzureDataLakeStorage",
                              "parameters": [{"dataType": "Text", "name": "server", "value": SERVIDOR},
                                             {"dataType": "Text", "name": "path", "value": f"/{CONTENEDOR}/oro"}]},
        "credentialDetails": {"singleSignOnType": "None", "connectionEncryption": "NotEncrypted",
                              "skipTestConnection": False, "credentials": {"credentialType": "WorkspaceIdentity"}},
    }
    for intento in range(1, 11):          # el permiso de Azure tarda en aplicarse
        try:
            c = f.pedir("POST", "/connections", cuerpo)
            print(f"Conexión {CONEXION} creada: {c['id']}")
            return c["id"]
        except RuntimeError as e:
            if intento == 10:
                raise
            print(f"La conexión todavía no pasa la prueba (intento {intento}); espero 60 s. {str(e)[:160]}")
            time.sleep(60)


def paso_lakehouse(f: Fabric, w: dict) -> str:
    for i in f.todos(f"/workspaces/{w['id']}/lakehouses"):
        if i["displayName"] == LAKEHOUSE:
            print(f"Lakehouse {LAKEHOUSE} ya existe: {i['id']}")
            return i["id"]
    lh = f.pedir("POST", f"/workspaces/{w['id']}/lakehouses",
                 {"displayName": LAKEHOUSE, "description": "Capa oro del TFM (accesos directos a ADLS, sin copias)",
                  "creationPayload": {"enableSchemas": True}})
    print(f"Lakehouse {LAKEHOUSE} creado: {lh['id']}")
    return lh["id"]


def paso_atajos(f: Fabric, w: dict, lh: str, conexion: str) -> None:
    existentes = {s["name"] for s in f.todos(f"/workspaces/{w['id']}/items/{lh}/shortcuts")}
    for esquema in ESQUEMAS:
        if esquema in existentes:
            print(f"Acceso directo {esquema} ya existe.")
            continue
        cuerpo = {"path": "Tables", "name": esquema,
                  "target": {"adlsGen2": {"location": SERVIDOR, "subpath": f"/{CONTENEDOR}/oro/{esquema}",
                                          "connectionId": conexion}}}
        for intento in range(1, 16):      # el rol de Azure puede tardar hasta ~10 min en aplicarse
            try:
                f.pedir("POST", f"/workspaces/{w['id']}/items/{lh}/shortcuts", cuerpo)
                break
            except RuntimeError as e:
                if "denied" not in str(e) or intento == 15:
                    raise
                print(f"Acceso a oro/{esquema} todavía denegado (intento {intento}); espero 60 s.")
                time.sleep(60)
        print(f"Acceso directo de esquema {esquema} -> oro/{esquema}")


def paso_revisar(f: Fabric, w: dict, lh: str) -> None:
    d = f.pedir("GET", f"/workspaces/{w['id']}/lakehouses/{lh}")
    sql = d.get("properties", {}).get("sqlEndpointProperties", {})
    print(f"Punto de conexión SQL: {sql.get('connectionString')} (estado {sql.get('provisioningStatus')})")
    # Sin esta sincronización, el punto de conexión SQL tarda en ver las tablas de los accesos directos.
    tablas = f.pedir("POST", f"/workspaces/{w['id']}/sqlEndpoints/{sql['id']}/refreshMetadata", {}).get("value", [])
    for x in tablas:
        print(f"  tabla {x['tableName']}: {x['status']}")
    for s in f.todos(f"/workspaces/{w['id']}/items/{lh}/shortcuts"):
        print(f"  {s['path']}/{s['name']} -> {json.dumps(s['target'].get('adlsGen2', s['target']))}")


# --------------------------------------------------------------------------- modelo e informe

def _partes(carpeta: Path, cambiar=None) -> list[dict]:
    """Archivos de un elemento del PBIP como partes de definición (sin .pbi/ ni .platform)."""
    partes = []
    for archivo in sorted(carpeta.rglob("*")):
        rel = archivo.relative_to(carpeta).as_posix()
        if not archivo.is_file() or rel.startswith(".pbi/") or rel == ".platform":
            continue
        contenido = archivo.read_bytes()
        if cambiar:
            contenido = cambiar(rel, contenido)
        partes.append({"path": rel, "payload": base64.b64encode(contenido).decode(), "payloadType": "InlineBase64"})
    return partes


def _particion_directlake(tabla: str) -> str:
    return (f"\tpartition {tabla} = entity\r\n\t\tmode: directLake\r\n\t\tsource\r\n"
            f"\t\t\tentityName: {tabla}\r\n\t\t\tschemaName: {ESQUEMA_DE[tabla]}\r\n"
            f"\t\t\texpressionSource: DatabaseQuery\r\n\r\n")


def tmdl_directlake(rel: str, contenido: bytes, servidor: str, id_sql: str) -> bytes:
    """Convierte un archivo TMDL del modelo de importación (vistas de Synapse) a Direct Lake sobre el lakehouse."""
    texto = contenido.decode("utf-8-sig")
    if rel == "definition/expressions.tmdl":
        texto = ("expression DatabaseQuery =\r\n\t\tlet\r\n"
                 f"\t\t    database = Sql.Database(\"{servidor}\", \"{id_sql}\")\r\n"
                 "\t\tin\r\n\t\t    database\r\n"
                 f"\tlineageTag: {uuid.uuid5(uuid.NAMESPACE_URL, 'tfm-directlake')}\r\n\r\n"
                 "\tannotation PBI_IncludeFutureArtifacts = False\r\n\r\n")
    elif rel == "definition/model.tmdl":
        texto = re.sub(r"annotation PBI_QueryOrder = .*\r?\n\r?\n", "", texto)
    elif rel.startswith("definition/tables/"):
        tabla = Path(rel).stem
        if tabla not in ESQUEMA_DE:
            raise SystemExit(f"La tabla {tabla} del PBIP no tiene esquema en ESQUEMA_DE (infra/fabric.py)")
        texto = re.sub(r"\tpartition [^\r\n]*? = m\r?\n(?:\t\t[^\r\n]*\r?\n|\r?\n)*",
                       lambda _: _particion_directlake(tabla), texto, count=1)
        for (t, col), tipo in TIPOS_DELTA.items():
            if t == tabla:
                texto = re.sub(rf"(\tcolumn {col}\r?\n\t\tdataType: )\w+", rf"\g<1>{tipo}", texto)
        if "mode: import" in texto or "Sql.Database(Servidor" in texto:
            raise SystemExit(f"No se pudo convertir la partición de {tabla}")
    return texto.encode("utf-8")


def _buscar_item(f: Fabric, w: dict, tipo: str, nombre: str) -> str | None:
    return next((i["id"] for i in f.todos(f"/workspaces/{w['id']}/items?type={tipo}")
                 if i["displayName"] == nombre), None)


def _crear_o_actualizar(f: Fabric, w: dict, tipo: str, ruta: str, nombre: str, definicion: dict) -> str:
    existente = _buscar_item(f, w, tipo, nombre)
    if existente:
        f.pedir("POST", f"/workspaces/{w['id']}/{ruta}/{existente}/updateDefinition", {"definition": definicion})
        print(f"{tipo} {nombre} actualizado: {existente}")
        return existente
    f.pedir("POST", f"/workspaces/{w['id']}/{ruta}", {"displayName": nombre, "definition": definicion})
    nuevo = _buscar_item(f, w, tipo, nombre)
    print(f"{tipo} {nombre} creado: {nuevo}")
    return nuevo


def paso_modelo(f: Fabric, w: dict, lh: str) -> str:
    sql = f.pedir("GET", f"/workspaces/{w['id']}/lakehouses/{lh}")["properties"]["sqlEndpointProperties"]
    partes = _partes(PBIP / f"{NOMBRE}.SemanticModel",
                     lambda rel, c: tmdl_directlake(rel, c, sql["connectionString"], sql["id"])
                     if rel.endswith(".tmdl") else c)
    modelo = _crear_o_actualizar(f, w, "SemanticModel", "semanticModels", NOMBRE, {"format": "TMDL", "parts": partes})
    # Direct Lake: «enmarcar» la versión actual de las tablas (después lo hace solo al cambiar oro).
    token = f.cred.get_token("https://analysis.windows.net/powerbi/api/.default").token
    r = f.http.post(f"https://api.powerbi.com/v1.0/myorg/groups/{w['id']}/datasets/{modelo}/refreshes",
                    headers={"Authorization": f"Bearer {token}"}, json={"type": "full"})
    print(f"Actualización del modelo solicitada: HTTP {r.status_code} {r.text[:300]}")
    return modelo


def paso_informe(f: Fabric, w: dict, modelo: str) -> str:
    pbir = {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
            "version": "4.0", "datasetReference": {"byConnection": {"connectionString": f"semanticmodelid={modelo}"}}}

    def cambiar(rel, c):
        return json.dumps(pbir, indent=2).encode() if rel == "definition.pbir" else c
    partes = _partes(PBIP / f"{NOMBRE}.Report", cambiar)
    return _crear_o_actualizar(f, w, "Report", "reports", NOMBRE, {"parts": partes})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--area", required=True, help="nombre o id del área de trabajo de Fabric")
    ap.add_argument("--pasos", default=",".join(PASOS))
    args = ap.parse_args(argv)
    pasos = [p.strip() for p in args.pasos.split(",") if p.strip()]
    f = Fabric()
    w = buscar_area(f, args.area)
    print(f"Área: {w['displayName']} ({w['id']}), capacidad {w.get('capacityId')}")
    if "identidad" in pasos or "permiso" in pasos:
        w = paso_identidad(f, w)
    if "permiso" in pasos:
        paso_permiso(w)
    conexion = paso_conexion(f) if {"conexion", "atajos"} & set(pasos) else None
    lh = paso_lakehouse(f, w) if {"lakehouse", "atajos", "revisar"} & set(pasos) else None
    if "atajos" in pasos:
        paso_atajos(f, w, lh, conexion)
    if "revisar" in pasos:
        paso_revisar(f, w, lh)
    modelo = None
    if "modelo" in pasos:
        lh = lh or paso_lakehouse(f, w)
        modelo = paso_modelo(f, w, lh)
    if "informe" in pasos:
        modelo = modelo or _buscar_item(f, w, "SemanticModel", NOMBRE)
        if not modelo:
            raise SystemExit("Falta el modelo semántico: ejecute antes el paso modelo")
        paso_informe(f, w, modelo)
    return 0


if __name__ == "__main__":
    sys.exit(main())

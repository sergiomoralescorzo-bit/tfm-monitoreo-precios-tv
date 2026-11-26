"""Valida cada JSON del PBIP contra el esquema de su "$schema" (resolviendo $ref remotos, con caché)."""
import json
import sys
import urllib.request
from pathlib import Path

from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

CACHE = Path(__file__).parent / ".cache_esquemas"
CACHE.mkdir(parents=True, exist_ok=True)


def a_raw(url: str) -> str:
    return url.replace("https://developer.microsoft.com/json-schemas/",
                       "https://raw.githubusercontent.com/microsoft/json-schemas/main/")


def bajar(url: str) -> dict:
    archivo = CACHE / (a_raw(url).split("/main/")[1].replace("/", "_"))
    if not archivo.exists():
        with urllib.request.urlopen(a_raw(url), timeout=60) as r:
            archivo.write_bytes(r.read())
    return json.loads(archivo.read_text(encoding="utf-8-sig"))


def recuperar(uri: str):
    return Resource.from_contents(bajar(uri), default_specification=DRAFT7)


registro = Registry(retrieve=recuperar)
errores = 0
archivos = sorted(Path(sys.argv[1]).rglob("*.json")) + sorted(Path(sys.argv[1]).rglob("*.pbi[rp]")) + \
    sorted(Path(sys.argv[1]).rglob("*.pbism"))
for f in archivos:
    datos = json.loads(f.read_text(encoding="utf-8"))
    url = datos.get("$schema")
    if not url:
        continue
    esquema = bajar(url)
    esquema.setdefault("$id", url)
    v = Draft7Validator(esquema, registry=registro)
    lista = sorted(v.iter_errors(datos), key=lambda e: list(e.path))
    for e in lista[:3]:
        print(f"ERROR {f.relative_to(sys.argv[1])}: {'/'.join(map(str, e.path))}: {e.message[:200]}")
    errores += len(lista)
print(f"{len(archivos)} archivos, {errores} errores")

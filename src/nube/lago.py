# -*- coding: utf-8 -*-
"""Sincronización de la raíz de datos local con ADLS Gen2 (Etapa 3).

Cuenta `sttfmwebscraping`, contenedor `datalake-tfm`. La captura deja los archivos originales en la
zona de aterrizaje de Bronce, con la estructura que definió el equipo (id = AAAAMMDDTHHMMSS_xxxxxx,
hora de Colombia; ts = AAAAMMDD_HHMMSS):

    local (data/)                                   lago: bronce/aterrizaje/{sitio}/...
    capturas/{sitio}/fecha=F/{id}.csv          ->   crudo/AAAA/MM/DD/productos_{sitio}_{ts}.csv     tabla de productos
    bronze/{sitio}/fecha=F/{id}/{archivo}.gz   ->   capturas/AAAA/MM/DD/{id}/{archivo}.gz           respuestas (evidencia)
    ejecuciones/ejecuciones.csv (fila del id)  ->   ejecuciones/ejecucion_{ts}.json
    estado/objetivos_{sitio}.csv               ->   estado/ultimo_estado.json
    data/maestro/maestro_televisores.csv       ->   bronce/aterrizaje/maestro/televisores/maestro_televisores.csv

Antes de una corrida se baja `estado/` (fichas descubiertas, para el modo seguimiento); al final
se sube solo lo que produjo esa corrida. Las capas siguientes (bronce/conformidad, plata, oro)
las escribe Spark (src/medallon).

Credenciales: TFM_ADLS_CONEXION (cadena de conexión) o, si no existe, DefaultAzureCredential
(identidad administrada en Container Apps; `az login` en el equipo local).

Uso local (sube el maestro y el código que usan los notebooks):
    python -m src.nube.lago maestro
    python -m src.nube.lago codigo
    python -m src.nube.lago historica --ids 20261013T223816_ac564b,...   # corrida local anterior, sin estado
"""
import argparse
import csv
import io
import json
import logging
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

log = logging.getLogger("lago")

CUENTA = "sttfmwebscraping"
CONTENEDOR = "datalake-tfm"
ATERRIZAJE = "bronce/aterrizaje"
CODIGO = "codigo/tfm_src.zip"
RAIZ_PROYECTO = Path(__file__).resolve().parents[2]


class Destino(Protocol):
    def subir(self, contenido: bytes, remota: str) -> None: ...
    def bajar(self, remota: str) -> bytes | None: ...
    def listar(self, prefijo: str) -> dict[str, int]: ...


class DestinoLocal:
    """Carpeta que imita al lago (pruebas y ensayos sin Azure)."""

    def __init__(self, raiz: Path):
        self.raiz = Path(raiz)

    def subir(self, contenido: bytes, remota: str) -> None:
        destino = self.raiz / remota
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(contenido)

    def bajar(self, remota: str) -> bytes | None:
        ruta = self.raiz / remota
        return ruta.read_bytes() if ruta.exists() else None

    def listar(self, prefijo: str) -> dict[str, int]:
        """Archivos bajo `prefijo` -> tamaño en bytes."""
        carpeta = self.raiz / prefijo
        return {p.relative_to(self.raiz).as_posix(): p.stat().st_size
                for p in carpeta.rglob("*") if p.is_file()} if carpeta.exists() else {}


class DestinoADLS:
    def __init__(self, cuenta: str = CUENTA, contenedor: str = CONTENEDOR):
        from azure.storage.filedatalake import DataLakeServiceClient

        conexion = os.environ.get("TFM_ADLS_CONEXION")
        if conexion:
            servicio = DataLakeServiceClient.from_connection_string(conexion)
        else:
            from azure.identity import DefaultAzureCredential
            servicio = DataLakeServiceClient(f"https://{cuenta}.dfs.core.windows.net",
                                             credential=DefaultAzureCredential())
        self.fs = servicio.get_file_system_client(contenedor)

    def subir(self, contenido: bytes, remota: str) -> None:
        self.fs.get_file_client(remota).upload_data(contenido, overwrite=True)

    def bajar(self, remota: str) -> bytes | None:
        from azure.core.exceptions import ResourceNotFoundError
        try:
            return self.fs.get_file_client(remota).download_file().readall()
        except ResourceNotFoundError:
            return None

    def listar(self, prefijo: str) -> dict[str, int]:
        from azure.core.exceptions import ResourceNotFoundError
        try:
            return {r.name: r.content_length for r in self.fs.get_paths(path=prefijo, recursive=True)
                    if not r.is_directory}
        except ResourceNotFoundError:
            return {}


def destino_desde_entorno() -> Destino:
    return DestinoADLS(os.environ.get("TFM_ADLS_CUENTA", CUENTA), os.environ.get("TFM_ADLS_CONTENEDOR", CONTENEDOR))


# --------------------------------------------------------------------------- rutas

def ruta_estado(sitio: str) -> str:
    return f"{ATERRIZAJE}/{sitio}/estado/ultimo_estado.json"


def _marca_tiempo(id_ejecucion: str) -> str:
    """'20261014T080000_abc123' -> '20261014_080000'."""
    return id_ejecucion[:15].replace("T", "_")


def _carpeta_fecha(particion: str) -> str:
    """'fecha=2026-10-14' -> '2026/10/14'."""
    return particion.removeprefix("fecha=").replace("-", "/")


def ruta_en_lago(relativa: str) -> str:
    """Ruta local relativa a la raíz de datos -> ruta en el lago (ver tabla del encabezado)."""
    capa, sitio, *resto = relativa.split("/")
    if capa == "capturas" and len(resto) == 2:
        fecha, archivo = resto
        ts = _marca_tiempo(archivo.removesuffix(".csv"))
        return f"{ATERRIZAJE}/{sitio}/crudo/{_carpeta_fecha(fecha)}/productos_{sitio}_{ts}.csv"
    if capa == "bronze" and len(resto) == 3:
        fecha, id_ejecucion, archivo = resto
        return f"{ATERRIZAJE}/{sitio}/capturas/{_carpeta_fecha(fecha)}/{id_ejecucion}/{archivo}"
    raise ValueError(f"Ruta sin destino en el lago: {relativa}")


def ruta_ejecucion(sitio: str, id_ejecucion: str) -> str:
    return f"{ATERRIZAJE}/{sitio}/ejecuciones/ejecucion_{_marca_tiempo(id_ejecucion)}.json"


def sitios_terminados(destino: "Destino", sitios: list[str], dia: str) -> dict[str, str]:
    """Sitios que ya tienen una ejecución EXITOSA o PARCIAL el `dia` ('AAAAMMDD', hora de Colombia) -> estado.

    Lo usa el reintento automático de la corrida diaria: un sitio que ya subió sus datos no se vuelve a
    consultar el mismo día (menos peticiones a la tienda y un reintento más corto)."""
    terminados = {}
    for sitio in sitios:
        for ruta in sorted(destino.listar(f"{ATERRIZAJE}/{sitio}/ejecuciones")):
            if not ruta.rsplit("/", 1)[-1].startswith(f"ejecucion_{dia}_"):
                continue
            try:
                estado = json.loads(destino.bajar(ruta) or b"{}").get("estado")
            except ValueError:
                continue
            if estado in ("EXITOSA", "PARCIAL"):
                terminados[sitio] = estado
    return terminados


# --------------------------------------------------------------------------- estado (CSV local <-> JSON en el lago)

def estado_a_json(sitio: str, texto_csv: str) -> bytes:
    objetivos = list(csv.DictReader(io.StringIO(texto_csv), delimiter=";"))
    return json.dumps({"sitio": sitio, "actualizado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "fichas": len(objetivos), "objetivos": objetivos}, ensure_ascii=False, indent=1).encode("utf-8")


def estado_a_csv(contenido: bytes) -> str:
    salida = io.StringIO()
    w = csv.DictWriter(salida, fieldnames=["clave", "url"], delimiter=";", lineterminator="\n")
    w.writeheader()
    w.writerows({"clave": o["clave"], "url": o["url"]} for o in json.loads(contenido)["objetivos"])
    return salida.getvalue()


# --------------------------------------------------------------------------- sincronización

def bajar_estado(destino: Destino, raiz: Path, sitios: list[str]) -> int:
    """Copia el estado de cada sitio del lago a `estado/` local. Devuelve cuántos archivos bajó."""
    n = 0
    for sitio in sitios:
        contenido = destino.bajar(ruta_estado(sitio))
        if contenido is not None:
            ruta = Path(raiz) / "estado" / f"objetivos_{sitio}.csv"
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(estado_a_csv(contenido), encoding="utf-8")
            n += 1
    return n


def archivos_de_corrida(raiz: Path, id_ejecucion: str, sitios: list[str] | None = None) -> list[Path]:
    """Archivos locales que produjo la corrida `id_ejecucion` (respuestas y tabla de productos).
    Con `sitios`, solo los de esos sitios."""
    raiz = Path(raiz)
    archivos: list[Path] = []
    for sitio in ["*"] if sitios is None else sitios:
        archivos += [p for p in (raiz / "bronze").glob(f"{sitio}/fecha=*/{id_ejecucion}/*") if p.is_file()]
        archivos += list((raiz / "capturas").glob(f"{sitio}/fecha=*/{id_ejecucion}.csv"))
    return sorted(archivos)


def ejecuciones_por_sitio(raiz: Path, id_ejecucion: str) -> dict[str, dict]:
    """Fila de `ejecuciones/ejecuciones.csv` de esa corrida para cada sitio."""
    ruta = Path(raiz) / "ejecuciones" / "ejecuciones.csv"
    if not ruta.exists():
        return {}
    with open(ruta, encoding="utf-8") as f:
        return {r["sitio"]: r for r in csv.DictReader(f, delimiter=";") if r["id_ejecucion"] == id_ejecucion}


def ejecucion_a_json(fila: dict) -> bytes:
    """Fila del CSV -> JSON con tipos (números y fechas), validada con el modelo de la Etapa 2."""
    from src.extraccion.modelos import RegistroEjecucion
    return RegistroEjecucion(**{k: v for k, v in fila.items() if v != ""}).model_dump_json(indent=1).encode("utf-8")


def subir_corrida(destino: Destino, raiz: Path, id_ejecucion: str, con_estado: bool = True,
                  sitios: list[str] | None = None) -> int:
    """Sube lo producido por la corrida y, si `con_estado`, el estado vigente. Devuelve cuántos archivos subió.

    Una corrida histórica (anterior a la última del lago) se sube sin estado, para no reemplazar
    las fichas descubiertas más recientes. Con `sitios`, sube solo lo de esos sitios: la tarea del
    contenedor sube cada sitio al terminar, para que un corte posterior (memoria, tiempo) no lo pierda.
    """
    raiz = Path(raiz)
    archivos = archivos_de_corrida(raiz, id_ejecucion, sitios)
    for i, p in enumerate(archivos, 1):
        destino.subir(p.read_bytes(), ruta_en_lago(p.relative_to(raiz).as_posix()))
        if i % 500 == 0:
            log.info("%d/%d archivos subidos", i, len(archivos))
    estados = sorted((raiz / "estado").glob("objetivos_*.csv")) if con_estado else []
    if sitios is not None:
        estados = [p for p in estados if p.stem.removeprefix("objetivos_") in sitios]
    for p in estados:
        sitio = p.stem.removeprefix("objetivos_")
        destino.subir(estado_a_json(sitio, p.read_text(encoding="utf-8")), ruta_estado(sitio))
    ejecuciones = ejecuciones_por_sitio(raiz, id_ejecucion)
    if sitios is not None:
        ejecuciones = {k: v for k, v in ejecuciones.items() if k in sitios}
    for sitio, fila in ejecuciones.items():
        destino.subir(ejecucion_a_json(fila), ruta_ejecucion(sitio, id_ejecucion))
    return len(archivos) + len(estados) + len(ejecuciones)


def subir_maestro(destino: Destino, ruta: Path = RAIZ_PROYECTO / "data" / "maestro" / "maestro_televisores.csv") -> str:
    remota = f"{ATERRIZAJE}/maestro/televisores/{ruta.name}"
    destino.subir(ruta.read_bytes(), remota)
    return remota


def empaquetar_codigo() -> bytes:
    """`src/catalogo` en un zip, para que los notebooks lo importen con `sc.addPyFile`."""
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted((RAIZ_PROYECTO / "src").rglob("*.py")):
            relativa = p.relative_to(RAIZ_PROYECTO).as_posix()
            if relativa.startswith(("src/catalogo/", "src/medallon/")) or relativa == "src/__init__.py":
                z.write(p, relativa)
    return memoria.getvalue()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("accion", choices=["maestro", "codigo", "historica"])
    ap.add_argument("--ids", help="historica: ids de corrida separados por coma (se suben sin estado)")
    ap.add_argument("--raiz", default=str(RAIZ_PROYECTO / "data"), help="historica: raíz de datos local")
    ap.add_argument("--lago-local", help="carpeta que reemplaza a ADLS (ensayo sin Azure)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("azure").setLevel(logging.WARNING)
    destino = DestinoLocal(Path(args.lago_local)) if args.lago_local else destino_desde_entorno()
    if args.accion == "historica":
        if not args.ids:
            ap.error("historica necesita --ids")
        for id_ejecucion in [i.strip() for i in args.ids.split(",") if i.strip()]:
            print(id_ejecucion, "->", subir_corrida(destino, Path(args.raiz), id_ejecucion, con_estado=False), "archivos")
    elif args.accion == "maestro":
        print("Maestro subido a", subir_maestro(destino))
    else:
        destino.subir(empaquetar_codigo(), CODIGO)
        print("Código subido a", CODIGO)
    return 0


if __name__ == "__main__":
    sys.exit(main())

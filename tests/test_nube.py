# -*- coding: utf-8 -*-
"""Pruebas de la Etapa 3: sincronización con el lago, usando una carpeta que imita a ADLS."""
import io
import json
import zipfile
from pathlib import Path

import pytest

from src.nube import lago

ID = "20261014T080000_abc123"
OTRO = "20261013T060000_zzz999"
A = "bronce/aterrizaje"
EJEC = "id_ejecucion;sitio;modo;inicio;fin;duracion_s;ok;estado;mensaje\n"


def crear(ruta: Path, texto: str = "x") -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")


def raiz_con_corridas(raiz: Path) -> None:
    for id_ in (ID, OTRO):
        fecha = f"{id_[:4]}-{id_[4:6]}-{id_[6:8]}"
        crear(raiz / "bronze" / "jumbo" / f"fecha={fecha}" / id_ / "00001_tv.json.gz")
        crear(raiz / "capturas" / "jumbo" / f"fecha={fecha}" / f"{id_}.csv")
    crear(raiz / "estado" / "objetivos_jumbo.csv", "clave;url\na;https://x/a\nb;https://x/b\n")
    crear(raiz / "ejecuciones" / "ejecuciones.csv", EJEC
          + f"{OTRO};jumbo;seguimiento;2026-10-13T11:00:00Z;;;5;EXITOSA;\n"
          + f"{ID};jumbo;completo;2026-10-14T13:00:00Z;2026-10-14T13:03:00Z;180.5;76;EXITOSA;ok\n"
          + f"{ID};exito;completo;2026-10-14T13:00:00Z;;;0;FALLIDA;sin datos\n")


@pytest.mark.parametrize("local, remota", [
    (f"capturas/exito/fecha=2026-10-14/{ID}.csv", f"{A}/exito/crudo/2026/10/14/productos_exito_20261014_080000.csv"),
    (f"bronze/jumbo/fecha=2026-10-14/{ID}/00001_tv.json.gz", f"{A}/jumbo/capturas/2026/10/14/{ID}/00001_tv.json.gz"),
])
def test_ruta_en_lago(local, remota):
    assert lago.ruta_en_lago(local) == remota


def test_rutas_de_estado_y_ejecucion():
    assert lago.ruta_estado("olimpica") == f"{A}/olimpica/estado/ultimo_estado.json"
    assert lago.ruta_ejecucion("exito", ID) == f"{A}/exito/ejecuciones/ejecucion_20261014_080000.json"


def test_ruta_sin_destino():
    with pytest.raises(ValueError):
        lago.ruta_en_lago("informes/informe.md")


def test_archivos_de_corrida_solo_incluye_esa_corrida(tmp_path):
    raiz_con_corridas(tmp_path)
    rutas = {p.relative_to(tmp_path).as_posix() for p in lago.archivos_de_corrida(tmp_path, ID)}
    assert rutas == {f"bronze/jumbo/fecha=2026-10-14/{ID}/00001_tv.json.gz", f"capturas/jumbo/fecha=2026-10-14/{ID}.csv"}


def test_subir_corrida_y_bajar_estado(tmp_path):
    local, nube = tmp_path / "local", tmp_path / "nube"
    raiz_con_corridas(local)
    destino = lago.DestinoLocal(nube)

    assert lago.subir_corrida(destino, local, ID) == 5   # 2 archivos + estado + ejecuciones de 2 sitios

    assert (nube / A / "jumbo/crudo/2026/10/14/productos_jumbo_20261014_080000.csv").exists()
    assert (nube / A / f"jumbo/capturas/2026/10/14/{ID}/00001_tv.json.gz").exists()
    assert not (nube / A / "jumbo/crudo/2026/10/13").exists()
    ejec = json.loads((nube / A / "jumbo/ejecuciones/ejecucion_20261014_080000.json").read_text(encoding="utf-8"))
    assert (ejec["id_ejecucion"], ejec["ok"], ejec["duracion_s"], ejec["estado"]) == (ID, 76, 180.5, "EXITOSA")
    estado = json.loads((nube / A / "jumbo/estado/ultimo_estado.json").read_text(encoding="utf-8"))
    assert estado["fichas"] == 2 and estado["objetivos"][0] == {"clave": "a", "url": "https://x/a"}

    otra = tmp_path / "contenedor_nuevo"
    assert lago.bajar_estado(destino, otra, ["jumbo", "exito"]) == 1
    assert (otra / "estado/objetivos_jumbo.csv").read_text(encoding="utf-8") == "clave;url\na;https://x/a\nb;https://x/b\n"


def test_corrida_historica_no_reemplaza_el_estado(tmp_path):
    local, nube = tmp_path / "local", tmp_path / "nube"
    raiz_con_corridas(local)
    crear(nube / A / "jumbo/estado/ultimo_estado.json", "vigente")

    assert lago.main(["historica", "--ids", OTRO, "--raiz", str(local), "--lago-local", str(nube)]) == 0

    assert (nube / A / "jumbo/crudo/2026/10/13/productos_jumbo_20261013_060000.csv").exists()
    assert (nube / A / "jumbo/ejecuciones/ejecucion_20261013_060000.json").exists()
    assert (nube / A / "jumbo/estado/ultimo_estado.json").read_text(encoding="utf-8") == "vigente"


def test_sin_ejecuciones(tmp_path):
    assert lago.ejecuciones_por_sitio(tmp_path, ID) == {}


def test_maestro_va_a_televisores(tmp_path):
    maestro = tmp_path / "maestro_televisores.csv"
    maestro.write_text("x", encoding="utf-8")
    assert lago.subir_maestro(lago.DestinoLocal(tmp_path / "nube"), maestro) == f"{A}/maestro/televisores/maestro_televisores.csv"


def test_paquete_de_codigo_para_spark():
    with zipfile.ZipFile(io.BytesIO(lago.empaquetar_codigo())) as z:
        nombres = set(z.namelist())
    assert {"src/__init__.py", "src/catalogo/emparejamiento.py", "src/medallon/plata.py"} <= nombres
    assert not any(n.startswith("src/extraccion/") for n in nombres)


# --------------------------------------------------------------------------- job de medallón (sin Spark)

def test_medallon_baja_solo_lo_que_lee_spark(tmp_path):
    from src.nube import tarea_medallon as tm
    nube = tmp_path / "nube"
    for r in [f"{A}/jumbo/crudo/2026/10/14/p.csv", f"{A}/jumbo/ejecuciones/e.json", f"{A}/maestro/televisores/m.csv",
              f"{A}/jumbo/capturas/2026/10/14/{ID}/00001.json.gz", f"{A}/jumbo/estado/ultimo_estado.json",
              "bronce/conformidad/jumbo/productos/fecha=2026-10-14/part-0.parquet",
              "bronce/conformidad/jumbo/productos/_delta_log/00000000000000000000.json",
              "plata/precios/ofertas/part-0.parquet", "plata/precios/ofertas/_delta_log/00000000000000000000.json"]:
        crear(nube / r)
    local = tmp_path / "local"
    assert tm.bajar(lago.DestinoLocal(nube), local, ["jumbo"])[0] == 6
    assert not (local / f"{A}/jumbo/capturas").exists() and not (local / f"{A}/jumbo/estado").exists()
    assert not (local / "plata/precios/ofertas/part-0.parquet").exists()
    assert (local / "plata/precios/ofertas/_delta_log/00000000000000000000.json").exists()


def test_medallon_sube_cambios_con_el_log_al_final(tmp_path):
    from src.nube import tarea_medallon as tm
    local = tmp_path / "local"
    crear(local / "oro/hechos/f/_delta_log/00000000000000000000.json")
    crear(local / "oro/hechos/f/viejo.parquet")
    antes = tm.huella(local)
    crear(local / "oro/hechos/f/_delta_log/00000000000000000001.json")
    crear(local / "oro/hechos/f/part-1.parquet")
    crear(local / "oro/hechos/f/.part-1.parquet.crc")
    crear(local / f"{A}/jumbo/crudo/x.csv")                     # entrada: nunca se sube

    subidas = []

    class Registro(lago.DestinoLocal):
        def subir(self, contenido, remota):
            subidas.append(remota)

    assert tm.subir(Registro(tmp_path / "nube"), local, antes)[0] == 2
    assert subidas == ["oro/hechos/f/part-1.parquet", "oro/hechos/f/_delta_log/00000000000000000001.json"]


def test_subir_corrida_por_sitio(tmp_path):
    local, nube = tmp_path / "local", tmp_path / "nube"
    raiz_con_corridas(local)
    crear(local / "bronze" / "exito" / "fecha=2026-10-14" / ID / "00001_tv.html.gz")
    crear(local / "estado" / "objetivos_exito.csv", "clave;url\nc;https://x/c\n")
    destino = lago.DestinoLocal(nube)

    assert lago.subir_corrida(destino, local, ID, sitios=["jumbo"]) == 4   # 2 archivos + estado + ejecución
    assert not (nube / A / "exito").exists()
    assert lago.subir_corrida(destino, local, ID, sitios=["exito"]) == 3   # 1 archivo + estado + ejecución
    assert (nube / A / f"exito/capturas/2026/10/14/{ID}/00001_tv.html.gz").exists()
    assert lago.subir_corrida(destino, local, ID, sitios=[]) == 0


def _ejecucion(destino, sitio, marca, estado):
    destino.subir(json.dumps({"sitio": sitio, "estado": estado}).encode(),
                  f"{lago.ATERRIZAJE}/{sitio}/ejecuciones/ejecucion_{marca}.json")


def test_sitios_terminados_solo_del_dia_y_con_datos(tmp_path):
    d = lago.DestinoLocal(tmp_path)
    _ejecucion(d, "alkosto", "20261119_060108", "EXITOSA")
    _ejecucion(d, "exito", "20261119_060108", "PARCIAL")
    _ejecucion(d, "jumbo", "20261119_060108", "FALLIDA")
    _ejecucion(d, "olimpica", "20261118_060108", "EXITOSA")       # otro día
    assert lago.sitios_terminados(d, ["alkosto", "exito", "jumbo", "olimpica", "ktronix"], "20261119") == {
        "alkosto": "EXITOSA", "exito": "PARCIAL"}


def test_reintento_no_repite_los_sitios_terminados(tmp_path, monkeypatch):
    from src.nube import tarea
    d = lago.DestinoLocal(tmp_path / "lago")
    hoy = tarea.ahora()[1].strftime("%Y%m%d")
    _ejecucion(d, "alkosto", f"{hoy}_060108", "EXITOSA")
    pedidos = []

    async def falso_ejecutar(sitios, *a, **k):
        pedidos.append(list(sitios))
        return []
    monkeypatch.setattr(tarea, "ejecutar", falso_ejecutar)
    monkeypatch.setattr(tarea.lago, "bajar_estado", lambda *a: 0)
    base = ["--lago-local", str(tmp_path / "lago"), "--datos", str(tmp_path / "w"), "--sitios", "alkosto,jumbo"]
    assert tarea.main(base) == 0
    assert tarea.main(base + ["--repetir"]) == 0
    assert tarea.main(base[:-1] + ["alkosto"]) == 0                  # nada que hacer: no llama a ejecutar
    assert pedidos == [["jumbo"], ["alkosto", "jumbo"]]

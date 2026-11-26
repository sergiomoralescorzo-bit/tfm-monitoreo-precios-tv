# -*- coding: utf-8 -*-
"""Capa Bronze local: guarda cada respuesta cruda comprimida (RF-03).

Estructura (la misma que tendrá el contenedor de ADLS Gen2 en la Etapa 3):
    bronze/{sitio}/fecha={AAAA-MM-DD}/{id_ejecucion}/{nnnnn}_{clave}.{ext}.gz
"""
import gzip
import re
from pathlib import Path


class AlmacenBronze:
    def __init__(self, raiz: Path, sitio: str, fecha: str, id_ejecucion: str):
        self.raiz = Path(raiz)
        self.relativa = Path("bronze") / sitio / f"fecha={fecha}" / id_ejecucion
        self.carpeta = self.raiz / self.relativa
        self.contador = 0

    def guardar(self, clave: str, contenido: bytes | str, ext: str) -> str:
        """Guarda el contenido y devuelve la ruta relativa a la raíz de datos (para `ruta_bronze`)."""
        self.carpeta.mkdir(parents=True, exist_ok=True)
        self.contador += 1
        clave = re.sub(r"[^A-Za-z0-9_.-]+", "_", clave)[-80:]
        nombre = f"{self.contador:05d}_{clave}.{ext}.gz"
        datos = contenido.encode("utf-8") if isinstance(contenido, str) else contenido
        with gzip.open(self.carpeta / nombre, "wb", compresslevel=6) as f:
            f.write(datos)
        return (self.relativa / nombre).as_posix()


def leer(raiz: Path, ruta_relativa: str) -> str:
    with gzip.open(Path(raiz) / ruta_relativa, "rt", encoding="utf-8") as f:
        return f.read()

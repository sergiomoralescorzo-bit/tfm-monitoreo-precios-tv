# -*- coding: utf-8 -*-
"""Rutas del lago `datalake-tfm` (cuenta `sttfmwebscraping`) para las capas del medallón.

    bronce/aterrizaje/{sitio}/crudo/AAAA/MM/DD/productos_{sitio}_{ts}.csv   tabla de productos de cada corrida
    bronce/aterrizaje/{sitio}/capturas/AAAA/MM/DD/{id}/...                  respuestas originales (evidencia)
    bronce/aterrizaje/{sitio}/ejecuciones/ejecucion_{ts}.json
    bronce/aterrizaje/{sitio}/estado/ultimo_estado.json
    bronce/aterrizaje/maestro/televisores/maestro_televisores.csv
    bronce/aterrizaje/revision/                                             decisiones de revisión manual (CSV)
    bronce/aterrizaje/{sitio}/reprocesos/reproceso_{ts}_rN.json           manifiesto de cada reproceso (crudo/..._rN.csv)
    bronce/conformidad/{sitio}/productos|ejecuciones     Delta, mismas columnas (texto) + metadatos de carga
    bronce/conformidad/maestro/televisores
    plata/precios/ofertas                   ofertas tipadas, deduplicadas, clasificadas y emparejadas
    plata/precios/revision_emparejamiento   ofertas emparejadas por REFERENCIA o sin emparejar (revisión manual)
    plata/catalogo/productos                un registro por producto (atributos del maestro o de la tienda)
    plata/control/ejecuciones               registro de ejecuciones tipado
    oro/dimensiones/dim_producto | dim_tienda | dim_calendario
    oro/hechos/fact_precio_diario | fact_ejecucion
    oro/kpis/kpi_brecha_precio | kpi_calidad_captura
    codigo/tfm_src.zip                      paquete Python que carga el notebook
"""

SITIOS = ["alkosto", "ktronix", "jumbo", "olimpica", "exito"]


def base_abfss(cuenta: str = "sttfmwebscraping", contenedor: str = "datalake-tfm") -> str:
    return f"abfss://{contenedor}@{cuenta}.dfs.core.windows.net"


class Rutas:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def aterrizaje(self, sitio: str, tipo: str) -> str:
        return f"{self.base}/bronce/aterrizaje/{sitio}/{tipo}"

    @property
    def maestro_csv(self) -> str:
        return f"{self.base}/bronce/aterrizaje/maestro/televisores/*.csv"

    @property
    def revision_csv(self) -> str:
        return f"{self.base}/bronce/aterrizaje/revision/*.csv"

    def conformidad(self, sitio: str, tabla: str) -> str:
        return f"{self.base}/bronce/conformidad/{sitio}/{tabla}"

    @property
    def conformidad_maestro(self) -> str:
        return f"{self.base}/bronce/conformidad/maestro/televisores"

    def plata(self, tabla: str) -> str:
        return f"{self.base}/plata/{tabla}"

    def oro(self, tabla: str) -> str:
        return f"{self.base}/oro/{tabla}"

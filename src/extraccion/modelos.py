# -*- coding: utf-8 -*-
"""Esquema del registro de captura y del registro de ejecuciones (Etapa 1, secciones 4.1 y 4.2)."""
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class EstadoExtraccion(str, Enum):
    """Estados por producto; amplían los del CoE131 (Disponible, No disponible, URL no disponible...)."""
    OK = "OK"
    SIN_STOCK = "SIN_STOCK"
    NO_ENCONTRADO = "NO_ENCONTRADO"
    ERROR_HTTP = "ERROR_HTTP"
    ERROR_PARSEO = "ERROR_PARSEO"
    BLOQUEADO = "BLOQUEADO"
    PROHIBIDO_ROBOTS = "PROHIBIDO_ROBOTS"


class EstadoEjecucion(str, Enum):
    EXITOSA = "EXITOSA"
    PARCIAL = "PARCIAL"
    FALLIDA = "FALLIDA"


class RegistroCaptura(BaseModel):
    """Una oferta de un producto en un sitio, en un momento dado."""
    id_ejecucion: str
    fecha_captura_utc: datetime
    fecha_captura_col: datetime
    cadena: str
    sitio: str
    sku_tienda: str | None = None
    ean_publicado: str | None = None
    gtin14: str | None = None
    titulo: str | None = None
    marca: str | None = None
    pulgadas: int | None = None
    referencia: str | None = None
    url: str
    vendedor: str | None = None
    es_vendedor_propio: bool | None = None
    precio_lista: int | None = None
    precio_venta: int | None = None
    precio_medio_pago: int | None = None
    disponible: bool | None = None
    stock: int | None = None
    estado_extraccion: EstadoExtraccion
    metodo: str
    ruta_bronze: str | None = None
    mensaje: str | None = None
    # Clasificación previa al emparejamiento (sección 6 de la Etapa 1).
    en_alcance: bool | None = None
    motivo_exclusion: str | None = None

    @property
    def completo(self) -> bool:
        """Registro completo: identificador, precio de venta, descripción y fecha (sección 4.1)."""
        return bool((self.ean_publicado or self.sku_tienda) and self.precio_venta and self.titulo)


class RegistroEjecucion(BaseModel):
    id_ejecucion: str
    sitio: str
    modo: str
    inicio: datetime
    fin: datetime | None = None
    duracion_s: float | None = None
    descubiertos: int = 0
    consultados: int = 0
    ok: int = 0
    sin_stock: int = 0
    no_encontrados: int = 0
    errores: int = 0
    bloqueados: int = 0
    registros: int = 0
    en_alcance: int = 0
    estado: EstadoEjecucion = EstadoEjecucion.FALLIDA
    mensaje: str = Field(default="")

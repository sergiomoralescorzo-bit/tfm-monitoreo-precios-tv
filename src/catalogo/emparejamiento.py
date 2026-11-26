# -*- coding: utf-8 -*-
"""Regla de emparejamiento (Etapa 1, sección 6).

Nivel 1  EAN         el GTIN-14 publicado (válido) es la clave del producto.
Nivel 2  REFERENCIA  sin GTIN válido: misma clave marca|pulgadas|referencia normalizada que un
                     producto con GTIN conocido (maestro u otra tienda). Se aceptan sufijos
                     regionales (HYLED4326 ~ HYLED4326QG) si la coincidencia es única.
—        SIN_EMPAREJAR
"""
from collections import defaultdict

from src.catalogo import atributos_tv, gtin


class IndiceReferencias:
    """Índice clave_referencia -> GTIN-14, con búsqueda exacta y por prefijo único."""

    def __init__(self):
        self._exacto: dict[str, set[str]] = defaultdict(set)
        self._por_grupo: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    def agregar(self, clave: str | None, gtin14: str | None) -> None:
        if not isinstance(clave, str) or not isinstance(gtin14, str):   # NaN de pandas
            return
        self._exacto[clave].add(gtin14)
        grupo, ref = clave.rsplit("|", 1)
        self._por_grupo[grupo][ref].add(gtin14)

    def buscar(self, clave: str | None) -> str | None:
        if not isinstance(clave, str):
            return None
        exacto = self._exacto.get(clave)
        if exacto:
            return next(iter(exacto)) if len(exacto) == 1 else None
        grupo, ref = clave.rsplit("|", 1)
        candidatos = set()
        for otra, gtins in self._por_grupo.get(grupo, {}).items():
            if len(min(ref, otra, key=len)) >= 4 and (otra.startswith(ref) or ref.startswith(otra)):
                candidatos |= gtins
        return next(iter(candidatos)) if len(candidatos) == 1 else None


def clave_de(marca: str | None, pulgadas, referencia: str | None) -> str | None:
    pulg = int(pulgadas) if pulgadas not in (None, "") and pulgadas == pulgadas else None
    marca = marca if isinstance(marca, str) and marca else None
    ref_norm = atributos_tv.referencia_normalizada(referencia, pulg, marca)
    return atributos_tv.clave_referencia(marca, pulg, ref_norm)


def emparejar(ean: str | None, marca: str | None, pulgadas, referencia: str | None,
              indice: IndiceReferencias) -> tuple[str | None, str]:
    """Devuelve (gtin14 del producto, método)."""
    if ean and gtin.es_valido(ean):
        return gtin.a_gtin14(ean), "EAN"
    encontrado = indice.buscar(clave_de(marca, pulgadas, referencia))
    if encontrado:
        return encontrado, "REFERENCIA"
    return None, "SIN_EMPAREJAR"

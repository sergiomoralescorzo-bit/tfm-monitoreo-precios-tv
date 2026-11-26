# -*- coding: utf-8 -*-
"""Normalización y validación de códigos GTIN (EAN-13, UPC-A, GTIN-14).

Apple publica sus equipos con UPC-A (12 dígitos); las tiendas los muestran a veces
con un cero a la izquierda (13 dígitos). Para emparejar se normaliza todo a GTIN-14.
"""
import re

_SOLO_DIGITOS = re.compile(r"\D")


def limpiar(codigo) -> str:
    """Quita todo lo que no sea dígito (espacios, guiones, '.0' de Excel)."""
    if codigo is None:
        return ""
    texto = str(codigo).strip()
    if texto.endswith(".0"):
        texto = texto[:-2]
    return _SOLO_DIGITOS.sub("", texto)


def digito_control(cuerpo: str) -> int:
    """Dígito de control GS1 (módulo 10) para el cuerpo sin el último dígito."""
    total = 0
    for i, c in enumerate(reversed(cuerpo)):
        total += int(c) * (3 if i % 2 == 0 else 1)
    return (10 - total % 10) % 10


def es_valido(codigo) -> bool:
    """True si el código tiene 8, 12, 13 o 14 dígitos y su dígito de control cuadra."""
    c = limpiar(codigo)
    if len(c) not in (8, 12, 13, 14):
        return False
    return digito_control(c[:-1]) == int(c[-1])


def a_gtin14(codigo) -> str | None:
    """Devuelve el GTIN-14 (con ceros a la izquierda) o None si el código no es válido."""
    c = limpiar(codigo)
    if not es_valido(c):
        return None
    return c.zfill(14)

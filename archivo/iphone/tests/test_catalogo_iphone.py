# -*- coding: utf-8 -*-
import pytest

from src.catalogo import atributos as at
from src.catalogo import gtin


@pytest.mark.parametrize("codigo, esperado", [
    ("195951415086", "00195951415086"),     # UPC-A del maestro
    ("0195949821998", "00195949821998"),    # mismo formato publicado por Éxito con cero inicial
    ("195951415086.0", "00195951415086"),   # valor leído desde Excel como número
    ("195951415087", None),                 # dígito de control incorrecto
    ("IZ20001118371", None),                # código interno de marketplace
    ("", None),
])
def test_a_gtin14(codigo, esperado):
    assert gtin.a_gtin14(codigo) == esperado


def test_upc_y_ean13_con_cero_son_el_mismo_producto():
    assert gtin.a_gtin14("195949035913") == gtin.a_gtin14("0195949035913")


@pytest.mark.parametrize("texto, modelo, cap, color", [
    ("iPhone 18 Pro Max 2TB \\Az", "iPhone 18 Pro Max", 2048, "azul"),
    ("Cel 4G iPhone 6Plus 64 GB\\Dr", "iPhone 6 Plus", 64, "dorado"),
    ("Cel4G iPhone XSMax64GB DEMO\\Pl", "iPhone XS Max", 64, "plata"),
    ("iPhone 13 256GB (PRODUCT)RED", "iPhone 13", 256, "rojo"),
    ("Celular Iphone 17 5G 8GB Ram/256GB Blanco", "iPhone 17", 256, "blanco"),
    ("IPhone 17 Pro Max 256GB | 5G | Chip A19 Pro", "iPhone 17 Pro Max", 256, None),
    ("Iphone 16E 128Gb Blanco", "iPhone 16e", 128, "blanco"),
    ("iPhone 16 Plus 128 Rs (Demo)", "iPhone 16 Plus", 128, "rosa"),
])
def test_atributos(texto, modelo, cap, color):
    assert at.modelo(texto) == modelo
    assert at.capacidad_gb(texto) == cap
    assert at.color(texto) == color


def test_banderas():
    assert at.es_demo("iPhone Air 256GB Az (Demo)")
    assert at.es_reacondicionado("Celular Iphone 14 128GB Azul Reacondicionado")
    assert at.es_reacondicionado("Cel4G iPhone 6SPlus Refu SS\\Gr")
    assert not at.es_reacondicionado("iPhone 15 128GB \\Az")

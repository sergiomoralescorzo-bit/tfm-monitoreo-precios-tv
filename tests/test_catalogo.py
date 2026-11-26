# -*- coding: utf-8 -*-
import pytest

from src.catalogo import atributos_tv as at
from src.catalogo import gtin


@pytest.mark.parametrize("codigo, esperado", [
    ("7705191047676", "07705191047676"),    # EAN-13 colombiano (Challenger)
    ("195951415086", "00195951415086"),     # UPC-A
    ("0195949821998", "00195949821998"),    # UPC-A publicado con cero inicial
    ("7705191047676.0", "07705191047676"),  # valor leído desde Excel como número
    ("7705191047677", None),                # dígito de control incorrecto
    ("IZ20001118371", None),                # código interno de marketplace
    ("", None),
])
def test_a_gtin14(codigo, esperado):
    assert gtin.a_gtin14(codigo) == esperado


@pytest.mark.parametrize("texto, marca, pulg, ref_norm", [
    # Descripciones del maestro
    ("TV LG 55\\ 55QNED80SRA 4KUHD", "LG", 55, "QNED80SRA"),
    ("TV CHALLENG 75\\ TG4770 QLED 4K", "CHALLENGER", 75, "TG4770"),
    ("Tv40 101cm LED Sams40H64003DINT", "SAMSUNG", 40, None),
    ("TV 43\\109.2cmLED LG43LF510TFHD", "LG", 43, "LF510T"),
    ("TV HYUNDAI 58\\ 5802 4KUHD", "HYUNDAI", 58, "5802"),
    ("Tv32\\80cmLED Chall 32D27HD T2", "CHALLENGER", 32, "D27"),
    # Títulos de tiendas
    ('Televisor Challenger 75" Pulgadas QLEDG 75TG4770 GOOGLE', "CHALLENGER", 75, "TG4770"),
    ("Televisor Samsung 50 Pulgadas Crystal UHD 4K Un50U8200F", "SAMSUNG", 50, "U8200F"),
    ("Televisor FINLANDEK 58 pulgadas LED Uhd4K Smart TV FILED5801UHDW", "FINLANDEK", 58, None),
    ("Televisor COMPAQ 40 pulgadas LED Fhd Smart TV QLG40EFHD", "COMPAQ", 40, None),
    ('TV LG 55" Pulgadas 139 Cm 55QNED85BSG 4K-UHD QNED Mini LED Smart TV WebOS con IA', "LG", 55, "QNED85BSG"),
])
def test_atributos_tv(texto, marca, pulg, ref_norm):
    m = at.marca(texto)
    p = at.pulgadas(texto)
    assert m == marca
    assert p == pulg
    if ref_norm is not None:
        assert at.referencia_normalizada(at.referencia(texto), p, m) == ref_norm


def test_misma_clave_en_maestro_y_tienda():
    maestro = "TV CHALLEN 65\\ 65TG380 QLED 4K"
    tienda = "Televisor Challenger 65\" Pulgadas QLED 65TG380 BT T2"
    claves = []
    for t in (maestro, tienda):
        m, p = at.marca(t), at.pulgadas(t)
        claves.append(at.clave_referencia(m, p, at.referencia_normalizada(at.referencia(t), p, m)))
    assert claves[0] == claves[1] == "CHALLENGER|65|TG380"


def test_pulgadas_desde_referencia():
    assert at.pulgadas_desde_referencia("UN50CU8200KXZL") == 50
    assert at.pulgadas_desde_referencia("QN77S90C") == 77


def test_exclusiones():
    assert at.es_combo("TV SAMSUNG 58\\ U8500H + Barra")
    assert at.es_combo("Combo Televisor LG 75 Pulgadas QNED MiniLED UHD 4K 75QNED65B")
    assert at.es_no_nuevo("Televisor LG 55 Pulgadas Exhibición")
    assert not at.es_combo("TV LG 65\\ 65UT7300 4KUHD")


@pytest.mark.parametrize("texto, tec, res", [
    ("TV LG 77\\ OLED77C4 OLED 4KUHD", "OLED", "4K"),
    ("TV SAMSUNG 85\\ M80H MiniLD 4K", "Mini LED", "4K"),
    ("TV LG 65\\ 65NANO86 4KUHD", "NanoCell", "4K"),
    ("TV TCL 32\\ S5K FHD QLED", "QLED", "FHD"),
    ("Televisor Samsung 50 Pulgadas Crystal UHD 4K Un50U8200F", "LED", "4K"),
    ("Televisor Olimpo 32 Pulgadas FHD Google TV 32D8300S", None, "FHD"),
])
def test_tecnologia_resolucion(texto, tec, res):
    assert at.tecnologia(texto) == tec
    assert at.resolucion(texto) == res

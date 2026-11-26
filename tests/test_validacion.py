# -*- coding: utf-8 -*-
"""Reglas de la validación y de precios atípicos (Etapa 6), sin Spark."""
from src.medallon import atipicos
from src.validacion import reglas
from src.validacion.metricas import _tabla, resumen_metas


def producto(key, cadena, referencia="UN55U8000F", marca="SAMSUNG", pulgadas=55):
    return {"producto_key": key, "cadena": cadena, "marca": marca, "pulgadas": pulgadas, "referencia": referencia}


def test_pares_perdidos_misma_clave_en_otra_cadena():
    filas = [producto("A", "Éxito"), producto("B", "Jumbo"),            # mismo modelo, GTIN distinto
             producto("C", "Éxito", "QN65Q7F"), producto("C", "Jumbo", "QN65Q7F"),   # ya emparejado
             producto("D", "Éxito", "UN50U8000F", pulgadas=50)]          # solo una cadena, sin par
    salida = reglas.pares_perdidos(filas)
    assert {s["producto_key"] for s in salida} == {"A", "B"}
    assert len({s["clave"] for s in salida}) == 1
    assert salida[0]["cadenas_candidatas"] == "Jumbo"


def test_pares_perdidos_no_une_dentro_de_la_misma_cadena():
    # Alkosto y Ktronix son la misma cadena: dos GTIN del mismo modelo ahí no son un par perdido.
    filas = [producto("A", "Colombiana"), producto("B", "Colombiana")]
    assert reglas.pares_perdidos(filas) == []


def test_pares_perdidos_exige_mismas_pulgadas():
    filas = [producto("A", "Éxito", "U8000F", pulgadas=55), producto("B", "Jumbo", "U8000F", pulgadas=65)]
    assert reglas.pares_perdidos(filas) == []


def test_motivos_atipico():
    assert atipicos.motivos_atipico(2_000_000, 2_500_000, [2_100_000], 1_900_000) == []
    assert atipicos.motivos_atipico(0) == ["SIN_PRECIO"]
    assert "BAJO_RANGO" in atipicos.motivos_atipico(150_000)
    assert "SOBRE_RANGO" in atipicos.motivos_atipico(99_000_000)
    assert "VENTA_MAYOR_QUE_LISTA" in atipicos.motivos_atipico(3_000_000, 2_000_000)
    assert "DESCUENTO_EXCESIVO" in atipicos.motivos_atipico(500_000, 2_000_000)
    assert "LEJOS_DE_OTRAS_CADENAS" in atipicos.motivos_atipico(3_999_997, None, [39_999_900, 41_000_000])
    assert "CAMBIO_BRUSCO" in atipicos.motivos_atipico(1_000_000, None, None, 2_500_000)


def precio(fecha, sitio, cadena, venta, producto="P", disponible=True, lista=None, metodo="EAN"):
    return {"fecha": fecha, "producto_key": producto, "sitio": sitio, "cadena": cadena, "precio_venta": venta,
            "precio_lista": lista, "disponible": disponible, "metodo_emparejamiento": metodo}


def test_marcar_compara_con_dos_o_mas_cadenas_con_stock():
    # El error de notación científica de SAP Commerce (3.999.997 en lugar de 39.999.900) se detecta
    # porque hay otras 2 cadenas con stock; con una sola no se marca a ninguna de las dos.
    dia = [precio(1, "alkosto", "A", 3_999_997), precio(1, "jumbo", "J", 39_999_900),
           precio(1, "exito", "E", 41_000_000), precio(1, "olimpica", "O", 1_000_000, disponible=False)]
    marcadas = {f["sitio"]: f["motivos_atipico"] for f in atipicos.marcar(dia)}
    assert marcadas == {"alkosto": "LEJOS_DE_OTRAS_CADENAS", "jumbo": None, "exito": None, "olimpica": None}
    dos = [precio(1, "alkosto", "A", 1_500_000), precio(1, "exito", "E", 3_200_000)]
    assert all(f["motivos_atipico"] is None for f in atipicos.marcar(dos))


def test_marcar_cambio_brusco_frente_al_dia_anterior():
    serie = [precio(2, "exito", "E", 900_000), precio(1, "exito", "E", 2_000_000), precio(3, "exito", "E", 950_000)]
    motivos = {f["fecha"]: f["motivos_atipico"] for f in atipicos.marcar(serie)}
    assert motivos == {1: None, 2: "CAMBIO_BRUSCO", 3: None}


def test_marcar_cambio_brusco_solo_entre_dias_con_stock():
    # Éxito (VTEX), sin stock, publica el precio de lista como precio (19-oct-2026: TCL 65" de 3.999.900
    # a 7.999.900). Ese día no se compara ni sirve de referencia para la vuelta del stock.
    serie = [precio(1, "exito", "E", 3_999_900, 7_999_900), precio(2, "exito", "E", 7_999_900, disponible=False),
             precio(3, "exito", "E", 3_999_900, 7_999_900)]
    marcadas = {f["fecha"]: f for f in atipicos.marcar(serie)}
    assert {k: f["motivos_atipico"] for k, f in marcadas.items()} == {1: None, 2: None, 3: None}
    assert marcadas[3]["precio_anterior"] == 3_999_900


def test_muestra_estratificada_reproducible():
    filas = [{"sitio": s, "producto_key": str(i), "url": f"u{i}"} for s in ("a", "b") for i in range(20)]
    filas += [{"sitio": "c", "producto_key": "x", "url": "ux"}]
    m1 = reglas.muestra_estratificada(filas, 5, semilla=20261018)
    m2 = reglas.muestra_estratificada(list(reversed(filas)), 5, semilla=20261018)
    assert m1 == m2
    assert [f["sitio"] for f in m1].count("a") == 5 and [f["sitio"] for f in m1].count("c") == 1


def test_resumen_metas_y_tabla():
    r = {"completitud": [{"completos": 95, "registros": 100}],
         "cobertura": [{"con_datos": 80, "vigentes": 100}],
         "emparejamiento": [{"en_2_o_mas_cadenas": 90, "no_unidos": 10, "ofertas_emparejadas": 87,
                             "ofertas_con_stock": 100}],
         "capturas": [{"minutos": 34.0, "sitios": 5}], "medallon": [{"minutos": 4.1}],
         "hechos": {"duplicados": 0, "pct_trazables": 1.0, "ruta_existe_en_lago": 10, "filas": 10}}
    filas = {f["metrica"]: f for f in resumen_metas(r)}
    assert filas["Completitud (RNF-02)"]["cumple"] == "Sí"
    assert filas["Cobertura (RNF-03)"]["cumple"] == "No"
    assert filas["Emparejamiento por productos"]["valor"] == 0.9
    assert filas["Tiempo captura + medallón (RNF-01), peor caso"]["valor"] == "38,1 min"
    # Con corridas de Synapse cuentan las pipelines (punta a punta), no el registro de ejecuciones.
    r["pipelines"] = [{"pipeline": "pl_captura_diaria", "estado": "Succeeded", "minutos": 34.3},
                      {"pipeline": "pl_medallon_semanal", "estado": "Succeeded", "minutos": 5.8},
                      {"pipeline": "pl_medallon_semanal", "estado": "Failed", "minutos": 50.0}]
    filas = {f["metrica"]: f for f in resumen_metas(r)}
    assert filas["Tiempo captura + medallón (RNF-01), peor caso"]["valor"] == "40,1 min"
    assert "95,0 %" in _tabla([{"pct": 0.95}], ["pct"])
    assert "100,0 %" in _tabla([{"pct": 1.0}], ["pct"])


def oferta(key, cadena, referencia="UN55U8000F", marca="SAMSUNG", pulgadas=55, titulo=None):
    return {**producto(key, cadena, referencia, marca, pulgadas), "titulo": titulo or f"Televisor {marca} {referencia}"}


def test_identificacion_unidos_consistentes_y_no_unidos():
    filas = [oferta("A", "Éxito"), oferta("A", "Jumbo", "55U8000F"),                 # unido y consistente
             oferta("B", "Éxito", "QN65Q7F", pulgadas=65), oferta("B", "Olímpica", "QN65Q8F", pulgadas=65),  # otra ref
             oferta("C", "Colombiana", "VGSCFH75SGMZX", pulgadas=75),                 # mismo modelo, otro GTIN
             oferta("D", "Éxito", "VGSCFH75SGMZX", pulgadas=75),
             oferta("E", "Jumbo", "UN50U8000F", pulgadas=50)]                         # solo una cadena, sin par
    resumen, detalle = reglas.identificacion(filas)
    assert resumen == {"unidos": 2, "unidos_consistentes": 1, "no_unidos_candidatos": 1,
                       "pct_identificacion": round(1 / 3, 4), "pct_precision": 0.5}
    assert {(d["tipo"], d["productos"]) for d in detalle} == {("INCONSISTENTE", "B"), ("NO_UNIDO", "C,D")}


def test_identificacion_titulo_similar_solo_sin_referencia():
    sin_ref = [oferta("A", "Éxito", None, "KALLEY", 32, 'Televisor KALLEY 32" HD Smart Android K-ATV32'),
               oferta("B", "Jumbo", None, "KALLEY", 32, 'TV KALLEY 32 pulgadas HD Smart Android K-ATV32')]
    assert reglas.identificacion(sin_ref)[0]["no_unidos_candidatos"] == 1
    # Con referencias distintas no basta un título parecido (U8000F frente a U7000F).
    otra_ref = [oferta("A", "Éxito"), oferta("B", "Jumbo", "UN55U7000F")]
    assert reglas.identificacion(otra_ref)[0]["no_unidos_candidatos"] == 0
    # Ni con otro tamaño: los títulos de una serie solo cambian en las pulgadas.
    otro_tamano = [oferta("A", "Éxito", None, titulo="Televisor Samsung 55 Crystal"),
                   oferta("B", "Jumbo", None, pulgadas=65, titulo="Televisor Samsung 65 Crystal")]
    assert reglas.identificacion(otro_tamano)[0]["no_unidos_candidatos"] == 0


def test_identificacion_misma_cadena_no_es_par_perdido():
    filas = [oferta("A", "Colombiana"), oferta("B", "Colombiana")]
    assert reglas.identificacion(filas)[0] == {"unidos": 0, "unidos_consistentes": 0, "no_unidos_candidatos": 0,
                                               "pct_identificacion": None, "pct_precision": None}


def test_consistente_tolera_atributo_ausente_y_sufijo_regional():
    assert reglas.consistente([oferta("A", "Éxito", "HYLED4326"), oferta("A", "Jumbo", "HYLED4326QG")])
    assert reglas.consistente([oferta("A", "Éxito"), oferta("A", "Jumbo", None)])
    assert not reglas.consistente([oferta("A", "Éxito"), oferta("A", "Jumbo", pulgadas=65)])
    assert not reglas.consistente([oferta("A", "Éxito"), oferta("A", "Jumbo", marca="LG")])


def test_resumen_metas_identificacion():
    r = {"completitud": [], "cobertura": [], "capturas": [], "medallon": [],
         "emparejamiento": [{"en_2_o_mas_cadenas": 10, "no_unidos": 0, "ofertas_emparejadas": 1, "ofertas_con_stock": 1,
                             "unidos": 10, "unidos_consistentes": 9, "no_unidos_candidatos": 2}],
         "hechos": {"duplicados": 0, "pct_trazables": None}}
    filas = {f["metrica"]: f for f in resumen_metas(r)}
    assert filas["Identificación correcta (H1)"]["valor"] == 0.75
    assert filas["Identificación correcta (H1)"]["cumple"] == "No"
    assert filas["Precisión del emparejamiento"]["valor"] == 0.9

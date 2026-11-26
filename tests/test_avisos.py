# -*- coding: utf-8 -*-
"""Resumen diario y alertas con plantillas (src/servicios/avisos.py), sin Spark."""
from datetime import date

from src.servicios import avisos

P = {"alertas": {"umbral_cambio_precio": 0.10, "max_por_tipo_en_resumen": 5}}


def evento(tipo, **kw):
    base = {"tipo_evento": tipo, "producto_key": "08806095465937", "marca": "SAMSUNG", "pulgadas": 55,
            "referencia": "UN55U8000F", "tienda": "Éxito", "sitio": "exito", "precio_anterior": 2_000_000,
            "precio_actual": 1_600_000, "variacion_pct": -0.2, "precio_lista": 3_000_000,
            "descuento_anunciado": None, "descuento_respaldado": None, "precio_referencia_30d": None,
            "url": "https://www.exito.com/tv/p"}
    base.update(kw)
    return base


def datos(eventos=(), **kw):
    d = {"fecha": "2026-11-27", "ofertas": {"con_stock": 980, "sitios": 5}, "productos_comparables": 140,
         "brecha": {"media": 0.153, "media_anterior": 0.121}, "marcadas_vigentes": 0,
         "eventos": list(eventos), "ejecuciones": [{"tienda": "Alkosto", "estado": "EXITOSA"}]}
    d.update(kw)
    return d


def test_formatos():
    assert avisos.pesos(1399900) == "$1.399.900"
    assert avisos.pct(0.153) == "15,3 %"
    assert avisos.pct(-0.2, signo=True) == "−20,0 %"
    assert avisos.fecha_larga(date(2026, 11, 27)) == "viernes 27 de noviembre de 2026"


def test_resumen_sin_eventos_solo_trae_las_frases_con_datos():
    frases = [f for f, _ in avisos.parrafos_resumen(datos(), P)]
    assert frases == [
        "La captura del día registró 980 ofertas de televisores con existencias en 5 sitios, y 140 productos "
        "se venden en dos o más cadenas.",
        "La brecha media de precio entre cadenas fue de 15,3 %, frente a 12,1 % en la captura anterior.",
    ]


def test_resumen_con_eventos_y_captura_parcial():
    ev = [evento("CAMBIO_PRECIO"),
          evento("CAMBIO_PRECIO", variacion_pct=0.15, precio_anterior=1_000_000, precio_actual=1_150_000),
          evento("AGOTADO"),
          evento("DESCUENTO_SIN_RESPALDO", precio_actual=900_000, precio_lista=2_000_000, descuento_anunciado=0.55,
                 descuento_respaldado=0.10, precio_referencia_30d=1_000_000)]
    ej = [{"tienda": "Éxito", "estado": "PARCIAL", "consultados": 220, "descubiertos": 530}]
    bloques = dict(avisos.parrafos_resumen(datos(ev, ejecuciones=ej, marcadas_vigentes=3), P))
    assert bloques["2 ofertas cambiaron de precio en un 10 % o más: 1 bajó y 1 subió."][0] == (
        'SAMSUNG 55" UN55U8000F en Éxito: de $2.000.000 a $1.600.000 (−20,0 %)')
    assert "Se agotó 1 oferta." in bloques
    solo_bajas = dict(avisos.parrafos_resumen(datos([evento("CAMBIO_PRECIO", revisar_atipico=True)]), P))
    assert solo_bajas["1 oferta bajó de precio en un 10 % o más."] == [
        'SAMSUNG 55" UN55U8000F en Éxito: de $2.000.000 a $1.600.000 (−20,0 %) '
        '(precio marcado como atípico: revisar)']
    detector = bloques["El detector marcó 1 oferta nueva con un descuento sin respaldo en el historial de los "
                       "últimos 30 días."]
    assert detector == ['SAMSUNG 55" UN55U8000F en Éxito: anuncia 55,0 % sobre $2.000.000, pero frente al menor '
                        'precio de los últimos 30 días ($1.000.000) el descuento es de 10,0 %']
    assert "En total, 3 ofertas tienen hoy un descuento sin respaldo en el historial." in bloques
    assert bloques["La captura no fue completa en 1 sitio, así que sus cifras pueden estar incompletas."] == [
        "Éxito: parcial, 220 de 530 fichas consultadas"]


def test_el_texto_se_repite_igual_con_los_mismos_datos():
    d = datos([evento("CAMBIO_PRECIO"), evento("PRODUCTO_NUEVO")])
    assert avisos.armar(d, [], P) == avisos.armar(d, [], P)


def test_coincide_por_tipo_marca_producto_y_tienda():
    e = evento("CAMBIO_PRECIO")
    assert avisos.coincide(e, None)
    assert avisos.coincide(e, {"tipos": ["cambio_precio"], "marcas": ["samsung"]})
    assert not avisos.coincide(e, {"marcas": ["LG"]})
    assert avisos.coincide(e, {"productos": ["un55u8000f"]})
    assert not avisos.coincide(e, {"tiendas": ["alkosto"]})


def test_armar_sin_suscripciones_envia_solo_el_resumen_a_los_destinatarios_por_defecto():
    salida = avisos.armar(datos([evento("CAMBIO_PRECIO")]), [], P)
    assert [(m["tipo"], m["para"]) for m in salida["mensajes"]] == [("resumen", "")]
    assert salida["teams"]["titulo"] == "Resumen de precios de televisores del viernes 27 de noviembre de 2026"


def test_armar_con_suscripciones():
    sus = [{"correo": "a@x.co", "alertas": {"marcas": ["SAMSUNG"]}},
           {"correo": "b@x.co", "resumen": False, "alertas": {"marcas": ["LG"]}},
           {"correo": "c@x.co"}]
    salida = avisos.armar(datos([evento("CAMBIO_PRECIO"), evento("AGOTADO")]), sus, P)
    assert [(m["tipo"], m["para"]) for m in salida["mensajes"]] == [
        ("resumen", "a@x.co"), ("resumen", "c@x.co"), ("alertas", "a@x.co")]
    alerta = salida["mensajes"][-1]
    assert alerta["asunto"] == "[TFM] Alertas de precios del viernes 27 de noviembre de 2026: 2 eventos"
    assert "<script" not in alerta["html"] and "Cambio de precio" in alerta["html"]


def test_leer_suscripciones(tmp_path):
    ruta = tmp_path / "s.yaml"
    ruta.write_text("suscripciones:\n  - correo: a@x.co\n  - nombre: sin correo\n", encoding="utf-8")
    assert avisos.leer_suscripciones(ruta) == [{"correo": "a@x.co"}]
    assert avisos.leer_suscripciones(tmp_path / "no.yaml") == []


def test_avisos_del_dia_solo_envia_datos_de_hoy(tmp_path, monkeypatch):
    import json
    import sys
    import types

    from src.nube import lago, tarea_medallon

    falso = types.ModuleType("src.servicios.datos_dia")
    falso.leer = lambda spark, base: {**datos([evento("CAMBIO_PRECIO")]), "fecha_key": 20261127}
    monkeypatch.setitem(sys.modules, "src.servicios.datos_dia", falso)
    import src.servicios
    monkeypatch.setattr(src.servicios, "datos_dia", falso, raising=False)
    enviados = []
    monkeypatch.setattr(tarea_medallon, "enviar", lambda url, cuerpo: enviados.append(cuerpo) or 202)
    destino = lago.DestinoLocal(tmp_path / "lago")

    monkeypatch.delenv("TFM_URL_AVISOS", raising=False)
    r = tarea_medallon.avisos_del_dia(destino, tmp_path, None, hoy="2026-11-27")
    assert r["envio"] == "no se envía: falta TFM_URL_AVISOS" and not enviados

    monkeypatch.setenv("TFM_URL_AVISOS", "https://logic.example/x")
    r = tarea_medallon.avisos_del_dia(destino, tmp_path, None, hoy="2026-11-28")
    assert r["envio"].startswith("no se envía: los datos son del 2026-11-27") and not enviados

    r = tarea_medallon.avisos_del_dia(destino, tmp_path, None, hoy="2026-11-27")
    assert r == {"fecha_datos": "2026-11-27", "mensajes": 1, "eventos": 1, "envio": "HTTP 202"}
    guardado = json.loads((tmp_path / "lago" / "oro/servicios/avisos/avisos_20261127.json").read_text(encoding="utf-8"))
    assert guardado["salida"] == enviados[0]


def test_detector_por_cadena_reemplaza_la_cifra_total():
    por_cadena = [{"cadena": "Cencosud (Jumbo)", "evaluables": 55, "marcadas": 55, "anunciado": 0.467,
                   "respaldado": -0.004},
                  {"cadena": "Olímpica", "evaluables": 0, "marcadas": 0, "anunciado": None, "respaldado": None}]
    p = dict(P, detector={"min_dias_observados": 20})
    bloques = dict(avisos.parrafos_resumen(datos(marcadas_vigentes=55, detector_por_cadena=por_cadena), p))
    clave = ("Ofertas con un descuento sin respaldo en el historial, por cadena (sobre las ofertas evaluables, "
             "con al menos 20 días observados):")
    esperado = ("Cencosud (Jumbo): 55 de 55 (100,0 %); descuento anunciado medio de 46,7 % y respaldado de "
                "−0,4 %").replace(" %", avisos.NBSP + "%")
    assert bloques[clave] == [esperado]
    assert not any(f.startswith("En total") for f in bloques)

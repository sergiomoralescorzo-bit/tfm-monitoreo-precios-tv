# -*- coding: utf-8 -*-
"""Resumen diario y alertas comerciales (RF-10, RF-11, RNF-09; memoria, subapartado 5.3.6.4).

Arma los mensajes con plantillas de texto fijas, sin modelos de lenguaje: cada frase corresponde a un
tipo de evento o a un indicador y cada cifra sale de los datos del día que entrega
`src/servicios/datos_dia.py` (consultas a la capa oro). Si un tipo de evento no ocurrió, su frase no
aparece. Con los mismos datos, el texto sale igual.

Este módulo no usa Spark: recibe diccionarios y devuelve diccionarios, para probarlo sin el medallón.

Suscripciones (bronce/aterrizaje/suscripciones/suscripciones.yaml en el lago, fuera del repositorio porque
tiene correos; ejemplo en config/suscripciones.ejemplo.yaml). Sin archivo, el resumen va a los
destinatarios por defecto de la Logic App y no hay alertas individuales.
"""
import html
from datetime import date
from pathlib import Path

NBSP = " "
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]
NOMBRES = {
    "CAMBIO_PRECIO": "Cambio de precio",
    "AGOTADO": "Agotado",
    "FIN_PROMOCION": "Fin de promoción",
    "PRODUCTO_NUEVO": "Producto nuevo",
    "DESCUENTO_SIN_RESPALDO": "Descuento sin respaldo en el historial",
}
PIE = ("Resumen generado con plantillas a partir de la capa oro del sistema de monitoreo de precios "
       "(TFM). Cada cifra puede verificarse en el tablero. Un descuento sin respaldo en el historial es una "
       "comparación con los precios observados en los últimos 30 días, no una conclusión sobre la conducta "
       "de la cadena.")


# --------------------------------------------------------------------------- formatos

def pesos(n) -> str:
    return "$" + f"{int(n):,}".replace(",", ".") if n is not None else "sin dato"


def pct(x, decimales: int = 1, signo: bool = False) -> str:
    if x is None:
        return "sin dato"
    v = f"{abs(x) * 100:.{decimales}f}".replace(".", ",")
    s = ("−" if x < 0 else "+") if signo and x != 0 else ("−" if x < 0 else "")
    return f"{s}{v}{NBSP}%"


def fecha_larga(f: date) -> str:
    return f"{DIAS[f.weekday()]} {f.day} de {MESES[f.month - 1]} de {f.year}"


def plural(n: int, singular: str, plural_: str) -> str:
    return f"{n} {singular if n == 1 else plural_}"


def producto(e: dict) -> str:
    partes = [e.get("marca") or "", f'{e["pulgadas"]}"' if e.get("pulgadas") else "", e.get("referencia") or ""]
    texto = " ".join(p for p in partes if p).strip()
    return texto or (e.get("descripcion") or e.get("producto_key") or "")


def _esc(t) -> str:
    return html.escape(str(t), quote=True)


# --------------------------------------------------------------------------- suscripciones

def leer_suscripciones(ruta: Path) -> list[dict]:
    ruta = Path(ruta)
    if not ruta.exists():
        return []
    import yaml
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    return [s for s in datos.get("suscripciones", []) if s.get("correo")]


def coincide(evento: dict, filtro: dict | None) -> bool:
    """Un evento entra en la suscripción si cumple cada lista no vacía (tipos, marcas, productos, tiendas)."""
    f = filtro or {}
    mayus = lambda xs: {str(x).upper() for x in xs or []}  # noqa: E731
    if f.get("tipos") and evento["tipo_evento"] not in mayus(f["tipos"]):
        return False
    if f.get("marcas") and (evento.get("marca") or "").upper() not in mayus(f["marcas"]):
        return False
    if f.get("productos") and not ({str(evento.get("producto_key")).upper(),
                                     (evento.get("referencia") or "").upper()} & mayus(f["productos"])):
        return False
    if f.get("tiendas") and (evento.get("sitio") or "").upper() not in mayus(f["tiendas"]):
        return False
    return True


# --------------------------------------------------------------------------- resumen diario

def _orden(e: dict):
    return -abs(e.get("variacion_pct") or 0)


def _linea_evento(e: dict) -> str:
    texto = _linea_evento_sola(e)
    return texto + " (precio marcado como atípico: revisar)" if e.get("revisar_atipico") else texto


def _linea_evento_sola(e: dict) -> str:
    base = f"{producto(e)} en {e.get('tienda')}"
    t = e["tipo_evento"]
    if t == "CAMBIO_PRECIO":
        return (f"{base}: de {pesos(e['precio_anterior'])} a {pesos(e['precio_actual'])} "
                f"({pct(e['variacion_pct'], signo=True)})")
    if t == "FIN_PROMOCION":
        return f"{base}: de {pesos(e['precio_anterior'])} a {pesos(e['precio_actual'])}"
    if t == "DESCUENTO_SIN_RESPALDO":
        return (f"{base}: anuncia {pct(e['descuento_anunciado'])} sobre {pesos(e['precio_lista'])}, "
                f"pero frente al menor precio de los últimos 30 días ({pesos(e['precio_referencia_30d'])}) "
                f"el descuento es de {pct(e['descuento_respaldado'])}")
    if t == "PRODUCTO_NUEVO":
        return f"{base}: {pesos(e['precio_actual'])}"
    return base


def parrafos_resumen(datos: dict, p: dict) -> list[tuple[str, list[str]]]:
    """[(frase, [detalles])] en el orden del resumen. Solo aparecen las frases con datos."""
    a = p["alertas"]
    maximo = int(a.get("max_por_tipo_en_resumen", 5))
    umbral = float(a["umbral_cambio_precio"])
    ev = datos.get("eventos", [])
    por_tipo = {t: sorted([e for e in ev if e["tipo_evento"] == t], key=_orden) for t in NOMBRES}
    salida = []

    o = datos.get("ofertas", {})
    frase = (f"La captura del día registró {plural(o.get('con_stock', 0), 'oferta', 'ofertas')} de televisores "
             f"con existencias en {plural(o.get('sitios', 0), 'sitio', 'sitios')}")
    if datos.get("productos_comparables"):
        frase += (f", y {plural(datos['productos_comparables'], 'producto se vende', 'productos se venden')} "
                  f"en dos o más cadenas")
    salida.append((frase + ".", []))

    b = datos.get("brecha", {})
    if b.get("media") is not None:
        frase = f"La brecha media de precio entre cadenas fue de {pct(b['media'])}"
        if b.get("media_anterior") is not None:
            dif = (b["media"] - b["media_anterior"]) * 100
            frase += (f", frente a {pct(b['media_anterior'])} en la captura anterior" if abs(dif) >= 0.05
                      else ", igual que en la captura anterior")
        salida.append((frase + ".", []))

    cambios = por_tipo["CAMBIO_PRECIO"]
    if cambios:
        bajas = sum(1 for e in cambios if (e.get("variacion_pct") or 0) < 0)
        subidas = len(cambios) - bajas
        if bajas and subidas:
            frase = (f"{plural(len(cambios), 'oferta cambió', 'ofertas cambiaron')} de precio en un "
                     f"{pct(umbral, 0)} o más: {bajas} {'bajó' if bajas == 1 else 'bajaron'} y "
                     f"{subidas} {'subió' if subidas == 1 else 'subieron'}.")
        else:
            verbo = ("bajó" if bajas else "subió") if len(cambios) == 1 else ("bajaron" if bajas else "subieron")
            frase = f"{plural(len(cambios), 'oferta', 'ofertas')} {verbo} de precio en un {pct(umbral, 0)} o más."
        salida.append((frase, [_linea_evento(e) for e in cambios[:maximo]]))

    fin = por_tipo["FIN_PROMOCION"]
    if fin:
        salida.append((f"{plural(len(fin), 'promoción terminó', 'promociones terminaron')} con una subida "
                       f"del precio de venta.", [_linea_evento(e) for e in fin[:maximo]]))

    agot, nuevos = por_tipo["AGOTADO"], por_tipo["PRODUCTO_NUEVO"]
    if agot or nuevos:
        partes = []
        if agot:
            partes.append(f"se {'agotó' if len(agot) == 1 else 'agotaron'} {plural(len(agot), 'oferta', 'ofertas')}")
        if nuevos:
            partes.append(f"{'apareció' if len(nuevos) == 1 else 'aparecieron'} "
                          f"{plural(len(nuevos), 'producto nuevo', 'productos nuevos')}")
        frase = " y ".join(partes)
        salida.append((frase[0].upper() + frase[1:] + ".", [_linea_evento(e) for e in nuevos[:maximo]]))

    dsr = por_tipo["DESCUENTO_SIN_RESPALDO"]
    if dsr:
        orden = sorted(dsr, key=lambda e: -((e.get("descuento_anunciado") or 0) - (e.get("descuento_respaldado") or 0)))
        salida.append((f"El detector marcó {plural(len(dsr), 'oferta nueva', 'ofertas nuevas')} con un descuento "
                       f"sin respaldo en el historial de los últimos 30 días.",
                       [_linea_evento(e) for e in orden[:maximo]]))
    por_cadena = [c for c in datos.get("detector_por_cadena") or [] if c.get("evaluables")]
    if por_cadena:
        salida.append((f"Ofertas con un descuento sin respaldo en el historial, por cadena (sobre las ofertas "
                       f"evaluables, con al menos {p.get('detector', {}).get('min_dias_observados', 20)} días observados):",
                       [f"{c['cadena']}: {c['marcadas']} de {c['evaluables']} ({pct(c['marcadas'] / c['evaluables'])}); "
                        f"descuento anunciado medio de {pct(c.get('anunciado'))} y respaldado de "
                        f"{pct(c.get('respaldado'))}" for c in por_cadena]))
    elif datos.get("marcadas_vigentes"):   # datos guardados antes del 19-nov, sin detalle por cadena
        salida.append((f"En total, {plural(datos['marcadas_vigentes'], 'oferta tiene', 'ofertas tienen')} hoy "
                       f"un descuento sin respaldo en el historial.", []))

    malas = [x for x in datos.get("ejecuciones", []) if x.get("estado") != "EXITOSA"]
    if malas:
        detalle = [f"{x['tienda']}: {x['estado'].lower()}, {x.get('consultados', 0)} de "
                   f"{x.get('descubiertos', 0)} fichas consultadas" for x in malas]
        salida.append(("La captura no fue completa en " + plural(len(malas), "sitio", "sitios")
                       + ", así que sus cifras pueden estar incompletas.", detalle))
    return salida


def _html(titulo: str, bloques: list[tuple[str, list[str]]], pie: str) -> str:
    partes = [f"<h3>{_esc(titulo)}</h3>"]
    for frase, detalles in bloques:
        partes.append(f"<p>{_esc(frase)}</p>")
        if detalles:
            partes.append("<ul>" + "".join(f"<li>{_esc(d)}</li>" for d in detalles) + "</ul>")
    partes.append(f'<p style="color:gray;font-size:smaller">{_esc(pie)}</p>')
    return "\n".join(partes)


def _texto(titulo: str, bloques: list[tuple[str, list[str]]]) -> str:
    lineas = [titulo, ""]
    for frase, detalles in bloques:
        lineas.append(frase)
        lineas += [f"- {d}" for d in detalles]
    return "\n".join(lineas)


# --------------------------------------------------------------------------- alertas

def _tabla_alertas(eventos: list[dict]) -> str:
    filas = "".join(
        f"<tr><td>{_esc(NOMBRES[e['tipo_evento']])}</td><td>{_esc(producto(e))}</td><td>{_esc(e.get('tienda'))}</td>"
        f"<td>{_esc(_linea_evento(e).split(': ', 1)[-1] if ': ' in _linea_evento(e) else '')}</td>"
        f"<td><a href=\"{_esc(e.get('url') or '')}\">ficha</a></td></tr>"
        for e in sorted(eventos, key=lambda e: (list(NOMBRES).index(e["tipo_evento"]), _orden(e))))
    return ('<table border="1" cellpadding="4" cellspacing="0" style="border-collapse:collapse">'
            "<tr><th>Evento</th><th>Producto</th><th>Tienda</th><th>Detalle</th><th>Página</th></tr>"
            f"{filas}</table>")


# --------------------------------------------------------------------------- todo junto

def armar(datos: dict, suscripciones: list[dict], p: dict) -> dict:
    """Mensajes del día para la Logic App: {"fecha", "mensajes": [{para, asunto, html}], "teams": {...}}.

    `para` vacío = destinatarios por defecto de la Logic App."""
    f = date.fromisoformat(datos["fecha"])
    titulo = f"Resumen de precios de televisores del {fecha_larga(f)}"
    bloques = parrafos_resumen(datos, p)
    mensajes = []
    con_resumen = [s for s in suscripciones if s.get("resumen", True)]
    for destino in ([s["correo"] for s in con_resumen] if suscripciones else [""]):
        mensajes.append({"tipo": "resumen", "para": destino, "asunto": f"[TFM] {titulo}",
                         "html": _html(titulo, bloques, PIE)})
    for s in suscripciones:
        if s.get("alertas") is None:
            continue
        propios = [e for e in datos.get("eventos", []) if coincide(e, s.get("alertas"))]
        if propios:
            t = f"Alertas de precios del {fecha_larga(f)}: {plural(len(propios), 'evento', 'eventos')}"
            mensajes.append({"tipo": "alertas", "para": s["correo"], "asunto": f"[TFM] {t}",
                             "html": f"<h3>{_esc(t)}</h3>" + _tabla_alertas(propios)
                                     + f'<p style="color:gray;font-size:smaller">{_esc(PIE)}</p>'})
    return {"fecha": datos["fecha"], "mensajes": mensajes,
            "teams": {"titulo": titulo, "texto": _texto(titulo, bloques)}}

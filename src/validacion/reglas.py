# -*- coding: utf-8 -*-
"""Reglas de la validación (Etapa 6) en Python puro, sin Spark, para probarlas con pytest.

- `pares_perdidos`: productos que una sola cadena vende con un GTIN, pero que otra cadena vende con
  la misma clave marca|pulgadas|referencia y otro GTIN. Son emparejamientos que la regla no hizo y
  sirven para estimar el denominador de la métrica (productos presentes en 2 o más cadenas).
- `muestra_estratificada`: muestra aleatoria reproducible para contrastar precios a mano.
Los precios atípicos están en `src/medallon/atipicos.py`, porque también los marca plata.
"""
import random
from collections import defaultdict

from src.catalogo.emparejamiento import clave_de


def pares_perdidos(productos: list[dict]) -> list[dict]:
    """`productos`: filas con producto_key, cadena, marca, pulgadas y referencia (un día, con stock).

    Devuelve un registro por producto vendido por una sola cadena cuya clave coincide con la de un
    producto distinto de otra cadena. Solo se usa la coincidencia exacta de la clave."""
    cadenas_de = defaultdict(set)
    claves_de = defaultdict(set)
    for p in productos:
        cadenas_de[p["producto_key"]].add(p["cadena"])
        clave = clave_de(p.get("marca"), p.get("pulgadas"), p.get("referencia"))
        if clave:
            claves_de[p["producto_key"]].add(clave)
    por_clave = defaultdict(set)
    for producto, claves in claves_de.items():
        for clave in claves:
            por_clave[clave].add(producto)

    salida = []
    for producto, claves in sorted(claves_de.items()):
        if len(cadenas_de[producto]) != 1:
            continue
        (cadena,) = cadenas_de[producto]
        for clave in sorted(claves):
            otros = sorted(o for o in por_clave[clave] - {producto} if cadenas_de[o] - {cadena})
            if otros:
                salida.append({"producto_key": producto, "cadena": cadena, "clave": clave,
                               "candidatos": ",".join(otros),
                               "cadenas_candidatas": ",".join(sorted(set().union(*[cadenas_de[o] for o in otros])
                                                                     - {cadena}))})
                break
    return salida


def muestra_estratificada(filas: list[dict], por_estrato: int, semilla: int, estrato: str = "sitio") -> list[dict]:
    """Hasta `por_estrato` filas al azar de cada estrato, en orden reproducible."""
    grupos = defaultdict(list)
    for f in sorted(filas, key=lambda f: (str(f[estrato]), str(f.get("producto_key")), str(f.get("url")))):
        grupos[f[estrato]].append(f)
    azar = random.Random(semilla)
    salida = []
    for clave in sorted(grupos):
        g = grupos[clave]
        salida += azar.sample(g, min(por_estrato, len(g)))
    return salida


# --------------------------------------------------------------------------- hipótesis 1 (memoria v8)
# «Identificación correcta» y precisión del emparejamiento, medidas en censo y sin muestra manual.
# Cada fila es una oferta de un día con stock: producto_key, cadena, marca, pulgadas, referencia y título
# tal como los publicó la tienda. La búsqueda de candidatos no usa el GTIN: así encuentra también los
# productos que la regla dejó separados.

SIMILITUD_TITULO = 0.90   # título "muy similar" (difflib), solo si a una de las dos ofertas le falta referencia
MIN_PREFIJO = 4           # como en IndiceReferencias: sufijo regional (HYLED4326 ~ HYLED4326QG)


def _ref_norm(f: dict) -> str | None:
    from src.catalogo import atributos_tv
    pulg = f.get("pulgadas")
    pulg = int(pulg) if pulg not in (None, "") and pulg == pulg else None
    return atributos_tv.referencia_normalizada(f.get("referencia"), pulg, f.get("marca"))


def _titulo_norm(texto) -> str:
    import re
    from src.catalogo import atributos_tv
    t = atributos_tv.sin_tildes(atributos_tv.limpiar_descripcion(texto).lower())
    t = re.sub(r"\b(televisor|tv|smart|pulgadas|pulg|cm|led|uhd|4k|hd)\b", " ", t)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def refs_compatibles(a: str | None, b: str | None) -> bool | None:
    """True si son la misma referencia (o una es prefijo de la otra, de 4+ caracteres); None si falta una."""
    if not a or not b:
        return None
    return a == b or (len(min(a, b, key=len)) >= MIN_PREFIJO and (a.startswith(b) or b.startswith(a)))


def misma_referencia_o_titulo(x: dict, y: dict) -> bool:
    """Candidato independiente del GTIN: misma marca y pulgadas, y referencia compatible; si a una de las
    dos le falta la referencia, un título muy similar."""
    from difflib import SequenceMatcher
    if not x.get("marca") or x.get("marca") != y.get("marca"):
        return False
    if not x.get("pulgadas") or x.get("pulgadas") != y.get("pulgadas"):
        return False
    refs = refs_compatibles(_ref_norm(x), _ref_norm(y))
    if refs is not None:
        return refs
    tx, ty = _titulo_norm(x.get("titulo")), _titulo_norm(y.get("titulo"))
    return bool(tx and ty) and SequenceMatcher(None, tx, ty).ratio() >= SIMILITUD_TITULO


def consistente(ofertas: list[dict]) -> bool:
    """Las ofertas de un producto unido (de 2+ cadenas) no se contradicen en marca, pulgadas ni referencia.
    Un atributo que la tienda no publicó no cuenta como contradicción."""
    marcas = {o["marca"] for o in ofertas if o.get("marca")}
    pulgadas_ = {int(o["pulgadas"]) for o in ofertas if o.get("pulgadas")}
    if len(marcas) > 1 or len(pulgadas_) > 1:
        return False
    refs = sorted({r for r in map(_ref_norm, ofertas) if r})
    return all(refs_compatibles(a, b) for i, a in enumerate(refs) for b in refs[i + 1:])


def identificacion(ofertas: list[dict]) -> tuple[dict, list[dict]]:
    """Un día. Devuelve (resumen, detalle de fallos).

    Población: productos unidos (2+ cadenas) más los productos reales que la regla no unió, hallados con
    `misma_referencia_o_titulo` entre productos de una sola cadena (cada grupo conectado que abarca dos o
    más cadenas cuenta como uno). Identificación correcta = unidos consistentes / población.
    Precisión del emparejamiento = unidos consistentes / unidos."""
    por_producto = defaultdict(list)
    for o in ofertas:
        por_producto[o["producto_key"]].append(o)
    cadenas = {k: {o["cadena"] for o in v} for k, v in por_producto.items()}
    unidos = sorted(k for k, c in cadenas.items() if len(c) >= 2)
    inconsistentes = [k for k in unidos if not consistente(por_producto[k])]

    # Candidatos sin GTIN: productos de una sola cadena que parecen el mismo de otra cadena.
    solos = sorted(k for k, c in cadenas.items() if len(c) == 1)
    padre = {k: k for k in solos}

    def raiz(k):
        while padre[k] != k:
            padre[k] = padre[padre[k]]
            k = padre[k]
        return k

    por_grupo = defaultdict(list)   # se compara solo dentro de marca|pulgadas
    for k in solos:
        o = por_producto[k][0]
        if o.get("marca") and o.get("pulgadas"):
            por_grupo[(o["marca"], int(o["pulgadas"]))].append(k)
    for grupo in por_grupo.values():
        for i, a in enumerate(grupo):
            for b in grupo[i + 1:]:
                if cadenas[a] != cadenas[b] and any(misma_referencia_o_titulo(x, y)
                                                    for x in por_producto[a] for y in por_producto[b]):
                    padre[raiz(a)] = raiz(b)
    componentes = defaultdict(list)
    for k in solos:
        componentes[raiz(k)].append(k)
    no_unidos = [sorted(c) for c in componentes.values()
                 if len(set().union(*(cadenas[k] for k in c))) >= 2]

    correctos = len(unidos) - len(inconsistentes)
    poblacion = len(unidos) + len(no_unidos)
    resumen = {"unidos": len(unidos), "unidos_consistentes": correctos, "no_unidos_candidatos": len(no_unidos),
               "pct_identificacion": round(correctos / poblacion, 4) if poblacion else None,
               "pct_precision": round(correctos / len(unidos), 4) if unidos else None}
    detalle = [{"tipo": "INCONSISTENTE", "productos": k,
                "cadenas": ",".join(sorted(cadenas[k])),
                "atributos": " / ".join(sorted({f"{o.get('marca')}|{o.get('pulgadas')}|{_ref_norm(o)}"
                                                for o in por_producto[k]}))} for k in inconsistentes]
    detalle += [{"tipo": "NO_UNIDO", "productos": ",".join(c),
                 "cadenas": ",".join(sorted(set().union(*(cadenas[k] for k in c)))),
                 "atributos": " / ".join(sorted({f"{o.get('marca')}|{o.get('pulgadas')}|{_ref_norm(o)}"
                                                 for k in c for o in por_producto[k]}))} for c in no_unidos]
    return resumen, detalle

# -*- coding: utf-8 -*-
"""Intérprete de robots.txt con comodines (* y $), según la especificación RFC 9309.

`urllib.robotparser` solo compara prefijos y no entiende reglas como `/*?*facets=` (Éxito)
o `/*&` (Olímpica), por eso se implementa aquí.
"""
import re
from urllib.parse import urlsplit


def _a_regex(patron: str) -> re.Pattern:
    fin = patron.endswith("$")
    if fin:
        patron = patron[:-1]
    cuerpo = ".*".join(re.escape(p) for p in patron.split("*"))
    return re.compile("^" + cuerpo + ("$" if fin else ""))


class ReglasRobots:
    """Reglas que aplican a un User-Agent. Gana la regla más larga; ante empate, Allow."""

    def __init__(self, texto: str, agente: str = "*"):
        self.reglas: list[tuple[bool, str, re.Pattern]] = []
        grupos: list[tuple[list[str], list[tuple[bool, str]]]] = []
        agentes: list[str] = []
        reglas: list[tuple[bool, str]] = []
        leyendo_agentes = False
        for linea in texto.splitlines():
            linea = linea.split("#", 1)[0].strip()
            if ":" not in linea:
                continue
            campo, valor = (s.strip() for s in linea.split(":", 1))
            campo = campo.lower()
            if campo == "user-agent":
                if not leyendo_agentes and (agentes or reglas):
                    grupos.append((agentes, reglas))
                    agentes, reglas = [], []
                agentes.append(valor.lower())
                leyendo_agentes = True
            elif campo in ("allow", "disallow"):
                leyendo_agentes = False
                if valor:
                    reglas.append((campo == "allow", valor))
            else:
                leyendo_agentes = False
        if agentes or reglas:
            grupos.append((agentes, reglas))

        agente = agente.lower()
        propios = [r for a, r in grupos if any(x != "*" and x in agente for x in a)]
        elegidos = propios or [r for a, r in grupos if "*" in a]
        # Los grupos repetidos para el mismo agente se combinan (Olímpica tiene dos "User-agent: *").
        for reglas_grupo in elegidos:
            for permitir, patron in reglas_grupo:
                self.reglas.append((permitir, patron, _a_regex(patron)))

    def permite(self, url: str) -> bool:
        partes = urlsplit(url)
        ruta = (partes.path or "/") + (f"?{partes.query}" if partes.query else "")
        mejor: tuple[int, bool] | None = None
        for permitir, patron, regex in self.reglas:
            if regex.match(ruta):
                clave = (len(patron), permitir)
                if mejor is None or clave > mejor:
                    mejor = clave
        return True if mejor is None else mejor[1]

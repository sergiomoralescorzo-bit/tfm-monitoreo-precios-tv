# -*- coding: utf-8 -*-
"""Despliegue de las vistas del modelo estrella en Synapse SQL serverless (Etapa 4).

Ejecuta los scripts de `synapse/sql/` contra `syn-tfm-webscraping-ondemand`:

    00_base_de_datos.sql   en master: crea la base tfm_oro (collation UTF-8)
    01_acceso_lago.sql     en tfm_oro: clave maestra, credencial con la identidad de Synapse, fuente ds_oro, esquema oro
    02_vistas_oro.sql      en tfm_oro: vistas OPENROWSET(FORMAT='DELTA') sobre oro/
    03_verificacion.sql    en tfm_oro: controles de solo lectura (conteos, duplicados, integridad, resumen diario)
    04_permiso_usuario.sql en tfm_oro: lectura de las vistas para un usuario de Entra ID (Power BI)

Todo es idempotente: se puede volver a ejecutar sin efectos. Los lotes se separan con líneas `GO`,
como en SSMS. La autenticación es con Entra ID (ActiveDirectoryDefault: `az login` en el equipo),
sin contraseñas. La clave maestra de la base se genera al azar y no se guarda.

Uso:
    python -m src.nube.sql_serverless desplegar     # 00, 01 y 02
    python -m src.nube.sql_serverless verificar     # 03
    python -m src.nube.sql_serverless permisos --usuarios a@comunidadunir.net,b@comunidadunir.net   # 04
Requiere `mssql-python` (driver de Microsoft que trae su propio ODBC).
"""
import argparse
import re
import secrets
import sys
from pathlib import Path

SERVIDOR = "syn-tfm-webscraping-ondemand.sql.azuresynapse.net"
BASE = "tfm_oro"
CARPETA = Path(__file__).resolve().parents[2] / "synapse" / "sql"
DESPLIEGUE = [("00_base_de_datos.sql", "master"), ("01_acceso_lago.sql", BASE), ("02_vistas_oro.sql", BASE)]
VERIFICACION = [("03_verificacion.sql", BASE)]
PERMISO = [("04_permiso_usuario.sql", BASE)]
_CORREO = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

_GO = re.compile(r"^\s*GO\s*$", re.IGNORECASE | re.MULTILINE)
_VARIABLE = re.compile(r"\$\((\w+)\)")


def lotes(texto: str) -> list[str]:
    """Separa un script en lotes por las líneas `GO`; descarta los lotes vacíos o solo con comentarios."""
    resultado = []
    for lote in _GO.split(texto):
        codigo = "\n".join(l for l in lote.splitlines() if not l.strip().startswith("--")).strip()
        if codigo:
            resultado.append(lote.strip())
    return resultado


def sustituir(texto: str, variables: dict[str, str]) -> str:
    """Reemplaza `$(NOMBRE)` como sqlcmd. Falla si falta alguna variable."""
    faltan = sorted(set(_VARIABLE.findall(texto)) - set(variables))
    if faltan:
        raise KeyError(f"Variables sin valor: {', '.join(faltan)}")
    return _VARIABLE.sub(lambda m: variables[m[1]], texto)


def usuarios(texto: str) -> list[str]:
    """Correos separados por coma. Solo se aceptan correos válidos, porque van dentro del SQL."""
    lista = [u.strip().lower() for u in texto.split(",") if u.strip()]
    invalidos = [u for u in lista if not _CORREO.match(u)]
    if invalidos or not lista:
        raise ValueError(f"Correos no válidos: {', '.join(invalidos) or '(ninguno)'}")
    return lista


def clave_maestra() -> str:
    """Contraseña aleatoria que cumple la política de complejidad de SQL."""
    return "Tfm#" + secrets.token_urlsafe(24) + "9a"


def conectar(base: str, servidor: str = SERVIDOR):
    import mssql_python
    return mssql_python.connect(f"Server=tcp:{servidor},1433;Database={base};"
                                "Authentication=ActiveDirectoryDefault;Encrypt=yes;", autocommit=True)


def imprimir(cursor) -> None:
    """Imprime los conjuntos de resultados del lote como tablas de texto."""
    while True:
        if cursor.description:
            columnas = [d[0] for d in cursor.description]
            filas = [["" if v is None else str(v) for v in f] for f in cursor.fetchall()]
            anchos = [max(len(c), *(len(f[i]) for f in filas)) if filas else len(c) for i, c in enumerate(columnas)]
            print("  ".join(c.ljust(a) for c, a in zip(columnas, anchos)))
            for f in filas:
                print("  ".join(v.ljust(a) for v, a in zip(f, anchos)))
            print()
        if not cursor.nextset():
            break


def ejecutar(scripts: list[tuple[str, str]], variables: dict[str, str], servidor: str = SERVIDOR) -> int:
    n = 0
    for archivo, base in scripts:
        texto = sustituir((CARPETA / archivo).read_text(encoding="utf-8"), variables)
        conexion = conectar(base, servidor)
        try:
            cursor = conexion.cursor()
            for lote in lotes(texto):
                cursor.execute(lote)
                imprimir(cursor)
                n += 1
        finally:
            conexion.close()
        print(f"OK {archivo} ({base})")
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("accion", choices=["desplegar", "verificar", "permisos"])
    ap.add_argument("--usuarios", help="permisos: correos de Entra ID separados por coma")
    ap.add_argument("--servidor", default=SERVIDOR)
    args = ap.parse_args(argv)
    if args.accion == "permisos":
        if not args.usuarios:
            ap.error("permisos necesita --usuarios")
        n = sum(ejecutar(PERMISO, {"USUARIO": u}, args.servidor) for u in usuarios(args.usuarios))
    else:
        scripts = DESPLIEGUE if args.accion == "desplegar" else VERIFICACION
        n = ejecutar(scripts, {"CLAVE_MAESTRA": clave_maestra()}, args.servidor)
    print(f"{n} lotes ejecutados")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Monitoreo de precios de televisores en el retail colombiano

Código fuente de la herramienta del caso de validación del Trabajo Fin de Máster *Diseño y validación de una metodología para el análisis de precios y la toma de decisiones comerciales a partir de datos web: caso de los televisores en el retail colombiano* (Máster Universitario en Análisis y Visualización de Datos Masivos, UNIR, 2026).

Autores: María Alejandra Romero Rosero, Sergio Luis Herrera Fonseca y Sergio Manuel Morales Corzo.
Director: Henry Eduardo Baquero Vega.

La herramienta captura cada día los precios de los televisores nuevos que venden directamente cuatro cadenas en cinco sitios web (Alkosto, Ktronix, Grupo Éxito, Jumbo y Olímpica). Los datos se procesan en una arquitectura medallón (bronce, plata y oro) sobre Azure. Los productos se emparejan entre cadenas por GTIN y el resultado se publica en un tablero de Power BI. La herramienta también incluye un detector de descuentos sin respaldo, eventos comerciales y un resumen diario por correo y Teams.

> Repositorio privado. El acceso se concede al director y al tribunal del TFM. Ver [Licencia y uso](#licencia-y-uso).

## Arquitectura

```
Disparador diario (06:00, hora de Colombia)
  └─ Canalización de Azure Synapse (pl_orquestador_diario)
       ├─ Trabajo de Container Apps: captura   (imagen tfm-captura)   ─┐
       └─ Trabajo de Container Apps: medallón  (imagen tfm-medallon)  ─┤
                                                                        ▼
                        Azure Data Lake Storage Gen2 (tablas Delta: bronce/plata/oro)
                                   │                         │
                    Synapse SQL sin servidor (vistas)   Microsoft Fabric (Direct Lake)
                                   │                         │
                              Power BI (PBIP)          Tablero publicado
       Logic Apps: aviso de fallos, vigilancia de las 09:30 y resumen diario (correo y Teams)
```

Spark corre en modo local dentro del contenedor del medallón (PySpark 3.4 y Delta Lake 2.4).

## Organización por fases de la metodología

| Carpeta | Contenido | Fase |
|---|---|---|
| `config/` | `fuentes.yaml` (sitios, rutas, pausas, vendedor propio, motor de captura y presupuesto de tiempo), `servicios.yaml` (parámetros del detector y de los eventos) y un ejemplo de suscripciones | 1, 2 y 5 |
| `src/extraccion/` | Cliente HTTP con robots.txt y pausas, extractores SAP Commerce, VTEX y Éxito, cliente Scrapling, clasificación de alcance y registro de ejecuciones | 2 |
| `src/catalogo/` | Maestro de televisores, validación del GTIN, atributos y regla de emparejamiento | 1 y 3 |
| `src/medallon/` | Conformidad, capas plata y oro, precios atípicos, detector y eventos comerciales con PySpark | 3 y 4 |
| `src/servicios/` | Datos del día y plantillas del resumen diario | 5 |
| `src/nube/` e `infra/` | Tareas de los contenedores, sincronización con el lago, reproceso, vistas SQL, despliegue en Azure y montaje en Fabric | 3 y 5 |
| `synapse/` | Canalizaciones, disparador, scripts SQL y vigilancia | 3 |
| `powerbi/` | Proyecto PBIP del tablero y scripts que aplican cada ajuste sobre su definición | 5 |
| `src/validacion/` | Programa de validación con las métricas de la memoria (cobertura, completitud, emparejamiento, identificación correcta, tiempo y demás) | 6 |
| `tests/` | Pruebas rápidas con respuestas reales guardadas y reducidas, sin conexión a internet | 2 a 6 |
| `tests_spark/` | Pruebas de las capas plata y oro en un contenedor con la misma versión de Spark de producción | 3 y 4 |
| `docs/` | Documentación técnica por etapa y anexos de viabilidad | Todas |
| `archivo/iphone/` | Primer alcance (iPhone), descartado; el motivo está en `docs/anexos/A2_viabilidad_televisores.md` | — |

Las fases son las de la metodología propuesta en el capítulo 5 de la memoria: 1) alcance y requisitos, 2) extracción, 3) orquestación y capas, 4) modelo analítico, 5) visualización y distribución, 6) evaluación.

## Requisitos

- Python 3.12 (las imágenes usan 3.12 para la captura y 3.10 para el medallón).
- Docker Desktop, para las pruebas de Spark y para construir las imágenes.
- Azure CLI con una suscripción propia, solo para desplegar en la nube.

## Puesta en marcha local, sin Azure

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
scrapling install

# Pruebas rápidas (sin internet)
python -m pytest -q
```

**Maestro de televisores.** El maestro no está en el repositorio. Para correr la captura completa se necesita `data/maestro/maestro_televisores.csv`, que se genera con `python -m src.catalogo.construir_maestro <ruta_excel>` a partir de una hoja `DIM_PRODUCTO` con la misma estructura.

**Captura de prueba** (unas pocas fichas por sitio, con una carpeta que hace las veces de lago):

```powershell
python -m src.nube.tarea --modo completo --limite 3 --lago-local C:\lago_prueba
```

**Medallón** (bronce → plata → oro) sobre la misma carpeta, con Docker:

```powershell
docker build -f medallon.Dockerfile -t tfm-medallon:local .
docker run --rm -v "C:\lago_prueba:/lago" tfm-medallon:local --lago-local /lago --sin-avisos
```

**Pruebas de Spark:**

```powershell
docker build -t tfm-spark-pruebas tests_spark
docker run --rm -v "${PWD}:/app" tfm-spark-pruebas
```

**Métricas de validación** sobre una copia local de plata y oro:

```powershell
python -m src.validacion.metricas calcular --lago C:\lago_prueba
```

## Despliegue en Azure

`infra/desplegar.ps1` construye y publica las dos imágenes. También crea el lago, los trabajos de Container Apps, las canalizaciones y el disparador de Synapse, las Logic Apps de avisos y los permisos. Sus pasos se pueden repetir sin duplicar recursos. Los parámetros (grupo de recursos, región, nombres y correos de aviso) van al inicio del script y se ajustan a la suscripción de quien despliega. `infra/fabric.py` monta el tablero en Microsoft Fabric con accesos directos a la capa oro. El detalle de cada etapa está en `docs/`.

## Captura responsable

- Se respeta robots.txt en cada petición y se hace una pausa mínima de 1,5 s entre peticiones al mismo sitio.
- El agente de usuario se puede identificar.
- Se capturan solo las ofertas del vendedor propio de cada cadena.
- En Éxito se usa Scrapling para superar el desafío de Cloudflare, sin proxies ni rotación de identidades. La memoria del TFM declara esta decisión.

## Qué no incluye el repositorio

- Las respuestas originales de los sitios (capa bronce) ni ningún dato capturado (plata u oro).
- El maestro de televisores, que es propiedad de los autores.
- Claves o contraseñas. Los servicios se autentican con identidades administradas, y la URL firmada de los avisos se guarda como secreto del trabajo de Container Apps.
- La configuración local y la caché de Power BI.

## Licencia y uso

© 2026 María Alejandra Romero Rosero, Sergio Luis Herrera Fonseca y Sergio Manuel Morales Corzo. Todos los derechos reservados.

El código se comparte para fines de evaluación académica del TFM. No se concede licencia de uso, copia ni redistribución sin autorización escrita de los autores. Para capturar datos de los sitios con fines distintos del académico se requiere la autorización de cada cadena, según sus términos de uso.

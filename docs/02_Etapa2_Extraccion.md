# Etapa 2 — Extracción de precios (web scraping)

**Versión:** 0.1 (13 de octubre de 2026)
**Objetivo específico que cubre:** *Desarrollar los componentes de extracción automatizada de precios de los sitios web de las cadenas seleccionadas, cumpliendo sus políticas de acceso.*
**Requerimientos que atiende (Etapa 1):** RF-02, RF-03, RF-07, RNF-02, RNF-03, RNF-06.

---

## 1. Entregables

| Entregable | Ubicación |
|---|---|
| Extractores de los 5 sitios (Alkosto, Ktronix, Jumbo, Olímpica, Éxito) | `src/extraccion/` |
| Configuración externa de sitios, pausas y patrones | `config/fuentes.yaml` |
| Clasificación previa al emparejamiento (combos, accesorios, marketplace…) | `src/extraccion/clasificacion.py` |
| Regla de emparejamiento EAN → referencia (sección 6 de la Etapa 1) | `src/catalogo/emparejamiento.py` |
| Informe por corrida (cobertura, completitud, coincidencias) | `src/extraccion/informe.py` |
| Captura diaria local programable | `scripts/captura_diaria.ps1` |
| Pruebas con respuestas reales guardadas | `tests/test_extraccion.py`, `tests/fixtures/` |
| Primera corrida completa y su informe | Sección 7 |

## 2. Cómo se captura cada sitio

Cada sitio se recorre en dos pasos: **descubrimiento** (qué fichas de televisores existen) y **captura** (precio, disponibilidad, EAN y vendedor de cada ficha).

| Sitio | Descubrimiento | Captura de la ficha | Formato | Navegador |
|---|---|---|---|---|
| Alkosto | Sitemap público `sitemap-productos.xml` filtrado por URL `/tv-…/p/{EAN}` | `/{slug}/p/{EAN}` | HTML con microdatos schema.org | No |
| Ktronix | Igual que Alkosto | Igual que Alkosto | HTML con microdatos | No |
| Jumbo | Índice de sitemaps → `product-N.xml` filtrado por `/televisor…/p` | API VTEX por ruta `/api/catalog_system/pub/products/search/{slug}/p` | JSON | No |
| Olímpica | Igual que Jumbo | Igual que Jumbo | JSON | No |
| Éxito | Listado `/tecnologia/televisores` y las 13 páginas por marca, con `?page=N` | Ficha `/{slug}/p`, que llega renderizada desde el servidor (`__NEXT_DATA__`) | HTML + JSON embebido | **Solo el listado** |

### Campos por plataforma

| Campo | Alkosto/Ktronix | Jumbo/Olímpica (VTEX) | Éxito |
|---|---|---|---|
| EAN | código de la URL y `itemprop=sku` | `items[].ean`; si falta, especificación `EAN` o `productReference` (solo si es un GTIN válido de 12–14 dígitos) | `skuData.AlternateIds.Ean` |
| Título | `h1[itemprop=name]` | `productName` | `product.name` |
| Referencia del fabricante | del título | especificación `Modelo` (si no, del título) | propiedad `Referencia` |
| Precio de venta | `itemprop=price` | `commertialOffer.Price` del vendedor propio | `sellers[sellerId=1].commertialOffer.Price` |
| Precio de lista | `previousPrice` del objeto de analítica | `ListPrice` | `ListPrice` |
| Disponibilidad | `itemprop=availability` (InStock) | `IsAvailable` y `AvailableQuantity > 0` | `AvailableQuantity > 0` |
| Vendedor | `itemprop=seller` (Alkosto/Ktronix) | `sellerId = 1` | `sellerId = 1` ("exito") |

## 3. Hallazgos que ajustaron el diseño de la Etapa 1

1. **Los sitemaps públicos reemplazan el barrido de EAN.** Alkosto y Ktronix publican todas sus fichas en `sitemap-productos.xml` (~30.000 productos, 327 televisores), con el EAN en la URL. Ya no hace falta consultar los 2.387 EAN del maestro (≈ 1 hora por sitio): el descubrimiento toma segundos y la captura completa, minutos. Jumbo y Olímpica también tienen sitemaps de productos.
2. **Olímpica prohíbe en su robots.txt toda URL con `&` o `%`** (`Disallow: /*&`). Eso impide paginar la búsqueda de la API (`?ft=…&_from=…&_to=…`), que es lo que se había usado en la prueba de viabilidad del Anexo A2 antes de notar la regla. Desde la Etapa 2 se descubre por sitemap y se consulta la API **por ruta y sin parámetros**, lo que el robots.txt permite. Lo mismo se aplica a Jumbo, por uniformidad.
3. **Éxito no necesita navegador para la ficha.** La ficha llega renderizada desde el servidor con todos los datos en `__NEXT_DATA__`, así que se descarga con el mismo cliente HTTP que los demás sitios. Playwright solo se usa para el listado, que sí se carga en el cliente. En la operación diaria (modo seguimiento) no se abre el navegador.
4. **En Éxito, el `gtin13` del JSON-LD no es el EAN:** contiene el SKU interno (p. ej. `3822830`). El EAN real está en `skuData.AlternateIds.Ean` (`6942351438313`). Leer el JSON-LD habría dado identificadores falsos.
5. **El orden del listado de Éxito cambia entre páginas**, y no se puede fijar porque su robots.txt prohíbe `sort=`. Para no perder fichas se recorren también las 13 páginas por marca que publica su sitemap.
6. **Las ofertas del marketplace conviven con las del vendedor propio.** En VTEX, un mismo producto puede tener un ítem vendido por un tercero con stock y otro del vendedor propio sin stock. Se guarda un registro por ítem, con el vendedor, y la clasificación marca `VENDEDOR_EXTERNO`.
7. **Códigos internos que parecen GTIN.** Un código interno de 8 dígitos de Olímpica (`10004029`) pasa el dígito de control por casualidad. Solo se aceptan GTIN de 12 a 14 dígitos, que es lo que usan los televisores.
8. **La especificación "Pulgadas" de Jumbo no es confiable** (un televisor de 32" figura con "50"). Las pulgadas se toman del título.
9. **Volumen de Bronze.** La ficha de Alkosto pesa 1,4 MB (≈ 135 KB comprimida). Una corrida completa deja ≈ 100 MB comprimidos, casi todo de Alkosto y Ktronix. En Azure el costo es despreciable; en local conviene guardar los datos fuera de OneDrive (variable `TFM_DATOS`).

## 4. Diseño del código

```
src/extraccion/
  ejecutar.py        orquestador: corre los sitios en paralelo y escribe salidas
  cliente.py         cliente HTTP por sitio: robots.txt, pausa, reintentos, bloqueo
  robots.py          intérprete de robots.txt con comodines (* y $)
  sitemap.py         lectura de sitemaps e índices
  bronze.py          guardado de respuestas crudas comprimidas
  modelos.py         esquema pydantic del registro de captura y de ejecuciones
  clasificacion.py   exclusiones previas al emparejamiento
  informe.py         métricas de una corrida
  sitios/
    sap_commerce.py  Alkosto y Ktronix
    vtex.py          Jumbo y Olímpica
    exito.py         Éxito (listado con Playwright, ficha con HTTP)
src/catalogo/emparejamiento.py   regla EAN → referencia
```

- **Un proceso, cinco tareas concurrentes** (`asyncio`): cada sitio lleva su propio ritmo, de modo que la duración total es la del sitio más lento y no la suma. Reemplaza los hilos por competidor del CoE131.
- **Los extractores son funciones puras** (`parsear_ficha`, `parsear_producto`): reciben el texto de la respuesta y devuelven registros. Por eso se prueban con respuestas guardadas, sin red.
- **Configuración externa (RNF-06):** sitios, rutas, patrones de URL, vendedor propio, pausas y reintentos están en `config/fuentes.yaml`.

## 5. Salidas

Bajo la raíz de datos (`data/` o la carpeta de `TFM_DATOS`), con la misma estructura que tendrá ADLS Gen2:

| Ruta | Contenido |
|---|---|
| `bronze/{sitio}/fecha=AAAA-MM-DD/{id_ejecucion}/nnnnn_{clave}.{html\|json}.gz` | Respuesta cruda de cada petición (RF-03) |
| `capturas/{sitio}/fecha=AAAA-MM-DD/{id_ejecucion}.csv` | Registros de captura (sección 4.1 de la Etapa 1), separador `;` |
| `ejecuciones/ejecuciones.csv` | Una fila por sitio y corrida (sección 4.2 de la Etapa 1) |
| `estado/objetivos_{sitio}.csv` | Fichas del último descubrimiento (las usa el modo seguimiento) |
| `informes/informe_{id_ejecucion}.md` | Informe de la corrida |

Cambios respecto al esquema de la Etapa 1:
- Se agregan `gtin14`, `en_alcance`, `motivo_exclusion` y `mensaje` al registro de captura.
- Se agrega el estado `PROHIBIDO_ROBOTS` (la URL no se pidió).
- El registro de ejecuciones suma `modo`, `descubiertos`, `sin_stock`, `bloqueados`, `registros` y `en_alcance`.
- `ruta_bronze` enlaza cada registro con su archivo crudo (RNF-05).

**Motivos de exclusión:** `VENDEDOR_EXTERNO`, `COMBO`, `NO_ES_TELEVISOR` (soportes, TV Box, monitores…), `NO_NUEVO`, `TECNOLOGIA_DESCONTINUADA`, `PRECIO_CERO`, `SIN_DATOS`.

## 6. Política de captura responsable (cómo se cumple en el código)

| Regla | Implementación |
|---|---|
| Cumplir robots.txt | Se descarga al iniciar cada sitio y se valida **cada URL antes de pedirla**. El intérprete propio entiende comodines (`/*?*facets=`, `/*&`), que `urllib.robotparser` no soporta. |
| No llegar a rutas prohibidas por redirección | Las redirecciones se siguen a mano y cada destino se valida antes de pedirlo (probado). |
| Ritmo bajo | Una petición a la vez por sitio y una pausa mínima de 1,5 s. |
| No evadir bloqueos | Ante 3 respuestas 403/429 seguidas se detiene el sitio y se registra `BLOQUEADO`. No se rotan IP ni identidades. |
| Identificación | User-Agent `TFM-MonitoreoPrecios/0.2 (proyecto academico…)`. En el navegador se añade al User-Agent estándar de Chromium. |
| Carga mínima | El navegador no descarga imágenes, fuentes ni videos. |
| Solo datos públicos | Fichas y listados abiertos, sin inicio de sesión. |

En el listado de Éxito, la propia página llama a sus servicios internos (`/api/…`) para mostrar los productos. El extractor no pide esas URL: solo abre la página permitida y lee lo que muestra.

## 7. Primera corrida completa

13 de octubre de 2026, de 22:38 a 23:15 (hora de Colombia). Primero se corrieron los cinco sitios a la vez; después se repitió Éxito para incluir las páginas por marca y corregir el título (secciones 3.5 y 7.4). Informe completo: `data/informes/informe_2026-10-13.md`.

### 7.1 Ejecución

| Sitio | Fichas descubiertas | Peticiones HTTP | Duración | Estado | Bloqueos / errores |
|---|---|---|---|---|---|
| Alkosto | 327 | 329 | 10,2 min | EXITOSA | 0 / 0 |
| Ktronix | 327 | 329 | 11,3 min | EXITOSA | 0 / 0 |
| Jumbo | 78 | 126 | 3,5 min (seguimiento: 2,0 min) | EXITOSA | 0 / 0 |
| Olímpica | 176 | 229 | 6,2 min | EXITOSA | 0 / 0 |
| Éxito | 460 (50 páginas de 13 listados) | 461 + 50 páginas | 19,3 min | EXITOSA | 0 / 0 |

Como los sitios corren en paralelo, **una corrida completa dura lo que tarda el sitio más lento: unos 19 minutos**, muy por debajo de la meta de 60 minutos del RNF-01, y deja margen para la transformación. Bronze ocupó 103 MB comprimidos (Alkosto 43, Ktronix 42, Éxito 15, Olímpica 2, Jumbo 0,7).

Los 26 y 27 `NO_ENCONTRADO` de Alkosto y Ktronix son fichas retiradas que siguen en el sitemap y redirigen a la categoría o al inicio. Se registran, pero no son fallas.

### 7.2 Alcance y completitud

| Sitio | Registros con datos | Completos (RNF-02) | TV propios en alcance | Con stock | Con EAN |
|---|---|---|---|---|---|
| Alkosto | 301 | 100 % | 243 | 175 | 100 % |
| Ktronix | 300 | 100 % | 242 | 175 | 100 % |
| Jumbo | 78 | 100 % | 74 | 72 | 100 % |
| Olímpica | 176 | 100 % | 69 | 68 | 100 % |
| Éxito | 460 | 100 % | 270 | 245 | 100 % |

**Exclusiones:** 171 ofertas del marketplace en Éxito y 99 en Olímpica; 35 reacondicionados en Alkosto (y los mismos 35 en Ktronix); 67 combos con barra de sonido; 5 que no son televisores (proyectores, TV Box, servicio de instalación) y 2 LCD portátiles. Se revisó una muestra de títulos de cada motivo y no se encontraron exclusiones indebidas, salvo los casos corregidos en la sección 7.4.

### 7.3 Emparejamiento preliminar (TV propios con stock)

| Sitio | Ofertas | En el maestro de Alkosto | En 2 o más cadenas | Emparejadas |
|---|---|---|---|---|
| Alkosto | 175 | 172 | 93 | 98,9 % |
| Ktronix | 175 | 172 | 93 | 98,9 % |
| Jumbo | 72 | 48 | 66 | 94,4 % |
| Olímpica | 68 | 45 | 53 | 85,3 % |
| Éxito | 245 | 143 | 113 | 69,0 % |
| **Total** | **735** | | | **87,2 %** |

Una oferta cuenta como emparejada si su producto está en el maestro o lo vende al menos otra cadena. Todas las ofertas en alcance traen un GTIN válido, así que en esta corrida todas se emparejaron por EAN y la regla por referencia no tuvo que actuar.

**Productos distintos según el número de cadenas que los venden** (Alkosto y Ktronix cuentan como una): 235 en una sola, **92 en dos, 27 en tres y 15 en las cuatro**. En total hay 134 productos comparables entre cadenas, frente a los 52 de la prueba de viabilidad (que no incluía Éxito).

**Por qué Éxito queda en 69 %:** sus 76 ofertas no emparejadas son surtido propio, es decir, modelos de Hisense (21), LG (14), Caixun (11) y Samsung (10) que ni Alkosto ni las demás cadenas venden. Solo 4 corresponden al mismo modelo con otro EAN. No son errores de la regla, sino productos que no tienen con quién compararse.

### 7.4 Ajustes hechos tras revisar la corrida

1. En Éxito, `product.name` es el nombre del SKU y en el marketplace a veces es solo el EAN. El título se toma de `skuData.ProductName`.
2. Se reconoce "Inch" como pulgadas ("TCL 75 Inch").
3. "Instalación TV hasta 55 pulgadas" se excluye como servicio (`NO_ES_TELEVISOR`).
4. Las fichas retiradas de Alkosto se registran con un mensaje explícito.

### 7.4.1 Corrección posterior: precios de 10 millones o más en Alkosto y Ktronix (15-oct-2026)

Al revisar plata en la Etapa 3 apareció un error de lectura. Los microdatos de SAP Commerce publican los precios de 10 millones o más en notación científica (`itemprop="price" content="3.99999E+7"`), y `a_entero` los leía como 3.999.997. Afectaba a **42 de 601 fichas** de esta corrida (21 por sitio), todas de 10 millones o más; el emparejamiento (por EAN) no cambia. Ahora el precio sale del objeto de analítica de la ficha (`price: '39999900'`, exacto), y `a_entero` acepta notación científica. Hay una prueba nueva con la ficha real (`tests/fixtures/alkosto_ficha_precio_alto.html.gz`). Los CSV locales de esta corrida (`data/`) conservan el error; en el lago se corrigió con el reproceso desde bronce (Etapa 3, sección 9.4).

### 7.5 Riesgo detectado en la regla por referencia

La regla de sufijo regional con coincidencia única uniría `C55VSUG` (LED) con `C55VSUGQ` (QLED) de Caixun, que son productos distintos. Como hoy todas las ofertas en alcance traen EAN, no afecta los resultados. Aun así, en Silver los emparejamientos por `REFERENCIA` se marcarán para revisión manual, y se evaluará si limitar la regla de prefijo a sufijos conocidos (`QG`, `PSA`, `KXZL`…).

## 8. Pruebas

`python -m pytest -q` ejecuta 58 pruebas (23 de la Etapa 1 y 35 de la Etapa 2), sin acceso a internet:
- robots.txt de Éxito, Olímpica y Alkosto (comodines, grupos repetidos y fin de ruta `$`);
- extracción con respuestas reales del 13-oct-2026: ficha con y sin stock de Alkosto; producto propio, producto con dos ítems (marketplace y propio) y producto del marketplace en Jumbo y Olímpica; ficha propia y del marketplace de Éxito, y listado de Éxito;
- clasificación (combos, accesorios, reacondicionados, LCD);
- cliente HTTP con un servidor simulado: no sigue redirecciones a rutas prohibidas, reintenta los errores 5xx y se detiene ante bloqueos;
- emparejamiento por EAN, por referencia con sufijo regional y exigencia de pulgadas iguales;
- informe: conteo de emparejados y de productos en varias cadenas.

Si un sitio cambia su estructura, se guarda una respuesta nueva en `tests/fixtures/` y las pruebas muestran qué campo dejó de extraerse.

## 9. Operación local

```powershell
.venv\Scripts\activate
python -m playwright install chromium                     # una vez
python -m src.extraccion.ejecutar                           # corrida completa, 5 sitios
python -m src.extraccion.ejecutar --modo seguimiento        # solo fichas conocidas (sin navegador)
python -m src.extraccion.ejecutar --sitios jumbo --limite 10
python -m src.extraccion.informe                            # informe de la última corrida
```

**Captura diaria desde la semana 4:** `scripts/captura_diaria.ps1` corre el modo completo los domingos y el seguimiento los demás días, y luego genera el informe. Se programa a las 06:00 con el Programador de tareas de Windows (el comando está en el encabezado del script). El computador debe estar encendido a esa hora; desde la Etapa 3 la ejecución pasa a Azure.

## 10. Pendientes para la Etapa 3

1. Empaquetar el extractor en una imagen Docker (base oficial de Playwright para Python) y ejecutarlo como Azure Container Apps Job.
2. Cambiar el destino de las salidas de disco local a ADLS Gen2, manteniendo las mismas rutas.
3. Llevar la clasificación y el emparejamiento a Silver (Spark), con el maestro como tabla de referencia.
4. Alertas a partir del registro de ejecuciones (sitio `FALLIDA` o `PARCIAL`).

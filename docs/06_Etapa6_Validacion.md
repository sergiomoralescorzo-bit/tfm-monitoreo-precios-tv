# Etapa 6 — Validación

**Versión 0.1 (17-oct-2026), preliminar.** Mide las métricas de la Etapa 1 (sección 10) con los dos días que hay en el lago (13 y 14-oct). Las métricas automáticas se recalculan con más días, después de que los disparadores (activos desde el 17-oct) acumulen datos. La exactitud de precio y la reducción de esfuerzo dependen del equipo (sección 4).

## 1. Cómo se mide

`src/validacion/` (pruebas en `tests/test_validacion.py`) calcula en dos pasos:

| Paso | Dónde corre | Qué hace |
|---|---|---|
| `bajar` | Equipo local con `az login` | Copia `plata/` y `oro/` del lago (unos 3,7 MB), lista las rutas de evidencia de bronce y guarda las corridas de las pipelines de Synapse |
| `calcular` | Imagen `tfm-medallon` (Spark 3.4 + Delta 2.4) | Calcula las métricas y escribe el informe y los CSV en `data/validacion/<fecha>/` |

```powershell
# 1. Bajar (desde la raíz del proyecto)
.venv\Scripts\python -m src.validacion.metricas bajar --lago <carpeta fuera de OneDrive>

# 2. Calcular (Git Bash; MSYS_NO_PATHCONV evita que se conviertan las rutas)
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/app" -v "<carpeta>:/lago" -e PYTHONPATH=/app \
  --entrypoint python acrtfmwebscraping.azurecr.io/tfm-medallon:0.5 \
  -m src.validacion.metricas calcular --lago /lago --salida /app/data/validacion/<fecha> [--muestra 12]
```

Salidas:
- `informe_validacion.md`
- `metricas.json`
- `no_unidos.csv`
- `atipicos.csv`
- con `--muestra N`, `muestra_exactitud_<fecha>.csv`

## 2. Definiciones operativas

| Métrica | Fórmula | Fuente |
|---|---|---|
| Completitud (RNF-02) | Registros con identificador (EAN o SKU), precio de venta > 0, título y fecha de captura / registros con datos (`OK` o `SIN_STOCK`) | plata `precios/ofertas`, última corrida del día por sitio |
| Cobertura (RNF-03) | Fichas (URL distintas) con datos / fichas consultadas que siguen publicadas (sin las `NO_ENCONTRADO`, que son fichas retiradas del sitemap) | plata `control/ejecuciones` + ofertas |
| Emparejamiento por ofertas | Ofertas en alcance con stock cuyo producto está en el maestro o en ≥ 2 cadenas / ofertas en alcance con stock (definición de la Etapa 2) | oro `kpi_calidad_captura` |
| Emparejamiento por productos | Productos en ≥ 2 cadenas / (esos + productos que la regla dejó separados). Un producto separado es uno que dos cadenas venden con la misma clave marca \| pulgadas \| referencia normalizada, pero con GTIN distinto | plata, `src/validacion/reglas.py` |
| Tiempo (RNF-01) | Peor duración de `pl_captura_diaria` + peor duración de `pl_medallon_diario` (antes `pl_medallon_semanal`), de punta a punta en Synapse | Corridas de Synapse |
| Duplicados (RNF-04) | Filas − combinaciones distintas (día, producto, tienda) | oro `fact_precio_diario` |
| Trazabilidad (RNF-05) | Filas cuya `ruta_bronze` existe en `bronce/aterrizaje/{sitio}/capturas` / filas | oro + listado del lago |

**Alcance de las dos definiciones de emparejamiento:**
- **Por productos** se acerca más a la fórmula de la Etapa 1. Su denominador se estima solo con coincidencias exactas de la clave, así que no detecta los pares con referencias distintas; es una cota superior.
- **Por ofertas** es más exigente: cuenta como no emparejado el surtido propio que ninguna otra cadena vende.

## 3. Resultados preliminares (13 y 14-oct-2026)

| Métrica | Valor | Meta | Cumple |
|---|---|---|---|
| Completitud | 100,0 % (2.636 de 2.636 registros) | ≥ 90 % | Sí |
| Cobertura | 100,0 % (2.633 fichas vigentes) | ≥ 90 % | Sí |
| Emparejamiento por ofertas | 87,2 % (641 de 735 y 643 de 737) | ≥ 80 % | Sí |
| Emparejamiento por productos | 99,3 % (134 en ≥ 2 cadenas, 1 separado por día) | ≥ 80 % | Sí |
| Tiempo captura + medallón | 40,1 min (34,3 + 5,8) | < 60 min | Sí |
| Duplicados | 0 de 1.800 filas | 0 | Sí |
| Trazabilidad a bronce | 100 % (1.800 de 1.800 rutas existen en el lago) | 100 % | Sí |
| Exactitud de precio | Pendiente (sección 4) | ≥ 80 % | — |
| Reducción de esfuerzo | Pendiente (sección 4) | ≥ 75 % | — |

**Detalle y observaciones:**
- **Cobertura:** las fichas retiradas son 26 en Alkosto, 27 en Ktronix y 0 a 2 en Jumbo y Olímpica. Se registran con `NO_ENCONTRADO` porque siguen en el sitemap y redirigen a la categoría. Ningún sitio tuvo errores ni bloqueos.
  - La cobertura se mide contra lo que el propio sitio publica en su sitemap o listado. El contraste externo es el conteo de televisores que el equipo haga en la categoría de cada sitio el mismo día (sección 4).
- **Producto separado:** Samsung 75" `VGSCFH75SGMZX`. Alkosto y Ktronix lo venden con el GTIN `08806099442781` y Éxito con el `08806099442767`.
  - Puede ser el mismo modelo con otro EAN o una variante. Queda para la revisión manual (`bronce/aterrizaje/revision/decisiones.csv`, decisión `CORREGIR` o `RECHAZAR`).
- **Tiempo:** la captura en Azure (34,3 min) incluye arrancar el contenedor y subir al lago. Solo el registro de ejecuciones mide 25,2 min con los 5 sitios en paralelo, que es lo que tarda el sitio más lento.
  - El medallón semanal tomó entre 4,1 y 5,8 min en sus 4 corridas exitosas.
  - La única corrida fallida (15-oct, 0,5 min) es anterior a la corrección de la Etapa 3, sección 9.
- **Hueco en la serie:** del 15 al 17-oct no hubo captura, porque los disparadores se activaron el 17-oct. La serie salta del 14 al 18-oct.

### 3.1 Precios atípicos (control de calidad)

Las reglas están en `src/medallon/atipicos.py` y las comparten plata y la validación.

**Desde el 17-oct, en plata y en el tablero** (decisión del equipo):
- `plata/precios/ofertas` y `oro.fact_precio_diario` tienen la columna `motivos_atipico`. Se evalúa sobre el precio diario (última captura del día por producto y sitio) y se copia a todas las ofertas de ese producto, sitio y día.
- La imagen es `tfm-medallon:0.4` y el medallón corrió en Azure en 4,1 min (`9fcbee28-…`).
- En Power BI está la medida *Precios atípicos* en la página "Calidad de la captura".

La validación las vuelve a aplicar sobre `fact_precio_diario`, para cubrir también los datos anteriores a la columna:

| Motivo | Regla |
|---|---|
| `SIN_PRECIO`, `BAJO_RANGO`, `SOBRE_RANGO` | Precio de venta ≤ 0, menor de $200.000 o mayor de $80.000.000 |
| `VENTA_MAYOR_QUE_LISTA` | Precio de venta mayor que el de lista |
| `DESCUENTO_EXCESIVO` | Descuento mayor del 70 % sobre el precio de lista |
| `LEJOS_DE_OTRAS_CADENAS` | Con stock, por debajo de la mitad o por encima del doble de la mediana de **al menos otras 2 cadenas** el mismo día. Con una sola cadena de referencia no se sabe cuál de las dos se aparta: eso ya se refleja en la brecha |
| `CAMBIO_BRUSCO` | Con stock, variación de más del 50 % frente al día anterior con stock en el mismo sitio (desde el 19-oct, imagen `tfm-medallon:0.5`) |

**Resultado:** 4 de 1.800 filas, todas `DESCUENTO_EXCESIVO` en Éxito:
- Caixun 50" a $999.900 frente a una lista de $3.499.900 (71 %);
- Caixun 55" a $1.149.900 frente a una lista de $3.999.900 (71 %);
- cada uno, los dos días.

La lectura es correcta, porque el sitio publica esos dos precios. El precio de lista parece inflado, y eso afecta el `descuento_pct` del tablero, no el precio de venta.

**Prueba con un error conocido:** en los CSV locales del 13-oct sigue el error de notación científica de la Etapa 2 (sección 7.4.1): precios de 10 millones o más leídos como unos 4 millones. Con esos datos, las reglas marcan 30 filas con `DESCUENTO_EXCESIVO` y 2 con `DESCUENTO_EXCESIVO,LEJOS_DE_OTRAS_CADENAS` (prueba `tests_spark`, datos reales). El control habría detectado ese error sin revisión manual.

En la primera versión la regla de cadenas comparaba también productos sin stock y con una sola cadena de referencia, y marcaba 24 filas más. Se revisaron: eran diferencias reales (por ejemplo, el Samsung 48" S90F OLED de Éxito a $3.249.900, sin stock en Alkosto a $7.099.900) y no errores de lectura.

**Ajuste del 19-oct: precio sin stock en Éxito.** Con el 19-oct, la regla marcó 5 `CAMBIO_BRUSCO` nuevos, todos en Éxito y sin stock. Por ejemplo, el TCL 65" C6K pasó de $3.999.900 a $7.999.900, y la LG OLED55B6 de $3.999.900 a $7.499.900.
- La página guardada en bronce muestra la causa: cuando no hay stock (`AvailableQuantity: 0`), VTEX publica `Price = ListPrice`. El "precio" de ese día es el precio de lista, no una oferta.
- La extracción es correcta: copia lo que publica el sitio.
- El tablero no se veía afectado, porque las medidas de precio de oro y Power BI ya filtran `disponible = TRUE`.
- Solo fallaba la regla, por dos razones: comparaba el día sin stock, y lo habría usado como referencia para marcar otra vez la vuelta al precio con stock.
- Ahora `CAMBIO_BRUSCO` solo compara días con stock (`tests/test_validacion.py`).
- Con el 13, el 14 y el 19-oct quedan 6 filas, todas los `DESCUENTO_EXCESIVO` de los Caixun.
- Plata y oro se actualizan con el medallón del 25-oct.

## 4. Pendiente con el equipo

1. **Exactitud de precio:** después de la captura del domingo 18-oct (06:00), se genera la muestra con `--muestra 12`: 12 ofertas con stock por tienda, unas 60 en total, con semilla igual a la fecha. El mismo día, el equipo abre cada URL y anota:
   - el precio observado;
   - la fecha y hora de la revisión;
   - si coincide (S/N);
   - una observación.

   Con 60 casos, un resultado del 90 % tiene un margen de unos ±8 puntos (95 %).
2. **Cobertura externa:** ese mismo día, anotar cuántos televisores muestra la categoría de cada sitio, para contrastarlo con las fichas capturadas.
3. **Reducción de esfuerzo:** estimar cuántas horas por semana tomaría la revisión manual equivalente (5 sitios, unas 700 ofertas con stock al día) y cuántas toma hoy la supervisión (revisar avisos y el tablero).
4. ~~Decidir si los atípicos pasan a plata~~: hecho el 17-oct (sección 3.1).
5. **Volver a calcular** con al menos una semana de datos.

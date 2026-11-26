# Etapa 5 — Tablero en Power BI

**Versión:** 0.1 (16 de octubre de 2026). El proyecto está generado, abre sin errores en Power BI Desktop 2.158 y ya se actualizó con los datos del 13 y el 14 de octubre. Las cifras coinciden con la Etapa 4.
**Objetivo específico que cubre:** *Visualizar los precios, la brecha entre cadenas y la calidad de la captura para apoyar la toma de decisiones.*
**Requerimientos que atiende (Etapa 1):** RF-08; insumo de las métricas de validación de la Etapa 6 (sección 10).

---

## 1. Entregables

| Entregable | Ubicación |
|---|---|
| Proyecto de Power BI (PBIP, formato de texto versionable) | `powerbi/TFM_Precios.pbip` |
| Modelo semántico en TMDL: 7 tablas, 9 relaciones, 23 medidas (22 + *Precios atípicos*, del 17-oct) | `powerbi/TFM_Precios.SemanticModel/` |
| Informe en PBIR: 4 páginas | `powerbi/TFM_Precios.Report/` |
| Generador del proyecto y validador contra los esquemas de Microsoft | `powerbi/herramientas/` |

**Cambio del 17-oct (Etapa 6):** se regeneró el proyecto con el generador. No había ediciones hechas en Desktop: todos los archivos eran del 16-oct.
- Novedades:
  - la columna `fact_precio_diario[motivos_atipico]`;
  - la medida *Precios atípicos*, con el número de filas marcadas;
  - una sexta tarjeta en la página "Calidad de la captura".
- El validador da 57 archivos y 0 errores.
- **Falta abrirlo en Desktop y actualizarlo:** en los dos días la tarjeta debería mostrar 4.

Se usa **PBIP** y no un `.pbix` porque guarda el modelo y el informe como texto. Así se pueden revisar los cambios, compararlos y versionarlos junto con el código, y se reconstruye con el generador. Para abrirlo hay que hacer doble clic en `TFM_Precios.pbip` y luego *Archivo → Guardar como* si se necesita un `.pbix` para entregar.

## 2. Modelo semántico

- **Origen:** las 7 vistas `oro.*` de `tfm_oro` (Etapa 4) en modo **Importación**, con dos parámetros: `Servidor` (`syn-tfm-webscraping-ondemand.sql.azuresynapse.net`) y `BaseDatos` (`tfm_oro`). Para apuntar a otro entorno basta con cambiar los parámetros.
- **Relaciones:** las 9 de la Etapa 4 (sección 3.1). Todas son de uno a varios y filtran en una sola dirección.
- **Tabla de fechas:** `dim_calendario` está marcada como tabla de fechas (`fecha`). `nombre_mes` y `nombre_dia` se ordenan por su número.
- Las claves técnicas (`*_key`) están ocultas, y los precios no se suman por defecto: se usan las medidas.

| Carpeta | Medidas |
|---|---|
| Precios (`fact_precio_diario`) | Ofertas, Productos, Precio mínimo, Precio promedio, Precio máximo, Descuento promedio, Última fecha con precio, **Precio mínimo último día**, **Tienda más barata**, **Enlace tienda más barata** (20-oct), Tiendas con oferta |
| Brecha entre cadenas (`kpi_brecha_precio`) | Productos comparados, Brecha promedio %, Brecha máxima %, Brecha promedio $, Veces más barata |
| Calidad (`kpi_calidad_captura`) | Emparejamiento %, Completitud % (ponderada por registros con datos), Registros capturados |
| Ejecuciones (`fact_ejecucion`) | Ejecuciones, Ejecuciones fallidas, Tasa de éxito, Duración promedio (min) |

Notas de diseño:
- Los precios se calculan **solo con ofertas con stock** (`disponible = TRUE`).
- *Precio mínimo último día* toma el último día con precio del periodo filtrado para cada producto, así un producto que ya no aparece no se compara con precios viejos de otro. *Tienda más barata* lista todas las tiendas empatadas en ese precio.
- *Emparejamiento %* es la razón de sumas (emparejadas / ofertas con stock), no el promedio de porcentajes, igual que en la verificación de la Etapa 4.

## 3. Informe

| Página | Contenido | RF-08 |
|---|---|---|
| **Resumen de precios** | Filtros (fecha, marca, pulgadas con sus valores directos, tecnología, tienda); 5 tarjetas (productos con precio, registros, precio más bajo, brecha promedio, emparejamiento); tabla de **menor precio por producto** con la tienda más barata | Menor precio por producto |
| **Brecha entre cadenas** | Tarjetas de brecha; brecha por marca y por tamaño; cadena que más veces tiene el menor precio; productos con mayor brecha | Brecha porcentual entre cadenas |
| **Evolución diaria** | Filtro por producto; precio promedio por tienda, brecha promedio y productos con precio por día | Evolución diaria |
| **Calidad de la captura** | Completitud, emparejamiento, ejecuciones exitosas, duración y fallas; métricas por tienda y por día; detalle de cada ejecución | Métricas de la Etapa 1, sección 10; RF-07 |

Todas las páginas tienen los filtros de marca, pulgadas y tecnología que pide RF-08, y desde el 20-oct un botón **Restablecer filtros** arriba a la derecha, que borra todos los segmentadores de la página (en Desktop se activa con Ctrl+clic).

### 3.1. Diseño visual (20-oct)

Se aplica con `powerbi/herramientas/redisenar_informe.py`, que edita los archivos PBIR existentes y se puede volver a ejecutar sin efectos duplicados.

**Paleta provisional.** No se recibió el logotipo ni el material de una marca principal, y el tablero compara 4 cadenas. Por eso la interfaz usa un azul marino neutro y cada tienda conserva su propio color.

| Uso | Color |
|---|---|
| Encabezado y menú, valores de las tarjetas | Marino `#14365D` (botón al pasar el cursor: `#1F4A7A`) |
| Series sin tienda (por ejemplo, brecha por marca) | Pizarra `#4A6B8A` y `#9FB4C9` |
| Fondo de página / tarjetas / bordes | `#F4F6F9` / `#FFFFFF` / `#E1E6ED` |
| Texto principal / secundario | `#1B2A3A` / `#5B6B7C` |
| Tiendas | Alkosto `#1F5AA6`, Ktronix `#5FA8E8` (misma cadena, tono hermano), Jumbo `#7A4FB5`, Olímpica `#C2367A`, Éxito `#E0A100` |
| Estados de calidad (no se usan para tiendas) | OK `#1E7B34`, alerta `#B54708`, error `#B42318`, sin datos `#8A94A3`; siempre acompañados de texto |

**Tema** (`StaticResources/RegisteredResources/TFM_Tema.json`): Segoe UI; títulos de 12 pt Semibold; etiquetas, ejes, leyendas y tablas de 10 pt; cifras de las tarjetas de 22 pt; visuales blancos con borde de 1 px y radio de 8; sin títulos de eje y tablas sin totales.

**Navegación.**
- Nueva página **Inicio**, que es la página de apertura. Tiene 4 tarjetas con ícono, nombre, descripción y «Abrir sección». Cada tarjeta es un botón transparente de navegación a página que se oscurece al pasar el cursor.
- Inicio muestra también la leyenda de colores por tienda y la fuente de los datos.
- Todas las páginas tienen un **menú superior** (Inicio, Vista general, Brechas, Evolución, Calidad). La sección activa aparece en blanco; las demás cambian de color al pasar el cursor y al pulsar.

**Cuadrícula común** (1280 × 720, 16:9, márgenes de 24 px):

| Franja | Posición |
|---|---|
| Encabezado | y de 0 a 64 |
| Filtros, con el botón «Restablecer filtros» a la derecha | y de 76 a 140 |
| Indicadores | y de 152 a 236 |
| Contenido | y de 248 a 696 |

Evolución diaria no tiene indicadores, así que su contenido empieza en y = 152.

**Filtros.**
- Van en orden de relevancia: fecha, marca, pulgadas, tecnología, tienda y producto.
- Se sincronizan entre páginas por campo (grupos `fecha`, `marca`, `pulgadas`, `tecnologia` y `tienda`), así que la selección se conserva al navegar.
- Todas las páginas usan las pulgadas exactas.

**Ayudas.** Cada indicador tiene un ícono de información con su definición; las metas se indican donde aplica.

**Cero frente a sin datos.** *Ejecuciones fallidas* y *Precios atípicos* muestran 0 cuando hay datos y no hubo casos, y quedan en blanco solo cuando no hay datos en el periodo. Antes, *Ejecuciones fallidas* aparecía «En blanco» con 23 ejecuciones y ninguna fallida.

## 4. Validación (16-oct)

| Control | Resultado |
|---|---|
| 56 archivos JSON del informe contra los esquemas oficiales (report 3.2.0, page 2.1.0, visualContainer 2.7.0) | **0 errores**. El validador sí detecta errores: se probó con un visual dañado a propósito |
| Apertura en Power BI Desktop 2.158 (Microsoft Store) | Abre el modelo, las vistas Modelo, DAX y TMDL, y el informe; los visuales ejecutan sus consultas |
| Estado de las 22 medidas en el motor local (`$SYSTEM.TMSCHEMA_MEASURES`) | **22 en estado Ready**: el DAX compila |
| Relaciones | 9 activas |
| Registro de Desktop | Solo hay errores de servicios en la nube ajenos al proyecto (Copilot, 401) y un primer intento de carga que se reintentó bien. Hay una advertencia `DateSlicerNoData` porque el modelo todavía no tenía datos |
| Actualización completa (con cuenta de UNIR) | 11 s, sin errores |
| Medidas con datos frente a la Etapa 4 | Ofertas 1.800 (898 + 902), productos 436, emparejamiento 87,2 % cada día, 134 productos comparados, brecha máxima 40,1 %, 13 ejecuciones con 100 % de éxito: **todo coincide** |
| *Tienda más barata* | Lista los empates, por ejemplo "Alkosto, Jumbo, Ktronix, Olímpica" en el CHALLENGER 65" a $ 3.099.900 |

## 5. Primera actualización (manual, una vez por equipo)

1. Abrir `powerbi/TFM_Precios.pbip` en Power BI Desktop.
2. *Inicio → Actualizar*. En la ventana de credenciales de **Base de datos SQL Server**, elegir **Cuenta de Microsoft** e iniciar sesión con la cuenta de UNIR. No usar *Windows*, porque el endpoint serverless solo acepta Entra ID.
3. Tienen acceso los tres integrantes del equipo (uno como administrador).

Cada actualización procesa unos 70 MB en SQL serverless, menos de USD 0,001, y está dentro del tope diario de 1 TB.

## 6. Pendientes

1. Revisión visual de las 4 páginas por el equipo. La primera actualización ya se hizo; cada integrante repite la sección 5 en su equipo.
   - **20-oct, Resumen de precios:** la tarjeta *Ofertas* se llama ahora *Registros* (misma medida); *Precio promedio* se cambió por *Precio más bajo* (medida `Precio mínimo`: menor precio de venta con stock); el segmentador de pulgadas usa la columna `pulgadas` (valores directos) en lugar de `rango_pulgadas`. Además, la tarjeta *Precio más bajo* muestra el valor completo (unidades: Ninguno), y la tabla de menor precio tiene como última columna *Ver en la tienda*: el enlace a la ficha de la tienda más barata (medida nueva `Enlace tienda más barata`, categoría URL web). Faltan las observaciones de las otras 3 páginas.
2. Publicar en el servicio Power BI (área de trabajo de UNIR) y programar la actualización diaria después del medallón (desde las 07:00). Requiere licencia Pro o PPU (el equipo la gestiona más adelante) y una puerta de enlace o credenciales OAuth en el servicio; lo decide el equipo.
3. Ajustes de formato y tema según la plantilla del TFM.
4. Etapa 6: usar la página de calidad como evidencia de las métricas de validación.

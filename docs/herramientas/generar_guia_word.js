// Genera la guía de revisión del TFM en Word.
// Refleja el estado al 19-oct-2026 (imágenes tfm-captura:0.4 y tfm-medallon:0.5, captura con 1 vCPU y 2 GiB). Las versiones vigentes
// son tfm-captura:0.7 y tfm-medallon:0.8 (infra/desplegar.ps1). El Word generado se conserva como registro de esa fecha.
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType,
  ShadingType, BorderStyle, ImageRun, TableLayoutType, AlignmentType, LevelFormat, Footer, PageNumber,
} = require("docx");

const [, , salida, imagen] = process.argv;
const ANCHO = 9360; // carta con márgenes de 1"
const FUENTE = "Calibri";

function runs(texto, base = {}) {
  return texto.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/).filter(Boolean).map((t) => {
    if (t.startsWith("`")) return new TextRun({ ...base, text: t.slice(1, -1), font: "Consolas", size: 18 });
    if (t.startsWith("**")) return new TextRun({ ...base, text: t.slice(2, -2), bold: true });
    if (t.startsWith("*")) return new TextRun({ ...base, text: t.slice(1, -1), italics: true });
    return new TextRun({ ...base, text: t });
  });
}
const p = (t, opts = {}) => new Paragraph({ children: runs(t), spacing: { after: 120 }, ...opts });
const h1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)] });
const h2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] });
const vineta = (t) => new Paragraph({ numbering: { reference: "vinetas", level: 0 }, children: runs(t), spacing: { after: 60 } });
const casilla = (t) => new Paragraph({ children: [new TextRun({ text: "☐  " }), ...runs(t)], indent: { left: 360, hanging: 360 }, spacing: { after: 60 } });

const borde = { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" };
const bordes = { top: borde, bottom: borde, left: borde, right: borde };
function tabla(encabezados, filas, proporciones) {
  const total = proporciones.reduce((a, b) => a + b, 0);
  const anchos = proporciones.map((x) => Math.floor((x / total) * ANCHO));
  anchos[anchos.length - 1] += ANCHO - anchos.reduce((a, b) => a + b, 0);
  const celda = (t, i, cab) => new TableCell({
    width: { size: anchos[i], type: WidthType.DXA }, borders: bordes,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    shading: cab ? { type: ShadingType.CLEAR, color: "auto", fill: "DCE6F2" } : undefined,
    children: [new Paragraph({ children: runs(t, { size: 19, bold: cab || undefined }) })],
  });
  return new Table({
    width: { size: ANCHO, type: WidthType.DXA }, columnWidths: anchos, layout: TableLayoutType.FIXED,
    rows: [
      new TableRow({ tableHeader: true, children: encabezados.map((t, i) => celda(t, i, true)) }),
      ...filas.map((f) => new TableRow({ children: f.map((t, i) => celda(t, i, false)) })),
    ],
  });
}
const espacio = () => new Paragraph({ spacing: { after: 60 }, children: [] });

const contenido = [
  new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun("Guía de revisión del proyecto TFM — Monitoreo de precios de televisores")] }),
  p("Estado al 19-oct-2026", { children: [new TextRun({ text: "Estado al 19-oct-2026", italics: true, color: "595959" })] }),
  p("El sistema captura cada día los precios de televisores de 5 sitios (Alkosto, Ktronix, Éxito, Jumbo y Olímpica), los procesa cada día en un lago con arquitectura medallón y los muestra en Power BI. Todo corre en Azure, sin depender de ningún equipo local. Hasta el 19-oct hay 15 recursos en Azure, 51 archivos Python (99 pruebas en verde) y 6 etapas, 5 de ellas aprobadas."),

  h1("Cómo encaja todo"),
  new Paragraph({ alignment: AlignmentType.CENTER, children: [new ImageRun({ type: "png", data: fs.readFileSync(imagen), transformation: { width: 600, height: 391 }, altText: { title: "Flujo del sistema", description: "Cada día Synapse encadena la captura y el medallón; el lago guarda bronce, plata y oro; SQL serverless y Power BI leen oro.", name: "flujo" } })] }),
  p("Cada día a las 06:00, Synapse inicia la captura, que deja los precios en bronce. Apenas la captura termina bien, el mismo orquestador inicia el medallón, que lee bronce y escribe plata y oro. SQL serverless publica oro como 7 vistas que lee Power BI. Si algo falla o no corre, llegan avisos por correo y Teams. El equipo local solo se usa para desarrollar, construir imágenes y revisar."),

  h1("Estado por etapa"),
  p("Cinco etapas están aprobadas y la validación (Etapa 6) está en curso. Cada etapa tiene su documento en `TFM_MonitoreoPrecios/docs/`, y la bitácora (`BITACORA.md`) registra las 14 sesiones de trabajo."),
  tabla(["Etapa", "Estado", "Qué se logró", "Documento"], [
    ["1. Requerimientos y arquitectura", "Aprobada (v0.2)", "Alcance: televisores, 4 cadenas y 5 sitios; regla de emparejamiento; metas de calidad", "`01_Etapa1_Requerimientos_y_Arquitectura.md`"],
    ["2. Extracción", "Aprobada (v0.1)", "5 extractores responsables (robots.txt, pausas, User-Agent identificable). Se corrigió el error de notación científica en precios de 10 M o más", "`02_Etapa2_Extraccion.md`"],
    ["3. Orquestación y medallón", "Aprobada (v0.2)", "Captura y medallón diarios en Azure, encadenados por un orquestador, avisos por correo y Teams, vigilancia diaria", "`03_Etapa3_Orquestacion_y_Medallon.md`"],
    ["4. Modelo estrella", "Aprobada (v0.2)", "7 vistas en SQL serverless (`tfm_oro`), 0 duplicados y 0 huérfanas", "`04_Etapa4_Modelo_Estrella.md`"],
    ["5. Power BI", "Aprobada (v0.1)", "PBIP con 4 páginas y 23 medidas. Falta la revisión visual del equipo", "`05_Etapa5_PowerBI.md`"],
    ["6. Validación", "En curso (v0.1)", "Las 7 métricas automáticas cumplen con 3 días de datos. Faltan la exactitud manual, la reducción de esfuerzo y recalcular con una semana", "`06_Etapa6_Validacion.md`"],
  ], [20, 13, 40, 27]),
  espacio(),
  p("La serie de datos empieza el 13-oct: hay datos del 13, el 14 y el 19-oct. Del 15 al 18-oct no se capturó, porque los disparadores se activaron el 17-oct y el 18-oct no corrieron."),

  h1("Recursos y servicios de Azure"),
  p("El grupo `RG-TFM-WEBSCRAPING` (Azure for Students, crédito de USD 100) tiene 15 recursos: 12 están en uso, 2 no se usan y 1 depende de una cuota pendiente. Casi todo está en West US; el lago y el Data Factory están en East US."),
  tabla(["Recurso", "Servicio", "Para qué sirve", "Estado"], [
    ["`sttfmwebscraping` (contenedor `datalake-tfm`)", "Storage, Data Lake Gen2", "El lago: bronce, plata, oro, maestro, revisión y código", "En uso"],
    ["`syn-tfm-webscraping`", "Azure Synapse Analytics", "Pipelines, disparadores y SQL serverless (BD `tfm_oro`)", "En uso"],
    ["`syn-tfm-webscraping/sptfm`", "Pool de Spark de Synapse", "Medallón con notebook (opción A)", "Sin uso: la cuota de Spark es 0"],
    ["`acrtfmwebscraping`", "Container Registry (Basic)", "Guarda las imágenes `tfm-captura:0.4` y `tfm-medallon:0.5`", "En uso"],
    ["`cae-tfm-webscraping`", "Entorno de Container Apps", "Entorno de consumo donde corren los dos jobs", "En uso"],
    ["`caj-tfm-captura`", "Container Apps Job", "La captura diaria de los 5 sitios (1 vCPU, 2 GiB)", "En uso"],
    ["`caj-tfm-medallon`", "Container Apps Job", "El medallón con Spark local (2 vCPU, 4 GiB)", "En uso"],
    ["`id-tfm-captura`", "Identidad administrada", "Permite que los jobs bajen imágenes y escriban en el lago sin claves", "En uso"],
    ["`workspace-gmYJ`", "Log Analytics", "Registros de los contenedores", "En uso"],
    ["`la-tfm-notificaciones`", "Logic App", "Envía el correo y la tarjeta de Teams cuando algo falla", "En uso"],
    ["`la-tfm-vigilancia`", "Logic App", "A las 09:30 revisa que la captura y el medallón hayan corrido", "En uso desde el 19-oct"],
    ["`office365-tfm`", "Conexión de API (Outlook)", "La cuenta que envía los correos", "En uso"],
    ["`ag-tfm-fallos`", "Grupo de acciones (Monitor)", "Lista de los 3 correos que reciben alertas", "En uso"],
    ["`alerta-tfm-pipelines-fallidas`", "Alerta de métrica (Monitor)", "Respaldo: avisa si cualquier pipeline termina en Failed", "En uso"],
    ["`ADF-TFM-WEBSCRAPING`", "Data Factory", "Se creó al inicio; las pipelines quedaron en Synapse", "Sin uso (no cobra)"],
  ], [28, 22, 34, 16]),
  espacio(),
  p("Fuera de Azure se usan: Power BI Desktop (archivos PBIP), Microsoft Teams (canal de alertas) y Docker Desktop en el equipo local, solo para construir las imágenes y correr pruebas. Ningún proceso programado corre en el equipo local: se verificó que no hay tareas del TFM en el Programador de tareas de Windows."),

  h1("Código Python"),
  p("Hay 51 archivos Python. 37 son del sistema y están en `src/` (7 de ellos son `__init__.py` vacíos), 9 son pruebas en `tests/` y `tests_spark/`, 2 son herramientas de Power BI y 3 son código archivado del primer alcance (iPhone). Todas las rutas son relativas a `TFM_MonitoreoPrecios/`. La columna «Corre en» indica dónde se ejecuta el módulo en producción."),
  tabla(["Carpeta", "Archivo", "Qué hace", "Corre en"], [
    ["`src/catalogo/`", "`atributos_tv.py`", "Saca marca, pulgadas, referencia, tecnología y resolución del título", "Job de medallón"],
    ["`src/catalogo/`", "`construir_maestro.py`", "Construye el maestro de televisores desde la hoja DIM_PRODUCTO", "Local, una vez"],
    ["`src/catalogo/`", "`emparejamiento.py`", "Regla para unir el mismo televisor entre cadenas (Etapa 1, sección 6)", "Job de medallón"],
    ["`src/catalogo/`", "`gtin.py`", "Normaliza y valida códigos EAN-13, UPC-A y GTIN-14", "Captura y medallón"],
    ["`src/extraccion/`", "`ejecutar.py`", "Corrida completa de los 5 sitios", "Job de captura"],
    ["`src/extraccion/`", "`cliente.py`", "Cliente HTTP responsable: robots.txt, una petición a la vez, pausas y 3 reintentos", "Job de captura"],
    ["`src/extraccion/`", "`robots.py`", "Lee robots.txt con comodines (RFC 9309)", "Job de captura"],
    ["`src/extraccion/`", "`sitemap.py`", "Lee los sitemaps XML para descubrir fichas", "Job de captura"],
    ["`src/extraccion/`", "`bronze.py`", "Guarda cada respuesta original comprimida (evidencia)", "Job de captura"],
    ["`src/extraccion/`", "`clasificacion.py`", "Excluye lo que no es un televisor antes de emparejar", "Job de captura"],
    ["`src/extraccion/`", "`modelos.py`", "Esquema del registro de precio y del registro de ejecución", "Job de captura"],
    ["`src/extraccion/`", "`informe.py`", "Informe de una corrida: cobertura, completitud y coincidencias", "Local"],
    ["`src/extraccion/`", "`reproceso.py`", "Vuelve a extraer desde la evidencia guardada, sin pedir nada a los sitios", "Local"],
    ["`src/extraccion/sitios/`", "`base.py`", "Piezas comunes a los extractores", "Job de captura"],
    ["`src/extraccion/sitios/`", "`sap_commerce.py`", "Alkosto y Ktronix: ficha HTML con microdatos schema.org", "Job de captura"],
    ["`src/extraccion/sitios/`", "`vtex.py`", "Jumbo y Olímpica: API pública de catálogo VTEX", "Job de captura"],
    ["`src/extraccion/sitios/`", "`exito.py`", "Éxito: listado con Playwright y ficha leída de `__NEXT_DATA__`", "Job de captura"],
    ["`src/medallon/`", "`semanal.py`", "Encadena bronce → conformidad → plata → oro", "Job de medallón"],
    ["`src/medallon/`", "`conformidad.py`", "Bronce: pasa los CSV de aterrizaje a tablas Delta sin transformar", "Job de medallón"],
    ["`src/medallon/`", "`plata.py`", "Plata: tipa, deduplica, clasifica y empareja las ofertas", "Job de medallón"],
    ["`src/medallon/`", "`oro.py`", "Oro: modelo estrella e indicadores, reconstruido completo", "Job de medallón"],
    ["`src/medallon/`", "`atipicos.py`", "Reglas de precios atípicos (control de calidad)", "Medallón y validación"],
    ["`src/medallon/`", "`rutas.py`", "Rutas de cada capa en el lago", "Job de medallón"],
    ["`src/nube/`", "`tarea.py`", "Punto de entrada del contenedor de captura", "Job de captura"],
    ["`src/nube/`", "`tarea_medallon.py`", "Punto de entrada del contenedor de medallón", "Job de medallón"],
    ["`src/nube/`", "`lago.py`", "Sube y baja archivos del lago (maestro, código, carga histórica)", "Local"],
    ["`src/nube/`", "`reproceso.py`", "Corrige en el lago una captura ya hecha, a partir de su evidencia", "Local"],
    ["`src/nube/`", "`sql_serverless.py`", "Despliega y verifica las 7 vistas de SQL serverless", "Local"],
    ["`src/validacion/`", "`metricas.py`", "Calcula las 7 métricas de la Etapa 6 y la muestra de exactitud", "Local (Docker)"],
    ["`src/validacion/`", "`reglas.py`", "Pares no unidos y muestra estratificada, sin Spark", "Local"],
    ["`powerbi/herramientas/`", "`generar_pbip.py`", "Generó el proyecto Power BI (modelo TMDL e informe PBIR)", "Local, ya usado"],
    ["`powerbi/herramientas/`", "`validar_pbir.py`", "Valida los JSON del PBIP contra su esquema", "Local"],
    ["`tests/`", "7 archivos `test_*.py`", "99 pruebas rápidas: extracción, catálogo, nube, pipelines, reproceso, SQL y validación", "Local"],
    ["`tests_spark/`", "`test_medallon.py`", "4 pruebas del medallón con Spark y Delta en Docker (unos 7 min)", "Local (Docker)"],
    ["`archivo/iphone/`", "3 archivos", "Primer alcance (iPhone), descartado; se conserva solo como referencia", "No corre"],
  ], [21, 22, 40, 17]),
  espacio(),
  p("Para correr las pruebas rápidas, ejecutar `.venv/Scripts/python -m pytest -q` desde `TFM_MonitoreoPrecios/`. Hoy dan 99 en verde: eran 95 hasta el 17-oct, y el 19-oct se agregaron 4 (vigilancia, disparadores y precios sin stock). La configuración de los sitios (URL, pausas y User-Agent) está en `config/fuentes.yaml`."),

  h1("El código Python dentro de Azure"),
  p("En Azure el código no está como archivos sueltos: viaja empaquetado en 2 imágenes de contenedor y en un zip del lago. Los jobs corren las imágenes; el zip y el notebook son de la opción A, sin uso mientras la cuota de Spark sea 0."),
  tabla(["Dónde en Azure", "Ruta", "Contenido Python", "Quién lo usa"], [
    ["Imagen de captura (Container Registry)", "`acrtfmwebscraping.azurecr.io/tfm-captura:0.4`, carpeta `/app/src/`", "24 archivos (19 módulos y 5 `__init__.py`). Punto de entrada: `python -m src.nube.tarea`", "Job `caj-tfm-captura`, cada día a las 06:00"],
    ["Imagen del medallón (Container Registry)", "`acrtfmwebscraping.azurecr.io/tfm-medallon:0.5`, carpeta `/app/src/`", "19 archivos (15 módulos y 4 `__init__.py`). Punto de entrada: `python -m src.nube.tarea_medallon`", "Job `caj-tfm-medallon`, cada día después de la captura"],
    ["Lago (Storage)", "`datalake-tfm/codigo/tfm_src.zip`", "13 archivos: `src/catalogo/` y `src/medallon/`", "Notebook de la opción A (sin uso)"],
    ["Synapse", "`syn-tfm-webscraping` → *Desarrollar → Cuadernos →* `nb_medallon_semanal`", "4 celdas de PySpark que cargan el zip y llaman a `semanal.ejecutar`", "Pool `sptfm` (sin uso: cuota 0)"],
  ], [20, 32, 28, 20]),
  espacio(),
  p("Qué módulos lleva cada paquete (rutas bajo `/app/src/` en las imágenes y bajo `src/` en el zip):"),
  tabla(["Módulos", "Imagen `tfm-captura:0.4`", "Imagen `tfm-medallon:0.5`", "Zip del lago"], [
    ["`catalogo/`: `atributos_tv.py`, `construir_maestro.py`, `emparejamiento.py`, `gtin.py`", "Sí", "Sí", "Sí"],
    ["`extraccion/`: `bronze.py`, `clasificacion.py`, `cliente.py`, `ejecutar.py`, `informe.py`, `modelos.py`, `robots.py`, `sitemap.py`", "Sí", "No", "No"],
    ["`extraccion/sitios/`: `base.py`, `exito.py`, `sap_commerce.py`, `vtex.py`", "Sí", "No", "No"],
    ["`medallon/`: `atipicos.py`, `conformidad.py`, `oro.py`, `plata.py`, `rutas.py`, `semanal.py`", "No", "Sí", "Sí"],
    ["`nube/`: `lago.py`, `tarea.py`, `tarea_medallon.py`", "Sí", "Sí", "No"],
    ["`nube/`: `reproceso.py`, `sql_serverless.py`", "No", "Sí", "No"],
    ["`extraccion/reproceso.py`, `validacion/`, `powerbi/herramientas/` y las pruebas", "No", "No", "No: solo en el equipo local"],
  ], [52, 16, 16, 16]),
  espacio(),
  p("Cómo verlo:"),
  vineta("**Imágenes:** en el portal, Container Registry `acrtfmwebscraping` → *Repositorios* muestra las versiones, y cada job muestra en *Contenedores* la que usa. El portal no deja ver los archivos internos. Para listarlos: `az acr login -n acrtfmwebscraping` y luego `docker run --rm --entrypoint sh acrtfmwebscraping.azurecr.io/tfm-medallon:0.5 -c \"find /app -name '*.py'\"`."),
  vineta("**Zip:** en el portal, Cuenta de almacenamiento `sttfmwebscraping` → *Contenedores* → `datalake-tfm` → `codigo/`."),
  p("La imagen de captura es del 15-oct, así que no lleva `extraccion/reproceso.py` (posterior), que solo se usa en local. La del medallón y el zip se actualizaron el 19-oct con la regla de atípicos corregida. Cuando cambia el código, `desplegar.ps1` construye una versión nueva de la imagen y la asigna al job.", { spacing: { before: 120, after: 120 } }),

  h1("Otros artefactos (no Python)"),
  p("Además del código, el proyecto define en archivos todo lo que está desplegado en Azure, así que se puede revisar sin entrar al portal."),
  tabla(["Carpeta", "Archivos", "Qué contiene"], [
    ["`synapse/pipelines/`", "`pl_orquestador_diario`, `pl_captura_diaria`, `pl_medallon_diario`, `pl_medallon_synapse`, `pl_notificar_fallo` (JSON)", "Las 5 pipelines: el orquestador corre la captura y, si termina bien, el medallón; las demás inician los jobs, esperan a que terminen y avisan si fallan. `pl_medallon_synapse` es la opción A, sin uso"],
    ["`synapse/triggers/`", "`tr_orquestador_diario` (JSON)", "Un solo disparador: todos los días a las 06:00 de Colombia inicia el orquestador. Desde el 19-oct reemplaza a los dos anteriores"],
    ["`synapse/notebooks/`", "`nb_medallon_semanal.ipynb`", "Notebook del medallón para el pool de Spark (opción A)"],
    ["`synapse/sql/`", "5 scripts, de `00_base_de_datos.sql` a `04_permiso_usuario.sql`", "BD `tfm_oro`, acceso al lago, las 7 vistas, la verificación y los permisos de lectura"],
    ["`infra/`", "`desplegar.ps1`, `notificaciones.json`, `vigilancia.json`, `permisos_equipo.ps1`", "Despliegue de todo por pasos (`-Pasos imagen,job,...`), plantillas de alertas y script de roles del equipo"],
    ["raíz", "`Dockerfile`, `medallon.Dockerfile`, `requirements*.txt`", "Las dos imágenes de contenedor y sus dependencias"],
    ["`powerbi/`", "`TFM_Precios.pbip` y sus carpetas", "Tablero: Resumen de precios, Evolución diaria, Brecha entre cadenas y Calidad de la captura"],
    ["`docs/`", "6 documentos de etapa, 2 de revisión (R1, R2) y 2 anexos de viabilidad", "La documentación del TFM"],
    ["`scripts/`", "`captura_diaria.ps1`", "Captura local de la Etapa 2. **Quedó reemplazada por Azure** y no está programada"],
    ["`data/`", "`bronze`, `capturas`, `maestro`, `validacion`, …", "Copias locales de desarrollo y salidas de la validación. El flujo diario no la usa"],
  ], [18, 40, 42]),
  espacio(),
  p("En el lago, cada capa tiene su lugar:"),
  vineta("`bronce/aterrizaje/{sitio}/`: CSV crudos, páginas originales y resúmenes de cada ejecución;"),
  vineta("`bronce/conformidad/`: lo mismo en Delta, sin transformar;"),
  vineta("`plata/`: ofertas limpias y emparejadas;"),
  vineta("`oro/`: modelo estrella;"),
  vineta("`codigo/`: el zip para el notebook."),

  h1("Guía de revisión paso a paso"),
  p("La revisión sigue el mismo camino que los datos: del sitio web al tablero. Toma unas 2 horas en total, y cada paso dice qué abrir y qué debería verse. Las casillas sirven para marcar el avance."),
  h2("1. Alcance y reglas (20 min)"),
  p("Leer las secciones de alcance, emparejamiento y metas de `docs/01_Etapa1_Requerimientos_y_Arquitectura.md`."),
  casilla("Están los 5 sitios y las 4 cadenas (Alkosto y Ktronix son la misma cadena)."),
  casilla("La regla de emparejamiento (primero el GTIN; si no hay, la referencia del modelo) es la que el equipo quiere."),
  casilla("Las 7 metas de calidad de la sección 10 son las que se van a defender."),
  h2("2. Captura (20 min)"),
  p("Leer `docs/02_Etapa2_Extraccion.md` y mirar `src/extraccion/cliente.py` y una carpeta de `src/extraccion/sitios/`."),
  casilla("La captura es responsable: respeta robots.txt, hace pausas, usa un User-Agent identificable y no evade bloqueos."),
  casilla("En el portal, en *Synapse Studio → Monitor → Ejecuciones de pipeline*, `pl_captura_diaria` aparece en Succeeded hoy a las 06:00."),
  casilla("En el lago, `bronce/aterrizaje/exito/crudo/2026/10/19/` tiene un CSV, y `ejecuciones/` tiene un resumen con `estado: EXITOSA`."),
  h2("3. Orquestación y alertas (20 min)"),
  p("Leer las secciones 9.6 y 9.7 de `docs/03_Etapa3_Orquestacion_y_Medallon.md`."),
  casilla("El disparador `tr_orquestador_diario` está en Started (*Synapse Studio → Administrar → Desencadenadores*)."),
  casilla("El correo y la tarjeta de Teams de prueba del 19-oct (18:28) llegaron."),
  casilla("Desde el 20-oct, en Monitor, `pl_orquestador_diario` aparece cada día en Succeeded, con la captura primero y el medallón después. A las 09:30 no debería llegar ningún aviso: eso confirma que la vigilancia funciona sin falsas alarmas."),
  h2("4. Medallón (15 min)"),
  p("Mirar `src/medallon/plata.py` y `src/medallon/oro.py`."),
  casilla("Se entiende qué hace cada capa: bronce guarda, plata limpia y empareja, oro modela."),
  casilla("El job `caj-tfm-medallon` tiene una ejecución en Succeeded cada día desde el 20-oct (*Container Apps → caj-tfm-medallon → Historial de ejecución*)."),
  h2("5. Modelo estrella (15 min)"),
  p("Leer `docs/04_Etapa4_Modelo_Estrella.md`."),
  casilla("En la BD `tfm_oro` de SQL serverless se puede consultar `SELECT TOP 10 * FROM oro.fact_precio_diario`."),
  casilla("Las 7 vistas tienen sentido: 3 dimensiones, 2 hechos y 2 indicadores."),
  h2("6. Tablero (20 min)"),
  p("Abrir `powerbi/TFM_Precios.pbip` en Power BI Desktop, actualizar y guardar con Ctrl+S."),
  casilla("Las 4 páginas cargan y muestran el 13, el 14 y el 19-oct."),
  casilla("La tarjeta *Precios atípicos* de «Calidad de la captura» muestra los precios atípicos. Desde el medallón del 20-oct (imagen 0.5) deben quedar solo los atípicos de los Caixun; los 5 de Éxito del 19-oct eran falsas alarmas (televisores sin stock)."),
  casilla("Anotar los ajustes visuales que quiere el equipo."),
  h2("7. Validación (20 min y el contraste)"),
  p("Leer `data/validacion/2026-10-19/informe_validacion.md`."),
  casilla("Las 7 métricas cumplen."),
  casilla("Contrastar `muestra_exactitud_20261019.csv`: abrir cada URL y anotar el precio que muestra el sitio y si coincide (S/N)."),
  casilla("Contar los televisores de la categoría de cada sitio y estimar las horas de revisión manual frente a las de supervisión."),

  h1("Tablero en línea para la defensa (11-mar-2027)"),
  p("La prueba gratuita de Fabric no alcanza por sí sola: dura 60 días y de hoy a la defensa hay 143. Por eso, los datos se quedan en Azure y el servicio Power BI se usa solo para publicar el tablero."),
  tabla(["Condición de la prueba de Fabric", "Efecto para el proyecto"], [
    ["Dura 60 días", "Una sola prueba iniciada hoy vence en diciembre"],
    ["No se garantiza una segunda prueba", "No se puede contar con encadenar varias"],
    ["El administrador de UNIR puede deshabilitarla y hay un límite por tenant", "Hay que comprobarlo con las cuentas de UNIR"],
    ["Al vencer, lo propio de Fabric (lakehouse, notebooks, pipelines) se inactiva y se borra a los 7 días; lo de Power BI se conserva", "Mover los datos a Fabric pondría en riesgo la defensa"],
  ], [55, 45]),
  espacio(),
  casilla("Esta semana, cada integrante entra a app.fabric.microsoft.com con su cuenta de UNIR y mira en su perfil qué licencia tiene (Free, Pro o PPU), **sin presionar «Iniciar evaluación»**."),
  casilla("Si alguien tiene Pro: publicar el tablero en el servicio con actualización programada a las 07:30, después del orquestador."),
  casilla("Si nadie tiene Pro: iniciar la prueba hacia el 15-ene-2027, para que dure hasta el 16-mar."),
  casilla("Plan B para la defensa: el PBIP en Power BI Desktop, actualizado con los datos de Azure."),
  p("Costo de Azure: USD 1,13 reales del 1 al 19-oct. Con el medallón diario se estiman USD 8 a 10 al mes, unos USD 50 hasta la defensa, dentro del crédito de USD 100. Fuente: Fabric trial capacity – Microsoft Learn (learn.microsoft.com/en-us/fabric/fundamentals/fabric-trial).", { spacing: { before: 120, after: 120 } }),

  h1("Pendientes abiertos del equipo"),
  p("Ninguno bloquea el funcionamiento diario. Los dos primeros son los que más avanzan la Etapa 6."),
  casilla("Contrastar la muestra de exactitud del 19-oct (60 ofertas)."),
  casilla("Contar la categoría de cada sitio y estimar las horas de revisión manual."),
  casilla("Revisar visualmente el PBIP y decidir si se publica en el servicio Power BI."),
  casilla("Revisar el Samsung 75\" `VGSCFH75SGMZX`, que tiene 2 GTIN: decidir si se marca CORREGIR o RECHAZAR en `decisiones.csv`."),
  casilla("Crear las alertas de presupuesto de 50, 75 y 90 USD en *Cost Management*."),
  casilla("Decidir qué hacer con `ADF-TFM-WEBSCRAPING`, que no se usa."),
  casilla("Restringir el firewall de Synapse, que hoy permite todas las IP."),
  casilla("Corregir el texto del TFM según `docs/R1_Revision_primera_entrega.md` (decisiones D1 a D3)."),
  casilla("Opcional: pedir la cuota de Spark de Synapse (opción A). El medallón ya funciona sin ella."),
];

const doc = new Document({
  creator: "TFM Monitoreo de precios",
  title: "Guía de revisión del proyecto TFM",
  styles: {
    default: { document: { run: { font: FUENTE, size: 21 } } },
    paragraphStyles: [
      { id: "Title", name: "Title", basedOn: "Normal", run: { size: 36, bold: true, color: "1F3864" }, paragraph: { spacing: { after: 120 } } },
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", run: { size: 28, bold: true, color: "1F3864" }, paragraph: { spacing: { before: 320, after: 120 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", run: { size: 23, bold: true, color: "2E5597" }, paragraph: { spacing: { before: 200, after: 80 }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [{ reference: "vinetas", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] }] },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Guía de revisión del proyecto TFM · página ", size: 16, color: "808080" }), new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "808080" })] })] }) },
    children: contenido,
  }],
});

Packer.toBuffer(doc).then((b) => { fs.writeFileSync(salida, b); console.log("escrito", salida, b.length, "bytes"); });

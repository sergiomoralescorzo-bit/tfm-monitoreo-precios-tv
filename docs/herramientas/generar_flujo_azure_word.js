// Genera el Word del flujo diario en Azure.
// Refleja el estado al 20-oct-2026 (imágenes tfm-captura:0.4 y tfm-medallon:0.5, captura con 1 vCPU y 2 GiB). Las versiones vigentes
// son tfm-captura:0.7 y tfm-medallon:0.8 (infra/desplegar.ps1). El Word generado se conserva como registro de esa fecha.
// Uso: node generar_flujo_azure_word.js <salida.docx> <flujo_azure.png>
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
// Numeración escrita a mano: con listas numeradas de Word, las listas de distintos pasos se mezclaban.
const contadores = {};
const numero = (t, ref) => {
  contadores[ref] = (contadores[ref] || 0) + 1;
  return new Paragraph({ children: [new TextRun(`${contadores[ref]}.	`), ...runs(t)], indent: { left: 720, hanging: 360 }, tabStops: [{ type: "left", position: 720 }], spacing: { after: 60 } });
};
const donde = (t) => new Paragraph({ children: runs(t, { color: "595959", size: 19 }), spacing: { after: 100 } });
const nota = (t) => new Paragraph({ children: runs(t, { italics: true, color: "595959" }), spacing: { after: 120 }, indent: { left: 360 } });

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
  new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun("Flujo diario en Azure")] }),
  p("Estado al 20-oct-2026", { children: [new TextRun({ text: "TFM Monitoreo de precios de televisores · estado al 20-oct-2026", italics: true, color: "595959" })] }),
  p("Qué arranca cada día, en qué orden, qué contenedor corre cada código Python y dónde queda cada resultado. Todo está en el grupo `RG-TFM-WEBSCRAPING` (West US). Las rutas de archivos son relativas a `TFM_MonitoreoPrecios/`."),

  h1("Diagrama"),
  new Paragraph({ alignment: AlignmentType.CENTER, children: [new ImageRun({ type: "png", data: fs.readFileSync(imagen), transformation: { width: 620, height: 555 }, altText: { title: "Flujo diario en Azure", description: "A las 06:00 Synapse inicia el orquestador, que corre la captura en caj-tfm-captura y, si termina bien, el medallón en caj-tfm-medallon. La captura escribe bronce/aterrizaje y el medallón escribe conformidad, plata y oro, que leen SQL serverless y Power BI. Los fallos avisan por correo y Teams, y a las 09:30 una vigilancia revisa que todo haya corrido.", name: "flujo" } })] }),
  p("Los números del diagrama corresponden a los pasos de este documento. Colores: azul, Synapse (decide el orden y espera); verde, Container Apps (ejecuta el Python); ocre, el lago (guarda cada capa); rojo, los avisos. Las líneas punteadas son lecturas o dependencias indirectas.", { children: runs("Los números del diagrama corresponden a los pasos de este documento. Colores: azul, Synapse (decide el orden y espera); verde, Container Apps (ejecuta el Python); ocre, el lago (guarda cada capa); rojo, los avisos. Las líneas punteadas son lecturas o dependencias indirectas.", { size: 19, color: "595959" }) }),

  h1("La idea general"),
  p("Synapse no ejecuta el Python. Solo **enciende** los dos contenedores por la API de Azure y **espera** a que terminen. Cada contenedor baja lo que necesita del lago, procesa en su propio disco y sube el resultado."),
  p("La captura va primero y el medallón solo corre si la captura terminó bien, porque el medallón procesa lo que la captura acaba de dejar en bronce."),

  h1("Paso a paso"),

  h2("1. El disparador arranca todo a las 06:00"),
  donde("Azure: Synapse Studio › Administrar › Desencadenadores · Archivo: `synapse/triggers/tr_orquestador_diario.json`"),
  p("`tr_orquestador_diario` es un disparador por horario (`ScheduleTrigger`) que se activa todos los días a las 06:00, hora de Colombia (`SA Pacific Standard Time`). Solo lanza una pipeline: `pl_orquestador_diario`."),
  nota("Su startTime es el 17-oct a las 00:00, antes de la primera hora de ejecución. Cuando el startTime coincidía con esa hora, el 18-oct no corrió nada."),

  h2("2. El orquestador define el orden"),
  donde("Azure: Synapse Studio › Integrar › Canalizaciones · Archivo: `synapse/pipelines/pl_orquestador_diario.json`"),
  p("No procesa datos. Tiene dos actividades `ExecutePipeline`, ambas con `waitOnCompletion: true`:"),
  numero("**Captura**: llama a `pl_captura_diaria` y espera a que termine.", "orden2"),
  numero("**Medallon**: llama a `pl_medallon_diario`, pero **solo si la captura terminó en Succeeded**. Si la captura falla, el medallón no corre y el orquestador queda en Failed.", "orden2"),

  h2("3. pl_captura_diaria enciende el contenedor de captura"),
  donde("Azure: Synapse Studio › Integrar · Archivo: `synapse/pipelines/pl_captura_diaria.json`"),
  tabla(["Actividad", "Qué hace"], [
    ["`Iniciar captura`", "Hace `POST …/jobs/caj-tfm-captura/start` con la identidad administrada de Synapse, que tiene el rol Contributor sobre el job."],
    ["`Guardar ejecucion`", "Guarda el nombre de la ejecución que devuelve Azure."],
    ["`Esperar fin`", "Cada 120 s consulta `GET …/executions/{nombre}` hasta que el estado deje de ser Running. Tope de 2 h 30 min."],
    ["`Verificar resultado`", "Si el estado final no es Succeeded, termina con el error `CAPTURA_FALLIDA`."],
    ["`Avisar fallo - …`", "Si cualquier actividad falla, llama a `pl_notificar_fallo` (paso 8) y deja la pipeline en Failed."],
  ], [28, 72]),
  espacio(),

  h2("4. Dentro de caj-tfm-captura: se capturan los 5 sitios"),
  donde("Azure: Container Apps Job `caj-tfm-captura` en el entorno `cae-tfm-webscraping` · Imagen: `tfm-captura:0.4` (`Dockerfile`) · 1 vCPU, 2 GiB, tope de 2 h"),
  p("La imagen trae Python 3.12 y Chromium de Playwright, y copia `config/` y `src/`. Al arrancar ejecuta `python -m src.nube.tarea` (`src/nube/tarea.py`), que sigue este orden:"),
  numero("**Elige el modo**: el domingo hace la captura *completa* (vuelve a descubrir todas las fichas); los demás días hace el *seguimiento* de las fichas ya conocidas.", "orden4"),
  numero("**Lee la configuración** de `config/fuentes.yaml`: sitios, User-Agent, pausa de 1,5 s y reintentos.", "orden4"),
  numero("**Baja el estado** del lago con `src/nube/lago.py`: las fichas descubiertas de `estado/ultimo_estado.json`.", "orden4"),
  numero("**Extrae los 5 sitios en paralelo** con `src/extraccion/ejecutar.py` (detalle en la tabla).", "orden4"),
  numero("**Sube la corrida al lago** con `lago.subir_corrida()`, usando la identidad `id-tfm-captura`.", "orden4"),
  numero("**Termina con un código**: 0 si ningún sitio quedó FALLIDA y 1 en caso contrario. Azure lo traduce a Succeeded o Failed, y eso es lo que lee el paso 3.", "orden4"),
  espacio(),
  tabla(["Python", "Qué procesa"], [
    ["`src/extraccion/cliente.py`", "Cliente HTTP responsable: respeta robots.txt, hace una petición a la vez con pausa y se detiene ante 403/429 (BLOQUEADO)."],
    ["`src/extraccion/robots.py`", "Interpreta robots.txt con comodines."],
    ["`src/extraccion/sitemap.py`", "Lee los sitemaps XML para descubrir fichas."],
    ["`src/extraccion/sitios/sap_commerce.py`", "Alkosto y Ktronix: ficha HTML con microdatos."],
    ["`src/extraccion/sitios/vtex.py`", "Jumbo y Olímpica: API pública de catálogo."],
    ["`src/extraccion/sitios/exito.py`", "Éxito: listado con Playwright y ficha leída de `__NEXT_DATA__`."],
    ["`src/extraccion/clasificacion.py`", "Marca si cada registro está en alcance o el motivo de exclusión."],
    ["`src/extraccion/bronze.py`", "Guarda cada respuesta original comprimida (.gz) como evidencia."],
    ["`src/extraccion/modelos.py`", "Esquema del registro de captura y del registro de ejecución."],
  ], [38, 62]),
  espacio(),
  p("Qué deja en el lago (contenedor `datalake-tfm`):"),
  tabla(["Carpeta temporal del contenedor", "Destino en el lago"], [
    ["`capturas/{sitio}/fecha=F/{id}.csv`", "`bronce/aterrizaje/{sitio}/crudo/AAAA/MM/DD/productos_{sitio}_{ts}.csv`"],
    ["`bronze/{sitio}/…/*.gz`", "`bronce/aterrizaje/{sitio}/capturas/AAAA/MM/DD/{id}/` (evidencia)"],
    ["Fila de `ejecuciones.csv`", "`bronce/aterrizaje/{sitio}/ejecuciones/ejecucion_{ts}.json`"],
    ["`estado/objetivos_{sitio}.csv`", "`bronce/aterrizaje/{sitio}/estado/ultimo_estado.json`"],
  ], [40, 60]),
  espacio(),

  h2("5. pl_medallon_diario enciende el contenedor del medallón"),
  donde("Azure: Synapse Studio › Integrar · Archivo: `synapse/pipelines/pl_medallon_diario.json`"),
  p("Tiene la misma estructura que el paso 3: `POST …/jobs/caj-tfm-medallon/start` y una consulta del estado cada 60 s, con un tope de 1 h 15 min. Si falla, termina con `MEDALLON_FALLIDO` y avisa. Conserva el nombre «semanal» por historia, pero desde el 19-oct corre a diario, encadenada a la captura."),

  h2("6. Dentro de caj-tfm-medallon: bronce → plata → oro"),
  donde("Azure: Container Apps Job `caj-tfm-medallon` · Imagen: `tfm-medallon:0.5` (`medallon.Dockerfile`) · 2 vCPU, 4 GiB, tope de 1 h"),
  p("La imagen trae Python 3.10, Java 17 y Spark 3.4 con Delta 2.4 en modo local, igual que el runtime de Synapse. Se usa porque la cuota de Spark de Synapse es 0 vCores (opción B). Al arrancar ejecuta `python -m src.nube.tarea_medallon` (`src/nube/tarea_medallon.py`):"),
  numero("**Crea una sesión de Spark local** (`local[*]`, 3 GB).", "orden6"),
  numero("**Baja del lago solo lo que Spark lee**: `crudo/` y `ejecuciones/` de cada sitio, `maestro/` y `revision/`, las tablas Delta de `bronce/conformidad/` y solo el `_delta_log` de `plata/` y `oro/`. No baja `capturas/` (la evidencia), porque pesa mucho.", "orden6"),
  numero("**Procesa las tres capas** con `src/medallon/semanal.py` (tabla).", "orden6"),
  numero("**Sube los archivos nuevos o modificados**, primero los datos y al final `_delta_log`, para que nadie lea una versión incompleta.", "orden6"),
  numero("**Deja un resumen** con tiempos y conteos en `plata/control/medallon/medallon_{fecha}.json`.", "orden6"),
  espacio(),
  tabla(["Orden", "Python", "Escribe (Delta)", "Qué hace"], [
    ["a", "`src/medallon/conformidad.py`", "`bronce/conformidad/{sitio}/productos`, `…/ejecuciones`, `…/maestro/televisores`", "Pasa los CSV a Delta sin transformar (todo como texto) y agrega el origen, la fecha de carga y la partición. Es incremental: no recarga archivos ya cargados."],
    ["b", "`src/medallon/plata.py`, con `atipicos.py` y `src/catalogo/` (`emparejamiento.py`, `atributos_tv.py`, `gtin.py`)", "`plata/precios/ofertas`, `plata/precios/revision_emparejamiento`, `plata/catalogo/productos`, `plata/control/ejecuciones`", "Tipa, deduplica y clasifica las ofertas. Las empareja por EAN y, si no hay EAN, por referencia. Marca los precios atípicos. Se reconstruye completa."],
    ["c", "`src/medallon/oro.py`", "`oro/dimensiones/`, `oro/hechos/`, `oro/kpis/`", "Modelo estrella (`dim_producto`, `dim_tienda`, `dim_calendario`, `fact_precio_diario`, `fact_ejecucion`) e indicadores (`kpi_brecha_precio`, `kpi_calidad_captura`). Se reconstruye completo."],
  ], [8, 28, 30, 34]),
  espacio(),
  p("Las rutas de todas las capas están en `src/medallon/rutas.py`."),

  h2("7. SQL serverless y Power BI leen oro"),
  donde("Azure: Synapse › SQL serverless › BD `tfm_oro` · Archivos: `synapse/sql/00…04_*.sql`, `powerbi/TFM_Precios.pbip`"),
  p("Aquí no se ejecuta ningún proceso. Las 7 vistas (`oro.dim_producto`, `oro.fact_precio_diario`, etc.) leen las tablas Delta de `oro/` con `OPENROWSET(… FORMAT='DELTA')`. Como no copian datos, cuando el medallón termina ya muestran los datos del día. Power BI se conecta a esas vistas."),

  h2("8. Avisos de fallo y vigilancia de las 09:30"),
  donde("Archivos: `synapse/pipelines/pl_notificar_fallo.json`, `infra/notificaciones.json`, `infra/vigilancia.json`"),
  vineta("**Si algo falla**, las ramas `Avisar fallo - …` llaman a `pl_notificar_fallo`. Esa pipeline envía el error a la Logic App `la-tfm-notificaciones`, que manda un correo a los 3 destinatarios y una tarjeta a Teams. Como respaldo, la alerta `ag-tfm-fallos` avisa si alguna pipeline termina en Failed."),
  vineta("**A las 09:30**, la Logic App `la-tfm-vigilancia` consulta en Synapse si hubo una ejecución exitosa de `pl_captura_diaria` y de `pl_medallon_diario` entre las 04:30 y las 09:30. Si falta alguna, avisa por la misma vía. Así se detecta también el día en que no se ejecutó nada, como el 18-oct."),

  h1("Recursos de Azure que intervienen"),
  tabla(["Recurso", "Nombre", "Papel en el flujo"], [
    ["Área de trabajo de Synapse", "`syn-tfm-webscraping`", "Disparador, pipelines y SQL serverless"],
    ["Container Registry (Basic)", "`acrtfmwebscraping`", "Guarda las imágenes `tfm-captura:0.4` y `tfm-medallon:0.5`"],
    ["Entorno de Container Apps", "`cae-tfm-webscraping`", "Donde corren los dos jobs"],
    ["Container Apps Job", "`caj-tfm-captura`", "Captura (paso 4)"],
    ["Container Apps Job", "`caj-tfm-medallon`", "Medallón (paso 6)"],
    ["Identidad administrada", "`id-tfm-captura`", "Los jobs bajan su imagen y leen y escriben el lago sin claves"],
    ["Data Lake Gen2", "`sttfmwebscraping` / `datalake-tfm`", "Guarda `bronce/`, `plata/`, `oro/` y `codigo/`"],
    ["Logic App", "`la-tfm-notificaciones`", "Correo y Teams cuando algo falla"],
    ["Logic App", "`la-tfm-vigilancia`", "Revisión diaria de las 09:30"],
    ["Alerta de Azure Monitor", "`ag-tfm-fallos`", "Respaldo de los avisos"],
  ], [28, 32, 40]),
  espacio(),

  h1("Lo que existe pero no corre cada día"),
  vineta("`pl_medallon_synapse` y el notebook `nb_medallon_semanal.ipynb`: son la opción A, con el pool de Spark `sptfm` de Synapse. No corren porque la cuota de Spark es 0. Cargan el código desde `codigo/tfm_src.zip` en el lago."),
  vineta("`ADF-TFM-WEBSCRAPING`: el Data Factory existe en el grupo, pero no se usa."),
  vineta("`infra/desplegar.ps1`: no forma parte de la ejecución diaria. Crea o actualiza todo lo anterior y reemplaza en las pipelines los marcadores como `__JOB__` o `__SUSCRIPCION__`."),

  h1("En una línea"),
  p("**06:00** `tr_orquestador_diario` → `pl_orquestador_diario` → `pl_captura_diaria` → `caj-tfm-captura` (`src.nube.tarea`) → `bronce/aterrizaje` → si terminó bien: `pl_medallon_diario` → `caj-tfm-medallon` (`src.nube.tarea_medallon` → conformidad → plata → oro) → SQL `tfm_oro` → Power BI. Si algo falla: correo y Teams. **09:30**: vigilancia."),
];

const doc = new Document({
  creator: "TFM Monitoreo de precios",
  title: "Flujo diario en Azure",
  styles: {
    default: { document: { run: { font: FUENTE, size: 21 } } },
    paragraphStyles: [
      { id: "Title", name: "Title", basedOn: "Normal", run: { size: 36, bold: true, color: "1F3864" }, paragraph: { spacing: { after: 120 } } },
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", run: { size: 28, bold: true, color: "1F3864" }, paragraph: { spacing: { before: 320, after: 120 }, outlineLevel: 0, keepNext: true } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", run: { size: 23, bold: true, color: "2E5597" }, paragraph: { spacing: { before: 240, after: 80 }, outlineLevel: 1, keepNext: true } },
    ],
  },
  numbering: { config: [
    { reference: "vinetas", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
  ] },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Flujo diario en Azure · página ", size: 16, color: "808080" }), new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "808080" })] })] }) },
    children: contenido,
  }],
});

Packer.toBuffer(doc).then((b) => { fs.writeFileSync(salida, b); console.log("escrito", salida, b.length, "bytes"); });

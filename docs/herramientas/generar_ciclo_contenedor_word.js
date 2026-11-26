// Genera el Word del ciclo de vida del contenedor de captura: cómo llega ejecutar.py a Azure y cómo se ejecuta cada día.
// Uso: node generar_ciclo_contenedor_word.js <salida.docx> <ciclo_despliegue.png> <ciclo_ejecucion.png>
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType,
  ShadingType, BorderStyle, ImageRun, TableLayoutType, AlignmentType, LevelFormat, Footer, PageNumber,
} = require("docx");

const [, , salida, imgDespliegue, imgEjecucion] = process.argv;
const ANCHO = 9360; // carta con márgenes de 1"
const FUENTE = "Calibri";

function runs(texto, base = {}) {
  return texto.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/).filter(Boolean).flatMap((t) => {
    if (t.startsWith("`")) return new TextRun({ ...base, text: t.slice(1, -1), font: "Consolas", size: 18 });
    if (t.startsWith("**")) return runs(t.slice(2, -2), { ...base, bold: true }); // admite `código` dentro de negrita
    if (t.startsWith("*")) return new TextRun({ ...base, text: t.slice(1, -1), italics: true });
    return new TextRun({ ...base, text: t });
  });
}
const p = (t, opts = {}) => new Paragraph({ children: runs(t), spacing: { after: 120 }, ...opts });
const h1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)] });
const h2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] });
const vineta = (t) => new Paragraph({ numbering: { reference: "vinetas", level: 0 }, children: runs(t), spacing: { after: 60 } });
const donde = (t) => new Paragraph({ children: runs(t, { color: "595959", size: 19 }), spacing: { after: 100 } });
// Numeración escrita a mano: con listas numeradas de Word, las listas de distintos pasos se mezclaban.
const contadores = {};
const numero = (t, ref) => {
  contadores[ref] = (contadores[ref] || 0) + 1;
  return new Paragraph({ children: [new TextRun(`${contadores[ref]}.\t`), ...runs(t)], indent: { left: 720, hanging: 360 }, tabStops: [{ type: "left", position: 720 }], spacing: { after: 60 } });
};
// Bloque de código: una línea por párrafo, fondo gris.
const codigo = (lineas) => lineas.map((l, i) => new Paragraph({
  children: [new TextRun({ text: l || " ", font: "Consolas", size: 17 })],
  shading: { type: ShadingType.CLEAR, color: "auto", fill: "F2F2F2" },
  spacing: { after: i === lineas.length - 1 ? 160 : 0 }, indent: { left: 200, right: 200 },
}));
const figura = (ruta, ancho, alto, titulo, descripcion) => new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { after: 80 },
  children: [new ImageRun({ type: "png", data: fs.readFileSync(ruta), transformation: { width: ancho, height: alto }, altText: { title: titulo, description: descripcion, name: titulo } })],
});
const pie = (t) => new Paragraph({ alignment: AlignmentType.CENTER, children: runs(t, { size: 18, italics: true, color: "595959" }), spacing: { after: 200 } });

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
  new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun("Ciclo de vida del contenedor de captura")] }),
  p("", { children: [new TextRun({ text: "TFM Monitoreo de precios de televisores · estado al 20-oct-2026", italics: true, color: "595959" })] }),
  p("Este documento explica dónde está guardado `ejecutar.py` en Azure, cómo llega allí y cómo se ejecuta cada día dentro del contenedor Docker de la captura. Complementa el documento *Flujo diario en Azure* (`docs/Flujo_ejecucion_Azure.docx`), que muestra el flujo completo. Las rutas de archivos son relativas a `TFM_MonitoreoPrecios/`."),
  p("Hay dos momentos distintos:"),
  vineta("**A. Despliegue**: cómo llega el código a Azure. Ocurre una sola vez por cada versión que se publica."),
  vineta("**B. Ejecución diaria**: cómo se ejecuta cada día a las 06:00, de forma automática."),
  p("En pocas palabras: `ejecutar.py` no aparece como archivo suelto en el portal de Azure. Viaja **dentro de la imagen Docker** `tfm-captura:0.4`, guardada en el registro `acrtfmwebscraping`, en la ruta `/app/src/extraccion/ejecutar.py`. Cada día, el Container Apps Job `caj-tfm-captura` crea un contenedor temporal a partir de esa imagen, y el código corre ahí dentro.", { spacing: { before: 120, after: 120 } }),

  // ------------------------------------------------------------------ A
  h1("A. Cómo llega ejecutar.py a Azure (despliegue)"),
  figura(imgDespliegue, 620, 260, "Despliegue de la imagen de captura", "En el PC, Docker construye la imagen tfm-captura:0.4 con el Dockerfile y el código; la imagen se sube al registro acrtfmwebscraping; el job caj-tfm-captura apunta a esa imagen y la identidad id-tfm-captura le da permiso para descargarla y escribir en el lago."),
  pie("Figura 1. Despliegue: del PC al registro de imágenes, y del registro al job."),

  h2("A1. La receta: el Dockerfile"),
  donde("Archivos: `Dockerfile`, `requirements-contenedor.txt`, `.dockerignore`"),
  p("El `Dockerfile` indica cómo se arma la «caja» (la imagen) que se envía a Azure:"),
  tabla(["Línea del Dockerfile", "Qué significa"], [
    ["`FROM mcr.microsoft.com/playwright/python:v1.63.0-noble`", "Parte de una imagen de Microsoft que ya trae Linux (Ubuntu), Python y Chromium."],
    ["`WORKDIR /app`", "Dentro de la imagen, todo queda en la carpeta `/app`."],
    ["`RUN pip install … requirements-contenedor.txt`", "Instala las librerías: httpx, BeautifulSoup, pydantic, Playwright, azure-identity y azure-storage-file-datalake."],
    ["`COPY config/ config/`", "Copia `fuentes.yaml` a `/app/config/fuentes.yaml`."],
    ["`COPY src/ src/`", "Copia el código. **Aquí entra `/app/src/extraccion/ejecutar.py`.**"],
    ["`USER pwuser`", "Corre sin permisos de administrador."],
    ["`ENTRYPOINT [\"python\", \"-m\", \"src.nube.tarea\"]`", "**Lo primero que se ejecuta al encender el contenedor.**"],
  ], [45, 55]),
  espacio(),
  p("El archivo `.dockerignore` deja fuera `data/`, `docs/`, `tests/`, `.venv/` y `src/medallon/`. Por eso esta imagen solo lleva el código de captura."),

  h2("A2. Construir y publicar la imagen"),
  donde("Comando: `infra\\desplegar.ps1 -Pasos imagen` (se ejecuta en el PC, con Docker Desktop abierto)"),
  p("El script hace tres cosas:"),
  numero("`az acr login -n acrtfmwebscraping`: inicia sesión en el registro de imágenes.", "a2"),
  numero("`docker build -t acrtfmwebscraping.azurecr.io/tfm-captura:0.4 .`: Docker Desktop arma la imagen en el PC siguiendo el Dockerfile.", "a2"),
  numero("`docker push …/tfm-captura:0.4`: sube la imagen a Azure.", "a2"),
  p("**Dónde queda guardada:** en el portal, *Registro de contenedor* `acrtfmwebscraping` → *Repositorios* → `tfm-captura` → `0.4`. Una imagen se parece a un archivo comprimido de solo lectura: contiene todo lo necesario (sistema operativo, Python, librerías y código), pero el portal no permite abrirla para ver archivos sueltos.", { spacing: { before: 120, after: 120 } }),

  h2("A3. El job queda apuntando a la imagen"),
  donde("Comando: `infra\\desplegar.ps1 -Pasos job` · Azure: *Container Apps Job* `caj-tfm-captura` → *Contenedores*"),
  p("El job `caj-tfm-captura` se creó con estos parámetros:"),
  tabla(["Parámetro", "Valor", "Significado"], [
    ["`--image`", "`acrtfmwebscraping.azurecr.io/tfm-captura:0.4`", "Qué imagen usar."],
    ["`--trigger-type`", "`Manual`", "No tiene horario propio: lo enciende Synapse."],
    ["`--cpu` / `--memory`", "1 vCPU / 2 GiB", "Tamaño de la máquina."],
    ["`--replica-timeout`", "7200 s (2 h)", "Si tarda más, Azure la detiene."],
    ["`--replica-retry-limit`", "0", "Si falla, no la reintenta."],
    ["`--mi-user-assigned`, `--registry-identity`", "`id-tfm-captura`", "La identidad con la que descarga la imagen (rol **AcrPull**) y escribe en el lago (rol **Storage Blob Data Contributor**), sin contraseñas."],
    ["`--env-vars`", "`TFM_ADLS_CUENTA=sttfmwebscraping`, `TFM_ADLS_CONTENEDOR=datalake-tfm`, `AZURE_CLIENT_ID=…`", "Le indican al Python a qué lago escribir y con qué identidad."],
  ], [27, 33, 40]),
  espacio(),
  p("El job **no guarda una copia** del código. Solo guarda la «ficha» de qué imagen usar y con qué recursos."),

  // ------------------------------------------------------------------ B
  h1("B. Cómo se ejecuta cada día"),
  figura(imgEjecucion, 620, 369, "Ejecución diaria de la captura", "Synapse pide iniciar el job; Azure crea una réplica con la imagen; el contenedor ejecuta src.nube.tarea, que baja el estado del lago, llama a ejecutar.py, sube los resultados a bronce/aterrizaje y termina; Azure destruye la réplica y Synapse ve el estado final."),
  pie("Figura 2. Ejecución diaria: de la orden de Synapse a la destrucción del contenedor."),

  h2("B1. Synapse enciende el job"),
  donde("Azure: Synapse Studio › Integrar · Archivo: `synapse/pipelines/pl_captura_diaria.json`"),
  p("A las 06:00, el orquestador llama a `pl_captura_diaria`. Su actividad `Iniciar captura` hace una llamada HTTP a la API de Azure:"),
  ...codigo(["POST https://management.azure.com/…/jobs/caj-tfm-captura/start"]),
  p("Synapse puede hacerlo porque su identidad administrada tiene el rol *Contributor* sobre el job. Es el equivalente a presionar el botón **«Ejecutar ahora»** del portal."),

  h2("B2. Azure crea el contenedor"),
  p("Container Apps toma una máquina del entorno `cae-tfm-webscraping` y, con la identidad `id-tfm-captura`, **descarga la imagen** desde el ACR. Luego la «enciende». Ese contenedor encendido se llama **réplica**, y es temporal."),

  h2("B3. Se ejecuta el ENTRYPOINT: tarea.py"),
  donde("Archivo: `src/nube/tarea.py` (dentro del contenedor: `/app/src/nube/tarea.py`)"),
  p("Al encenderse, el contenedor ejecuta `python -m src.nube.tarea`. Ese archivo es el «jefe» de la corrida:"),
  ...codigo([
    "modo = modo_del_dia()                     # domingo → \"completo\", otro día → \"seguimiento\"",
    "raiz = tempfile.mkdtemp(prefix=\"tfm_\")    # carpeta temporal, ej. /tmp/tfm_ab12",
    "destino = lago.destino_desde_entorno()    # conexión al lago (lee TFM_ADLS_CUENTA, etc.)",
    "lago.bajar_estado(destino, raiz, sitios)  # baja las fichas conocidas",
    "ejecuciones = asyncio.run(ejecutar(...))  # ◀── AQUÍ SE LLAMA ejecutar.py",
    "lago.subir_corrida(destino, raiz, id)     # sube los resultados",
    "return 0 si ningún sitio quedó FALLIDA, si no 1",
  ]),
  p("**Así se llama `ejecutar.py`:** `tarea.py` lo importa como módulo, con `from src.extraccion.ejecutar import ejecutar`, y llama a su función `ejecutar()`. Nadie ejecuta `ejecutar.py` directamente en Azure."),

  h2("B4. Qué hace ejecutar.py por dentro"),
  donde("Archivo: `src/extraccion/ejecutar.py` (dentro del contenedor: `/app/src/extraccion/ejecutar.py`)"),
  p("**Función `ejecutar()`:**"),
  numero("Crea un id de corrida, por ejemplo `20261020T060312_a1b2c3` (hora de Colombia más 6 caracteres al azar).", "b4"),
  numero("Lanza **`ejecutar_sitio()` para los 5 sitios a la vez** con `asyncio.gather`: Alkosto, Ktronix, Jumbo, Olímpica y Éxito corren en paralelo.", "b4"),
  p("**Función `ejecutar_sitio()`, una por sitio:**", { spacing: { before: 120, after: 120 } }),
  tabla(["#", "Qué hace", "Con qué archivo"], [
    ["1", "Abre un cliente HTTP con el User-Agent del TFM, una pausa de 1,5 s, 3 reintentos y un tope de 3 bloqueos.", "`cliente.py`"],
    ["2", "Lee el robots.txt del sitio.", "`robots.py`"],
    ["3", "**Seguimiento:** usa las fichas ya conocidas (bajadas del lago en B3). **Completo** (o si no hay fichas): **descubre** las fichas en el sitemap, o en el listado con Playwright en el caso de Éxito.", "`sitemap.py`, `sitios/exito.py`"],
    ["4", "Para cada ficha: la descarga, **guarda la respuesta original** (.gz) y **extrae** precio, stock, EAN y vendedor.", "`bronze.py` + `sitios/sap_commerce.py`, `vtex.py` o `exito.py`"],
    ["5", "Si el sitio responde 403/429 repetidamente, **se detiene** y registra BLOQUEADO, sin intentar esquivarlo.", "`cliente.py`"],
    ["6", "Marca cada registro como en alcance o fuera de él (por ejemplo, accesorios).", "`clasificacion.py`"],
    ["7", "Calcula el estado del sitio: **EXITOSA**, **PARCIAL** (hubo errores) o **FALLIDA** (0 precios).", "—"],
    ["8", "Escribe en la carpeta temporal: `capturas/{sitio}/fecha=…/{id}.csv`, `bronze/…/*.gz`, `ejecuciones/ejecuciones.csv` y `estado/objetivos_{sitio}.csv`.", "`modelos.py` (esquema)"],
  ], [5, 65, 30]),
  espacio(),
  p("Hasta aquí **nada está en el lago todavía**: todo vive en el disco temporal del contenedor."),

  h2("B5. Subida al lago"),
  p("De vuelta en `tarea.py`, `lago.subir_corrida()` (`src/nube/lago.py`) copia lo producido al contenedor de almacenamiento `datalake-tfm`:"),
  tabla(["Disco temporal del contenedor", "Destino en el lago"], [
    ["`capturas/{sitio}/fecha=F/{id}.csv`", "`bronce/aterrizaje/{sitio}/crudo/AAAA/MM/DD/productos_{sitio}_{ts}.csv`"],
    ["`bronze/{sitio}/…/*.gz`", "`bronce/aterrizaje/{sitio}/capturas/AAAA/MM/DD/{id}/`"],
    ["Fila de `ejecuciones.csv`", "`bronce/aterrizaje/{sitio}/ejecuciones/ejecucion_{ts}.json`"],
    ["`estado/objetivos_{sitio}.csv`", "`bronce/aterrizaje/{sitio}/estado/ultimo_estado.json`"],
  ], [40, 60]),
  espacio(),

  h2("B6. Fin y limpieza"),
  vineta("`tarea.py` termina con el código 0 (todo bien) o 1 (algún sitio FALLIDA)."),
  vineta("Azure marca la ejecución como **Succeeded** o **Failed** y **destruye la réplica**: la carpeta temporal desaparece. Lo único que queda es lo que se subió al lago y los registros (logs)."),
  vineta("Synapse, que consultaba el estado cada 2 minutos (`Esperar fin`), ve el resultado. Si es Succeeded, el orquestador sigue con el medallón."),

  // ------------------------------------------------------------------ resumen
  h1("Resumen: dónde está cada cosa"),
  tabla(["Qué", "Dónde está guardado", "Cuánto dura"], [
    ["Código fuente original (`ejecutar.py`)", "PC del equipo: `TFM_MonitoreoPrecios/src/extraccion/`", "Permanente; es la fuente de verdad"],
    ["Imagen con el código", "ACR `acrtfmwebscraping` → `tfm-captura:0.4` → `/app/src/extraccion/ejecutar.py`", "Permanente, hasta que se borre"],
    ["Configuración del job (imagen, CPU, variables)", "Container Apps Job `caj-tfm-captura`", "Permanente"],
    ["Contenedor en ejecución (réplica)", "Entorno `cae-tfm-webscraping`", "Solo durante la corrida (unos 34 min)"],
    ["Archivos de trabajo (`/tmp/tfm_…`)", "Disco de la réplica", "Se borran al terminar"],
    ["Resultados", "Lago `datalake-tfm` → `bronce/aterrizaje/`", "Permanentes"],
    ["Mensajes de la corrida", "`caj-tfm-captura` → *Historial de ejecuciones* → *Registros* (Log Analytics)", "Según la retención de Log Analytics"],
  ], [30, 45, 25]),
  espacio(),

  h1("Cómo comprobarlo y cómo actualizarlo"),
  h2("Ver el archivo que está en Azure"),
  p("El portal muestra la imagen y sus capas, pero no los archivos. Para leer el `ejecutar.py` desplegado y compararlo con el del repositorio, con Docker Desktop:"),
  ...codigo([
    "az acr login -n acrtfmwebscraping",
    "docker run --rm --entrypoint cat acrtfmwebscraping.azurecr.io/tfm-captura:0.4 /app/src/extraccion/ejecutar.py",
  ]),
  h2("Publicar un cambio de ejecutar.py"),
  p("Si alguien cambia `ejecutar.py` en el PC, Azure sigue usando la versión que está dentro de `tfm-captura:0.4`. Para que el cambio llegue a Azure hay que:"),
  numero("subir el número de versión (por ejemplo, `-Version 0.5` en `desplegar.ps1`);", "act"),
  numero("ejecutar `infra\\desplegar.ps1 -Pasos imagen,job`, que construye la imagen, la publica y actualiza el job para que apunte a ella.", "act"),
  h2("El contenedor del medallón funciona igual"),
  p("`caj-tfm-medallon` sigue el mismo ciclo, con otra imagen (`tfm-medallon:0.5`, construida con `medallon.Dockerfile`) y otro punto de entrada (`python -m src.nube.tarea_medallon`). Se publica con `infra\\desplegar.ps1 -Pasos imagen-medallon,job-medallon`."),
];

const doc = new Document({
  creator: "TFM Monitoreo de precios",
  title: "Ciclo de vida del contenedor de captura",
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
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Ciclo de vida del contenedor de captura · página ", size: 16, color: "808080" }), new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "808080" })] })] }) },
    children: contenido,
  }],
});

Packer.toBuffer(doc).then((b) => { fs.writeFileSync(salida, b); console.log("escrito", salida, b.length, "bytes"); });

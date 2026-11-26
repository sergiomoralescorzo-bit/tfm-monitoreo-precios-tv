// Genera el Word de la creación de las dos imágenes Docker y de los archivos Python que ejecuta cada una.
// Uso: node generar_imagenes_docker_word.js <salida.docx> <imagenes_docker.png>
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType,
  ShadingType, BorderStyle, ImageRun, TableLayoutType, AlignmentType, LevelFormat, Footer, PageNumber,
} = require("docx");

const [, , salida, imagen] = process.argv;
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
const nota = (t) => new Paragraph({ children: runs(t, { italics: true, color: "595959" }), spacing: { after: 120 }, indent: { left: 360 } });
// Numeración escrita a mano: con listas numeradas de Word, las listas de distintas secciones se mezclaban.
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
  keepNext: i < lineas.length - 1, keepLines: true,
}));
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
  new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun("Creación de las imágenes Docker")] }),
  p("", { children: [new TextRun({ text: "TFM Monitoreo de precios de televisores · estado al 20-oct-2026", italics: true, color: "595959" })] }),
  p("Este documento explica cómo se crean las dos imágenes Docker del proyecto y qué archivos Python ejecuta cada una. Complementa a *Flujo diario en Azure* (`docs/Flujo_ejecucion_Azure.docx`) y a *Ciclo de vida del contenedor de captura* (`docs/Ciclo_contenedor_captura.docx`). Las rutas de archivos son relativas a `TFM_MonitoreoPrecios/`."),
  p("Hay **dos imágenes**, una por cada contenedor. Las dos se construyen en el PC con Docker Desktop y se publican en el registro `acrtfmwebscraping`. Cambian la receta (Dockerfile), las librerías y el código Python que llevan dentro:"),
  tabla(["", "Imagen de captura", "Imagen del medallón"], [
    ["Receta", "`Dockerfile`", "`medallon.Dockerfile`"],
    ["Filtro de archivos", "`.dockerignore`", "`medallon.Dockerfile.dockerignore`"],
    ["Librerías", "`requirements-contenedor.txt`", "`requirements-medallon.txt`"],
    ["Imagen publicada", "`tfm-captura:0.4`", "`tfm-medallon:0.5`"],
    ["Tamaño", "3,76 GB (1,09 GB comprimida)", "1,23 GB (457 MB comprimida)"],
    ["Job que la usa", "`caj-tfm-captura`", "`caj-tfm-medallon`"],
    ["Python que arranca", "`src/nube/tarea.py`", "`src/nube/tarea_medallon.py`"],
  ], [24, 38, 38]),
  espacio(),

  // ------------------------------------------------------------------ 1
  h1("1. Qué significa crear una imagen Docker"),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 80 }, children: [new ImageRun({ type: "png", data: fs.readFileSync(imagen), transformation: { width: 620, height: 347 }, altText: { title: "Capas de las imágenes Docker", description: "Cada imagen se arma por capas: la base (sistema operativo y Python), la configuración, las librerías, el código y el punto de entrada. desplegar.ps1 construye y publica las imágenes en acrtfmwebscraping, y cada Container Apps Job descarga la suya al ejecutarse.", name: "imagenes" } })] }),
  pie("Figura 1. Capas de las dos imágenes y su publicación en Azure."),
  p("Una imagen se arma **por capas**, siguiendo las instrucciones del Dockerfile de arriba hacia abajo: primero el sistema operativo y Python, luego las librerías, después el código y, al final, el punto de entrada (qué ejecutar al encender el contenedor)."),
  p("Al ejecutar `docker build`, Docker:"),
  numero("toma la carpeta del proyecto (el **contexto**), **menos** lo que excluye el archivo `.dockerignore`;", "s1"),
  numero("ejecuta cada línea del Dockerfile y guarda el resultado como una capa;", "s1"),
  numero("etiqueta el resultado con un nombre y una versión, por ejemplo `tfm-captura:0.4`.", "s1"),
  p("Luego `docker push` sube las capas al registro `acrtfmwebscraping`. Si una capa no cambió (por ejemplo, las librerías), no se vuelve a subir.", { spacing: { before: 120, after: 120 } }),

  // ------------------------------------------------------------------ 2
  h1("2. Creación de la imagen de captura"),
  donde("Archivos: `Dockerfile`, `.dockerignore`, `requirements-contenedor.txt`"),
  h2("2.1. Qué archivos entran"),
  p("El archivo `.dockerignore` **excluye** `.venv/`, `data/`, `archivo/`, `docs/`, `tests/`, `tests_spark/`, `scripts/`, `synapse/`, `infra/`, **`src/medallon/`** y los `__pycache__`."),
  p("**Entran:** `Dockerfile`, `requirements-contenedor.txt`, `config/` y `src/` (sin medallón)."),
  h2("2.2. Las instrucciones, en orden"),
  tabla(["#", "Instrucción", "Qué hace", "Por qué"], [
    ["1", "`FROM mcr.microsoft.com/playwright/python:v1.63.0-noble`", "Descarga la base de Microsoft: Ubuntu 24.04, Python 3.12 y Chromium ya instalados.", "Éxito necesita un navegador para su listado. Por eso esta imagen pesa 3,76 GB."],
    ["2", "`ENV … TZ=America/Bogota`", "Fija la hora de Colombia y la salida en UTF-8.", "`modo_del_dia()` decide si es domingo según la hora de Colombia."],
    ["3", "`WORKDIR /app`", "Crea y usa la carpeta `/app`.", "Todo el código queda allí."],
    ["4", "`COPY requirements-contenedor.txt .`", "Copia la lista de librerías.", "Va antes del código para aprovechar la caché de capas."],
    ["5", "`RUN pip install … -r requirements-contenedor.txt`", "Instala `pyyaml`, `httpx`, `beautifulsoup4`, `lxml`, `pydantic`, `playwright==1.63.0`, `tzdata`, `azure-identity` y `azure-storage-file-datalake`.", "Son las que usan la extracción y la conexión al lago."],
    ["6", "`COPY config/ config/`", "Copia `fuentes.yaml`.", "Sitios, User-Agent, pausas y reintentos."],
    ["7", "`COPY src/ src/`", "Copia el código Python.", "Aquí entra `ejecutar.py`."],
    ["8", "`USER pwuser`", "Cambia a un usuario sin privilegios.", "Seguridad."],
    ["9", "`ENTRYPOINT [\"python\", \"-m\", \"src.nube.tarea\"]`", "Define el arranque.", "Es lo único que se ejecuta al encender el contenedor."],
  ], [5, 33, 34, 28]),
  espacio(),
  h2("2.3. Comando que la crea"),
  p("Paso `imagen` de `infra/desplegar.ps1`:"),
  ...codigo([
    "az acr login -n acrtfmwebscraping",
    "docker build -t acrtfmwebscraping.azurecr.io/tfm-captura:0.4 .",
    "docker push acrtfmwebscraping.azurecr.io/tfm-captura:0.4",
  ]),

  // ------------------------------------------------------------------ 3
  h1("3. Creación de la imagen del medallón"),
  donde("Archivos: `medallon.Dockerfile`, `medallon.Dockerfile.dockerignore`, `requirements-medallon.txt`"),
  h2("3.1. Qué archivos entran"),
  p("Este filtro funciona al revés: **excluye todo** (`*`) y solo deja entrar `requirements-medallon.txt`, `src/__init__.py`, `src/medallon/`, `src/catalogo/` y `src/nube/`. Docker usa este archivo porque tiene el mismo nombre que el Dockerfile seguido de `.dockerignore`."),
  h2("3.2. Las instrucciones, en orden"),
  tabla(["#", "Instrucción", "Qué hace", "Por qué"], [
    ["1", "`FROM python:3.10-slim-bookworm`", "Base liviana: Debian y Python 3.10.", "Spark 3.4 es compatible con Python 3.10, igual que Synapse."],
    ["2", "`RUN apt-get install openjdk-17-jre-headless procps`", "Instala Java 17.", "Spark corre sobre Java."],
    ["3", "`COPY requirements-medallon.txt .` y `RUN pip install …`", "Instala `pyspark==3.4.3`, `delta-spark==2.4.0`, `azure-identity` y `azure-storage-file-datalake`.", "Las mismas versiones que `tests_spark` y Synapse."],
    ["4", "`RUN python -c \"… urlretrieve …delta-core_2.12-2.4.0.jar…\"`", "Descarga una sola vez, al construir, los 2 archivos .jar de Delta y los deja en `pyspark/jars`.", "Así el contenedor no depende de Internet (Maven) cada vez que arranca."],
    ["5", "`ENV … TZ=America/Bogota`", "Fija la hora y la codificación.", "Igual que en la captura."],
    ["6", "`RUN useradd --create-home spark`", "Crea el usuario `spark`.", "Para no correr como administrador."],
    ["7", "`WORKDIR /app` y `COPY src/ src/`", "Copia el código (solo lo que dejó pasar el filtro).", "—"],
    ["8", "`USER spark`", "Cambia al usuario sin privilegios.", "Seguridad."],
    ["9", "`ENTRYPOINT [\"python\", \"-m\", \"src.nube.tarea_medallon\"]`", "Define el arranque.", "—"],
  ], [5, 33, 34, 28]),
  espacio(),
  h2("3.3. Comando que la crea"),
  p("Paso `imagen-medallon` de `infra/desplegar.ps1`:"),
  ...codigo([
    "az acr login -n acrtfmwebscraping",
    "docker build -f medallon.Dockerfile -t acrtfmwebscraping.azurecr.io/tfm-medallon:0.5 .",
    "docker push acrtfmwebscraping.azurecr.io/tfm-medallon:0.5",
  ]),

  // ------------------------------------------------------------------ 4
  h1("4. Qué archivos Python se ejecutan en cada contenedor"),
  p("Al encenderse, cada contenedor ejecuta **un solo archivo**: el de su ENTRYPOINT. Ese archivo **importa** a los demás. Los árboles muestran quién llama a quién, en el orden en que se ejecutan."),

  h2("4.1. Contenedor de captura: python -m src.nube.tarea"),
  ...codigo([
    "src/nube/tarea.py                      ← ARRANCA AQUÍ (orquesta la corrida)",
    "├── src/nube/lago.py                   ← baja el estado y sube los resultados al lago",
    "│   └── src/extraccion/modelos.py",
    "├── src/extraccion/sitios/base.py      ← ahora(): hora de Colombia → modo del día",
    "└── src/extraccion/ejecutar.py         ← ejecutar(): los 5 sitios en paralelo",
    "    ├── src/extraccion/cliente.py      ← HTTP con pausas, reintentos y bloqueos",
    "    │   └── src/extraccion/robots.py   ← lee robots.txt",
    "    ├── src/extraccion/sitemap.py      ← descubre las fichas en los sitemaps",
    "    ├── src/extraccion/sitios/sap_commerce.py  ← Alkosto y Ktronix",
    "    ├── src/extraccion/sitios/vtex.py          ← Jumbo y Olímpica",
    "    │   └── src/catalogo/gtin.py               ← valida EAN/GTIN",
    "    ├── src/extraccion/sitios/exito.py         ← Éxito (Chromium con Playwright)",
    "    ├── src/extraccion/sitios/base.py          ← arma cada registro",
    "    │   ├── src/catalogo/atributos_tv.py       ← marca, pulgadas y referencia",
    "    │   └── src/catalogo/gtin.py",
    "    ├── src/extraccion/bronze.py       ← guarda la respuesta original (.gz)",
    "    ├── src/extraccion/clasificacion.py← ¿es un televisor? (en alcance)",
    "    │   └── src/catalogo/atributos_tv.py",
    "    └── src/extraccion/modelos.py      ← esquema de los registros",
  ]),
  p("**Copiados en la imagen pero que no se ejecutan:** `src/extraccion/informe.py`, `src/extraccion/reproceso.py`, `src/nube/reproceso.py`, `src/nube/tarea_medallon.py`, `src/nube/sql_serverless.py`, `src/catalogo/construir_maestro.py`, `src/catalogo/emparejamiento.py` y `src/validacion/`. Entran porque se copia `src/` completo, pero nadie los importa en esta corrida. Se usan en el PC."),

  h2("4.2. Contenedor del medallón: python -m src.nube.tarea_medallon"),
  ...codigo([
    "src/nube/tarea_medallon.py             ← ARRANCA AQUÍ: Spark local, baja, procesa, sube",
    "├── src/nube/lago.py                   ← baja del lago y sube el resultado",
    "├── src/medallon/rutas.py              ← lista de sitios y rutas de cada capa",
    "└── src/medallon/semanal.py            ← ejecuta las 3 capas en orden",
    "    ├── 1. src/medallon/conformidad.py ← CSV → Delta sin transformar",
    "    ├── 2. src/medallon/plata.py       ← tipa, deduplica, clasifica y empareja",
    "    │      ├── src/catalogo/emparejamiento.py  ← regla EAN → referencia",
    "    │      │   ├── src/catalogo/atributos_tv.py",
    "    │      │   └── src/catalogo/gtin.py",
    "    │      ├── src/catalogo/atributos_tv.py",
    "    │      └── src/medallon/atipicos.py        ← marca los precios atípicos",
    "    └── 3. src/medallon/oro.py         ← modelo estrella e indicadores",
  ]),
  p("**Copiado pero que no se ejecuta:** `src/catalogo/construir_maestro.py`. Además, la carpeta `src/nube/` entra completa, pero de ella solo se usan `tarea_medallon.py` y `lago.py`. Esta imagen **no** contiene `src/extraccion/`, porque el medallón no captura."),
  nota("Detalle técnico: lago.py importa src/extraccion/modelos.py solo dentro de una función que el medallón nunca llama. Por eso la imagen del medallón funciona aunque no tenga src/extraccion/."),

  // ------------------------------------------------------------------ 5
  h1("5. Versiones y cuándo se reconstruye"),
  p("En Docker Desktop del PC están todas las versiones construidas. Azure usa solo las que indican los jobs:"),
  tabla(["Imagen", "Versiones locales", "En uso en Azure"], [
    ["`tfm-captura`", "0.3, 0.4", "**0.4**"],
    ["`tfm-medallon`", "0.1 a 0.5", "**0.5**: `CAMBIO_BRUSCO` solo compara días con stock"],
  ], [25, 25, 50]),
  espacio(),
  p("**Hay que reconstruir la imagen cuando cambia** cualquier archivo que entra en ella: el código en `src/`, `config/fuentes.yaml`, la lista de librerías o el propio Dockerfile. El procedimiento es:"),
  numero("subir el número de versión (`-Version` o `-VersionMedallon` en `desplegar.ps1`);", "s5"),
  numero("ejecutar `infra\\desplegar.ps1 -Pasos imagen,job` (captura) o `-Pasos imagen-medallon,job-medallon` (medallón);", "s5"),
  numero("el paso `job` actualiza el job para que use la nueva etiqueta. Desde la siguiente corrida de las 06:00, Azure usa el código nuevo.", "s5"),
  p("**No hace falta reconstruir** si cambia algo de Synapse (pipelines y disparador), de las Logic Apps, del SQL o de Power BI, porque eso no está dentro de las imágenes.", { spacing: { before: 120, after: 120 } }),
];

const doc = new Document({
  creator: "TFM Monitoreo de precios",
  title: "Creación de las imágenes Docker",
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
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Creación de las imágenes Docker · página ", size: 16, color: "808080" }), new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "808080" })] })] }) },
    children: contenido,
  }],
});

Packer.toBuffer(doc).then((b) => { fs.writeFileSync(salida, b); console.log("escrito", salida, b.length, "bytes"); });

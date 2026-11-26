// Piezas comunes de los Word de proceso (generar_proceso_captura_word.js y generar_proceso_medallon_word.js):
// mismo formato que los demás documentos de docs/ (carta, Calibri, títulos azules, tablas con encabezado celeste).
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType,
  ShadingType, BorderStyle, ImageRun, TableLayoutType, AlignmentType, LevelFormat, Footer, PageNumber,
} = require("docx");

const ANCHO = 9360; // carta con márgenes de 1"

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
const subtitulo = (t) => new Paragraph({ children: [new TextRun({ text: t, italics: true, color: "595959" })], spacing: { after: 120 } });
const espacio = () => new Paragraph({ spacing: { after: 60 }, children: [] });

// Numeración escrita a mano: con listas numeradas de Word, las listas de distintas secciones se mezclaban.
const contadores = {};
const numero = (t, ref) => {
  contadores[ref] = (contadores[ref] || 0) + 1;
  return new Paragraph({ children: [new TextRun(`${contadores[ref]}.\t`), ...runs(t)], indent: { left: 720, hanging: 360 }, tabStops: [{ type: "left", position: 720 }], spacing: { after: 60 } });
};

// Bloque de código: una línea por párrafo, fondo gris, sin cortarse entre páginas.
const codigo = (lineas) => lineas.map((l, i) => new Paragraph({
  children: [new TextRun({ text: l || " ", font: "Consolas", size: 17 })],
  shading: { type: ShadingType.CLEAR, color: "auto", fill: "F2F2F2" },
  spacing: { after: i === lineas.length - 1 ? 160 : 0 }, indent: { left: 200, right: 200 },
  keepNext: i < lineas.length - 1, keepLines: true,
}));

// Figura: imagen centrada (ancho 620 px) y pie de figura.
const figura = (ruta, alto, titulo, descripcion, pie) => [
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 80 }, keepNext: true, children: [new ImageRun({
    type: "png", data: fs.readFileSync(ruta), transformation: { width: 620, height: alto },
    altText: { title: titulo, description: descripcion, name: titulo } })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, children: runs(pie, { size: 18, italics: true, color: "595959" }), spacing: { after: 200 } }),
];

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
      ...filas.map((f) => new TableRow({ cantSplit: true, children: f.map((t, i) => celda(t, i, false)) })),
    ],
  });
}

function escribir(salida, titulo, contenido) {
  const doc = new Document({
    creator: "TFM Monitoreo de precios",
    title: titulo,
    styles: {
      default: { document: { run: { font: "Calibri", size: 21 } } },
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
      footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: `${titulo} · página `, size: 16, color: "808080" }), new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "808080" })] })] }) },
      children: [new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun(titulo)] }), ...contenido],
    }],
  });
  return Packer.toBuffer(doc).then((b) => { fs.writeFileSync(salida, b); console.log("escrito", salida, b.length, "bytes"); });
}

module.exports = { runs, p, h1, h2, vineta, donde, nota, subtitulo, espacio, numero, codigo, figura, tabla, escribir };

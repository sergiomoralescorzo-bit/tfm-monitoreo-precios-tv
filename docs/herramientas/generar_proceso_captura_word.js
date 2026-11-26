// Genera el Word del proceso completo del Container Apps Job caj-tfm-captura: arquitectura, imagen, configuración,
// ejecución diaria, Python que corre, entradas y salidas, monitoreo y actualización.
// Uso: node generar_proceso_captura_word.js <salida.docx>   (lee los PNG de esta misma carpeta)
const path = require("path");
const { p, h1, h2, vineta, donde, nota, subtitulo, espacio, numero, codigo, figura, tabla, escribir } = require("./word_comun");

const [, , salida] = process.argv;
const img = (n) => path.join(__dirname, n);

const contenido = [
  subtitulo("TFM Monitoreo de precios de televisores · estado al 20-oct-2026"),
  p("Este documento describe de principio a fin el contenedor de **captura** (`caj-tfm-captura`): cómo está armado en Azure, cómo se crea su imagen Docker, cómo se ejecuta cada día, qué archivos Python corre y qué deja en el lago. Las rutas de archivos son relativas a `TFM_MonitoreoPrecios/`. El contenedor del medallón tiene su propio documento: `docs/Proceso_caj-tfm-medallon.docx`."),

  h1("Ficha técnica"),
  tabla(["Elemento", "Valor"], [
    ["Recurso de Azure", "Container Apps Job `caj-tfm-captura`, grupo `RG-TFM-WEBSCRAPING`, West US"],
    ["Entorno", "`cae-tfm-webscraping` (perfil Consumption)"],
    ["Imagen", "`acrtfmwebscraping.azurecr.io/tfm-captura:0.4`"],
    ["Receta de la imagen", "`Dockerfile` · `.dockerignore` · `requirements-contenedor.txt`"],
    ["Punto de entrada", "`python -m src.nube.tarea` (`src/nube/tarea.py`)"],
    ["Recursos", "1 vCPU · 2 GiB de memoria · tope de 2 h por ejecución · sin reintentos"],
    ["Identidad", "`id-tfm-captura`: AcrPull sobre el ACR y Storage Blob Data Contributor sobre el lago"],
    ["Quién lo inicia", "`pl_captura_diaria` (Synapse), llamada por `pl_orquestador_diario` a las 06:00 de Colombia"],
    ["Duración habitual", "≈34 minutos (5 sitios en paralelo)"],
    ["Lee del lago", "`bronce/aterrizaje/{sitio}/estado/ultimo_estado.json`"],
    ["Escribe en el lago", "`bronce/aterrizaje/{sitio}/crudo/`, `capturas/`, `ejecuciones/` y `estado/`"],
    ["Fuentes externas", "Alkosto, Ktronix, Jumbo, Olímpica y Éxito (HTTPS público)"],
    ["Registros", "Log Analytics `workspace-gmYJ` (Historial de ejecuciones del job)"],
  ], [28, 72]),
  espacio(),

  // ------------------------------------------------------------------ 1
  h1("1. Arquitectura"),
  ...figura(img("cap_arquitectura.png"), 335, "Arquitectura de caj-tfm-captura",
    "Synapse inicia el job; el job corre en el entorno cae-tfm-webscraping con la imagen del ACR y la identidad id-tfm-captura; la réplica consulta los 5 sitios por HTTPS, lee y escribe bronce/aterrizaje en el lago y envía sus registros a Log Analytics.",
    "Figura 1. Arquitectura del contenedor de captura."),
  p("El job es una «ficha» que dice qué imagen correr y con qué recursos. Cuando Synapse lo inicia, Azure crea una **réplica**: un contenedor temporal que ejecuta el código, consulta los sitios por Internet, guarda el resultado en el lago y se destruye al terminar."),
  tabla(["Componente", "Papel", "Relación con el job"], [
    ["`syn-tfm-webscraping`", "Orquesta: decide cuándo correr y espera el resultado", "Su identidad tiene el rol Contributor sobre el job para iniciarlo (`POST /start`) y consultar su estado"],
    ["`acrtfmwebscraping`", "Guarda la imagen `tfm-captura:0.4`", "Azure descarga la imagen de aquí en cada ejecución"],
    ["`id-tfm-captura`", "Identidad administrada (sin contraseñas)", "AcrPull para descargar la imagen; Storage Blob Data Contributor para leer y escribir el lago"],
    ["`cae-tfm-webscraping`", "Entorno donde corren los contenedores", "Aporta la máquina (1 vCPU, 2 GiB) mientras dura la réplica"],
    ["`sttfmwebscraping` / `datalake-tfm`", "Lago de datos (ADLS Gen2)", "Entrada: estado de las fichas. Salida: todo `bronce/aterrizaje/`"],
    ["`workspace-gmYJ`", "Log Analytics", "Recibe los mensajes que imprime el Python"],
    ["5 sitios web", "Fuentes de precios", "El contenedor los consulta por HTTPS, respetando robots.txt y pausas"],
  ], [26, 30, 44]),
  espacio(),

  // ------------------------------------------------------------------ 2
  h1("2. Creación de la imagen Docker"),
  ...figura(img("ciclo_despliegue.png"), 260, "Despliegue de la imagen de captura",
    "En el PC, Docker construye la imagen tfm-captura:0.4 con el Dockerfile y el código; la imagen se sube al registro acrtfmwebscraping; el job caj-tfm-captura apunta a esa imagen.",
    "Figura 2. Del PC al registro de imágenes, y del registro al job."),
  h2("2.1. Qué archivos entran (A1)"),
  p("El archivo `.dockerignore` **excluye** `.venv/`, `data/`, `archivo/`, `docs/`, `tests/`, `tests_spark/`, `scripts/`, `synapse/`, `infra/`, **`src/medallon/`** y los `__pycache__`. **Entran:** `Dockerfile`, `requirements-contenedor.txt`, `config/` y `src/` (sin medallón)."),
  h2("2.2. Las instrucciones del Dockerfile, en orden"),
  tabla(["#", "Instrucción", "Qué hace", "Por qué"], [
    ["1", "`FROM mcr.microsoft.com/playwright/python:v1.63.0-noble`", "Base de Microsoft: Ubuntu 24.04, Python 3.12 y Chromium ya instalados.", "Éxito necesita un navegador para su listado. Por eso la imagen pesa 3,76 GB."],
    ["2", "`ENV … TZ=America/Bogota`", "Fija la hora de Colombia y la salida en UTF-8.", "`modo_del_dia()` decide si es domingo según la hora de Colombia."],
    ["3", "`WORKDIR /app`", "Crea y usa la carpeta `/app`.", "Todo el código queda allí."],
    ["4", "`COPY requirements-contenedor.txt .`", "Copia la lista de librerías.", "Va antes del código para aprovechar la caché de capas."],
    ["5", "`RUN pip install … -r requirements-contenedor.txt`", "Instala `pyyaml`, `httpx`, `beautifulsoup4`, `lxml`, `pydantic`, `playwright==1.63.0`, `tzdata`, `azure-identity` y `azure-storage-file-datalake`.", "Las usan la extracción y la conexión al lago."],
    ["6", "`COPY config/ config/`", "Copia `fuentes.yaml`.", "Sitios, User-Agent, pausas y reintentos."],
    ["7", "`COPY src/ src/`", "Copia el código Python.", "Aquí entra `ejecutar.py`."],
    ["8", "`USER pwuser`", "Cambia a un usuario sin privilegios.", "Seguridad."],
    ["9", "`ENTRYPOINT [\"python\", \"-m\", \"src.nube.tarea\"]`", "Define el arranque.", "Es lo único que se ejecuta al encender el contenedor."],
  ], [5, 33, 34, 28]),
  espacio(),
  h2("2.3. Construir y publicar (A2)"),
  p("Paso `imagen` de `infra/desplegar.ps1`, ejecutado en el PC con Docker Desktop abierto:"),
  ...codigo([
    "az acr login -n acrtfmwebscraping",
    "docker build -t acrtfmwebscraping.azurecr.io/tfm-captura:0.4 .",
    "docker push acrtfmwebscraping.azurecr.io/tfm-captura:0.4",
  ]),
  p("La imagen queda en el portal en *Registro de contenedor* `acrtfmwebscraping` → *Repositorios* → `tfm-captura` → `0.4`. Es de solo lectura: el portal muestra sus capas, pero no permite abrir los archivos."),

  // ------------------------------------------------------------------ 3
  h1("3. Configuración del job (A3)"),
  donde("Comando: `infra\\desplegar.ps1 -Pasos job` · Azure: *Container Apps Job* `caj-tfm-captura` → *Contenedores*"),
  tabla(["Parámetro", "Valor", "Significado"], [
    ["`--image`", "`acrtfmwebscraping.azurecr.io/tfm-captura:0.4`", "Qué imagen usar."],
    ["`--trigger-type`", "`Manual`", "No tiene horario propio: lo enciende Synapse."],
    ["`--cpu` / `--memory`", "1 vCPU / 2 GiB", "Tamaño de la máquina."],
    ["`--replica-timeout`", "7200 s (2 h)", "Si tarda más, Azure la detiene."],
    ["`--replica-retry-limit`", "0", "Si falla, no la reintenta (evita volver a consultar los sitios)."],
    ["`--parallelism` / `--replica-completion-count`", "1 / 1", "Una sola réplica por ejecución."],
    ["`--mi-user-assigned`, `--registry-identity`", "`id-tfm-captura`", "Identidad para descargar la imagen y escribir en el lago."],
    ["`--env-vars`", "`TFM_ADLS_CUENTA=sttfmwebscraping`, `TFM_ADLS_CONTENEDOR=datalake-tfm`, `AZURE_CLIENT_ID=…`", "Le indican al Python a qué lago escribir y con qué identidad."],
  ], [30, 32, 38]),
  espacio(),
  p("El job no guarda una copia del código: solo la referencia a la imagen. Si la imagen cambia, hay que volver a ejecutar este paso para que el job apunte a la nueva versión."),

  // ------------------------------------------------------------------ 4
  h1("4. Ejecución diaria, paso a paso"),
  ...figura(img("ciclo_ejecucion.png"), 369, "Ejecución diaria de la captura",
    "Synapse pide iniciar el job; Azure crea una réplica; el contenedor ejecuta src.nube.tarea, que baja el estado, llama a ejecutar.py, sube los resultados y termina; Azure destruye la réplica y Synapse ve el estado final.",
    "Figura 3. De la orden de Synapse a la destrucción del contenedor."),

  h2("B1. Synapse enciende el job"),
  donde("Archivo: `synapse/pipelines/pl_captura_diaria.json`"),
  p("A las 06:00 el disparador `tr_orquestador_diario` inicia `pl_orquestador_diario`, que llama a `pl_captura_diaria`. Sus actividades:"),
  tabla(["Actividad", "Qué hace"], [
    ["`Iniciar captura`", "`POST https://management.azure.com/…/jobs/caj-tfm-captura/start` con la identidad de Synapse. Es como presionar «Ejecutar ahora» en el portal. Hasta 2 reintentos."],
    ["`Guardar ejecucion`", "Guarda el nombre de la ejecución que devuelve Azure."],
    ["`Esperar fin`", "Cada 120 s consulta `GET …/executions/{nombre}` hasta que el estado deje de ser Running. Tope de 2 h 30 min."],
    ["`Verificar resultado`", "Si el estado final no es Succeeded, termina con `CAPTURA_FALLIDA`."],
    ["`Avisar fallo - …`", "Si cualquier actividad falla, llama a `pl_notificar_fallo` (correo y Teams) y deja la pipeline en Failed."],
  ], [26, 74]),
  espacio(),

  h2("B2. Azure crea la réplica"),
  p("Container Apps toma una máquina del entorno `cae-tfm-webscraping`, descarga `tfm-captura:0.4` del ACR con la identidad `id-tfm-captura` y la enciende con las variables de entorno del job."),

  h2("B3. Arranca src/nube/tarea.py"),
  p("El ENTRYPOINT ejecuta `python -m src.nube.tarea`. Ese archivo dirige la corrida:"),
  ...codigo([
    "modo = modo_del_dia()                     # domingo → \"completo\", otro día → \"seguimiento\"",
    "raiz = tempfile.mkdtemp(prefix=\"tfm_\")    # carpeta temporal, ej. /tmp/tfm_ab12",
    "destino = lago.destino_desde_entorno()    # conexión al lago (TFM_ADLS_CUENTA, …)",
    "lago.bajar_estado(destino, raiz, sitios)  # baja las fichas ya descubiertas",
    "ejecuciones = asyncio.run(ejecutar(...))  # ◀── src/extraccion/ejecutar.py",
    "imprimir_resumen(ejecuciones)             # tabla por sitio en los registros",
    "lago.subir_corrida(destino, raiz, id)     # sube los resultados",
    "return 0 si ningún sitio quedó FALLIDA, si no 1",
  ]),
  tabla(["Modo", "Cuándo", "Qué hace"], [
    ["`completo`", "Domingo", "Vuelve a descubrir todas las fichas de televisores (sitemaps o listado) y las captura."],
    ["`seguimiento`", "Lunes a sábado", "Captura las fichas descubiertas la última vez (las de `ultimo_estado.json`). Si no hay, descubre."],
  ], [18, 20, 62]),
  espacio(),

  h2("B4. src/extraccion/ejecutar.py captura los 5 sitios"),
  p("**`ejecutar()`** crea el id de la corrida (por ejemplo `20261020T060312_a1b2c3`: hora de Colombia más 6 caracteres al azar) y lanza **`ejecutar_sitio()` para los 5 sitios a la vez** con `asyncio.gather`."),
  p("**`ejecutar_sitio()`**, para cada sitio:"),
  tabla(["#", "Qué hace", "Archivo"], [
    ["1", "Abre un cliente HTTP con el User-Agent del TFM, una pausa de 1,5 s, 3 reintentos, 30 s de espera y un tope de 3 bloqueos seguidos.", "`cliente.py`"],
    ["2", "Lee el robots.txt del sitio. Ninguna URL prohibida se pide.", "`robots.py`"],
    ["3", "Obtiene la lista de fichas: las conocidas (seguimiento) o las descubre en el sitemap; en Éxito, en el listado de categoría con Chromium.", "`sitemap.py`, `sitios/exito.py`"],
    ["4", "Para cada ficha: la descarga, guarda la respuesta original comprimida (.gz) y extrae precio de venta y de lista, stock, EAN, vendedor y título.", "`bronze.py` + `sitios/sap_commerce.py`, `vtex.py` o `exito.py`"],
    ["5", "Si el sitio responde 403/429 repetidamente, se detiene y registra BLOQUEADO, sin intentar esquivarlo.", "`cliente.py`"],
    ["6", "Clasifica cada registro: en alcance (televisor) o fuera (accesorio, combo…), con el motivo.", "`clasificacion.py`"],
    ["7", "Calcula el estado del sitio: EXITOSA, PARCIAL (hubo errores, bloqueos o fichas sin consultar) o FALLIDA (ningún precio).", "—"],
    ["8", "Escribe en la carpeta temporal la tabla de productos, la evidencia, la fila de ejecución y la lista de fichas.", "`modelos.py` (esquema)"],
  ], [5, 65, 30]),
  espacio(),
  tabla(["Sitio", "Plataforma", "Cómo descubre", "Cómo lee la ficha"], [
    ["Alkosto", "SAP Commerce", "`/sitemap-productos.xml`", "HTML con microdatos schema.org"],
    ["Ktronix", "SAP Commerce", "`/sitemap-productos.xml`", "HTML con microdatos schema.org"],
    ["Jumbo", "VTEX", "Índice `/sitemap.xml` y sus `product-N.xml`", "API pública de catálogo (JSON)"],
    ["Olímpica", "VTEX", "Índice `/sitemap.xml` (robots.txt no permite paginar la búsqueda)", "API pública de catálogo (JSON)"],
    ["Éxito", "VTEX (frontal Next.js)", "Listado de categoría y páginas por marca, renderizados con Chromium (Playwright), hasta 60 páginas", "HTML, dato `__NEXT_DATA__` (sin navegador)"],
  ], [14, 18, 34, 34]),
  espacio(),
  p("Hasta aquí todo está en el disco temporal del contenedor; nada se ha escrito en el lago."),

  h2("B5. Subida al lago"),
  p("`lago.subir_corrida()` (`src/nube/lago.py`) copia lo producido con el SDK de Azure y la identidad del job. Ver la tabla de la sección 6."),

  h2("B6. Fin y limpieza"),
  vineta("`tarea.py` devuelve 0 si ningún sitio quedó FALLIDA y 1 en caso contrario."),
  vineta("Azure marca la ejecución como **Succeeded** o **Failed** y destruye la réplica: el disco temporal desaparece."),
  vineta("`Esperar fin` ve el estado final. Si es Succeeded, el orquestador inicia el medallón (`caj-tfm-medallon`)."),

  // ------------------------------------------------------------------ 5
  h1("5. Archivos Python que se ejecutan"),
  p("El contenedor ejecuta un solo archivo, el del ENTRYPOINT; ese archivo importa a los demás. El árbol muestra quién llama a quién:"),
  ...codigo([
    "src/nube/tarea.py                      ← ARRANCA AQUÍ (orquesta la corrida)",
    "├── src/nube/lago.py                   ← baja el estado y sube los resultados",
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
  tabla(["Archivo", "Qué hace"], [
    ["`src/nube/tarea.py`", "Punto de entrada: elige el modo, prepara la carpeta temporal, baja el estado, llama a la extracción y sube la corrida."],
    ["`src/nube/lago.py`", "Conexión al lago con `DefaultAzureCredential`; traduce las rutas locales a la estructura del lago."],
    ["`src/extraccion/ejecutar.py`", "Corrida de los 5 sitios: descubrir, capturar, clasificar, contar y escribir."],
    ["`src/extraccion/cliente.py`", "Cliente HTTP responsable: una petición a la vez por sitio, pausa mínima, reintentos con espera creciente y parada ante bloqueos."],
    ["`src/extraccion/robots.py`", "Interpreta robots.txt con comodines (RFC 9309)."],
    ["`src/extraccion/sitemap.py`", "Lee índices y listas de URL de los sitemaps XML."],
    ["`src/extraccion/sitios/*.py`", "Un extractor por plataforma (SAP Commerce, VTEX, Éxito) y las piezas comunes (`base.py`)."],
    ["`src/extraccion/bronze.py`", "Guarda cada respuesta original comprimida como evidencia."],
    ["`src/extraccion/clasificacion.py`", "Marca `en_alcance` y el motivo de exclusión, sin borrar nada."],
    ["`src/extraccion/modelos.py`", "Esquema (pydantic) del registro de captura y del registro de ejecución."],
    ["`src/catalogo/gtin.py`, `atributos_tv.py`", "Normalizan el EAN a GTIN-14 y extraen marca, pulgadas y referencia del título."],
  ], [32, 68]),
  espacio(),
  p("**Copiados en la imagen pero que no se ejecutan aquí:** `src/extraccion/informe.py`, `src/extraccion/reproceso.py`, `src/nube/reproceso.py`, `src/nube/tarea_medallon.py`, `src/nube/sql_serverless.py`, `src/catalogo/construir_maestro.py`, `src/catalogo/emparejamiento.py` y `src/validacion/`. Se usan en el PC."),

  // ------------------------------------------------------------------ 6
  h1("6. Entradas y salidas en el lago"),
  donde("Cuenta `sttfmwebscraping`, contenedor `datalake-tfm`"),
  tabla(["Sentido", "Carpeta temporal del contenedor", "Ruta en el lago", "Contenido"], [
    ["Lee", "`estado/objetivos_{sitio}.csv`", "`bronce/aterrizaje/{sitio}/estado/ultimo_estado.json`", "Fichas descubiertas (para el modo seguimiento)"],
    ["Escribe", "`capturas/{sitio}/fecha=F/{id}.csv`", "`bronce/aterrizaje/{sitio}/crudo/AAAA/MM/DD/productos_{sitio}_{ts}.csv`", "Tabla de productos: un registro por ficha y vendedor"],
    ["Escribe", "`bronze/{sitio}/fecha=F/{id}/*.gz`", "`bronce/aterrizaje/{sitio}/capturas/AAAA/MM/DD/{id}/`", "Respuestas originales (evidencia para reprocesar)"],
    ["Escribe", "fila de `ejecuciones/ejecuciones.csv`", "`bronce/aterrizaje/{sitio}/ejecuciones/ejecucion_{ts}.json`", "Registro de la corrida: duración, conteos y estado"],
    ["Escribe", "`estado/objetivos_{sitio}.csv`", "`bronce/aterrizaje/{sitio}/estado/ultimo_estado.json`", "Fichas vigentes para el día siguiente"],
  ], [11, 26, 36, 27]),
  espacio(),
  p("Estos archivos son la entrada del medallón, que los convierte en tablas Delta (ver `docs/Proceso_caj-tfm-medallon.docx`)."),

  // ------------------------------------------------------------------ 7
  h1("7. Estados y resultado"),
  tabla(["Nivel", "Valores", "Cómo se decide"], [
    ["Registro (ficha)", "OK, SIN_STOCK, NO_ENCONTRADO, ERROR_HTTP, ERROR_PARSEO, PROHIBIDO_ROBOTS, BLOQUEADO", "Según la respuesta del sitio y el resultado del parseo"],
    ["Sitio", "EXITOSA, PARCIAL, FALLIDA", "FALLIDA si no hay ningún OK ni SIN_STOCK; PARCIAL si hubo errores, bloqueos o fichas sin consultar"],
    ["Contenedor", "Código de salida 0 o 1", "1 si algún sitio quedó FALLIDA"],
    ["Ejecución en Azure", "Succeeded o Failed", "Traducción del código de salida; es lo que lee `pl_captura_diaria`"],
  ], [20, 40, 40]),
  espacio(),
  nota("Captura responsable: el contenedor respeta robots.txt, hace pausas entre peticiones, usa un User-Agent identificable y no intenta evadir bloqueos."),

  // ------------------------------------------------------------------ 8
  h1("8. Monitoreo y fallos"),
  vineta("**Estado de cada ejecución:** *Container Apps Job* `caj-tfm-captura` → *Historial de ejecuciones*."),
  vineta("**Mensajes del Python** (progreso cada 50 fichas, resumen por sitio, errores): en la misma ejecución → *Registros* (Log Analytics `workspace-gmYJ`)."),
  vineta("**Si falla:** `pl_captura_diaria` llama a `pl_notificar_fallo`, que envía correo a los 3 destinatarios y una tarjeta a Teams. El medallón no se ejecuta ese día."),
  vineta("**Si no corre:** la Logic App `la-tfm-vigilancia` revisa a las 09:30 que haya una ejecución exitosa desde las 04:30 y avisa si no."),
  vineta("**En Synapse:** *Monitor* → *Ejecuciones de canalización* → `pl_orquestador_diario` / `pl_captura_diaria`."),

  // ------------------------------------------------------------------ 9
  h1("9. Probar y actualizar"),
  h2("9.1. Probar la imagen en el PC"),
  p("Sin tocar el lago, con 3 fichas de un sitio:"),
  ...codigo(["docker run --rm --ipc=host tfm-captura:0.4 --sin-lago --sitios jumbo --limite 3"]),
  p("Opciones de `tarea.py`: `--modo completo|seguimiento`, `--sitios`, `--limite`, `--sin-lago` (no lee ni escribe en ADLS) y `--lago-local <carpeta>` (usa una carpeta como lago)."),
  h2("9.2. Ver el archivo desplegado"),
  ...codigo([
    "az acr login -n acrtfmwebscraping",
    "docker run --rm --entrypoint cat acrtfmwebscraping.azurecr.io/tfm-captura:0.4 /app/src/extraccion/ejecutar.py",
  ]),
  h2("9.3. Publicar un cambio"),
  p("Cualquier cambio en `src/`, `config/fuentes.yaml`, `requirements-contenedor.txt` o el `Dockerfile` requiere una imagen nueva:"),
  numero("subir la versión con `-Version` (por ejemplo, 0.5);", "pub"),
  numero("ejecutar `infra\\desplegar.ps1 -Pasos imagen,job -Version 0.5`;", "pub"),
  numero("desde la siguiente corrida de las 06:00, el job usa la imagen nueva.", "pub"),
  p("Los cambios en Synapse, Logic Apps, SQL o Power BI no requieren reconstruir la imagen.", { spacing: { before: 120, after: 120 } }),

  // ------------------------------------------------------------------ resumen
  h1("Resumen: dónde está cada cosa"),
  tabla(["Qué", "Dónde", "Cuánto dura"], [
    ["Código fuente", "PC: `TFM_MonitoreoPrecios/src/` y `config/`", "Permanente (fuente de verdad)"],
    ["Imagen con el código", "ACR `acrtfmwebscraping` → `tfm-captura:0.4` → `/app/`", "Permanente, hasta que se borre"],
    ["Configuración del job", "Container Apps Job `caj-tfm-captura`", "Permanente"],
    ["Contenedor en ejecución", "Réplica en `cae-tfm-webscraping`", "≈34 min por día"],
    ["Archivos de trabajo", "`/tmp/tfm_…` de la réplica", "Se borran al terminar"],
    ["Resultados", "`datalake-tfm` → `bronce/aterrizaje/`", "Permanentes"],
    ["Registros", "Log Analytics `workspace-gmYJ`", "Según la retención de Log Analytics"],
  ], [26, 46, 28]),
];

escribir(salida, "Proceso del contenedor caj-tfm-captura", contenido);

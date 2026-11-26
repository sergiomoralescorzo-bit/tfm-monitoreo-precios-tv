# Anexo A1 — Prueba de viabilidad de las fuentes

**Fecha de la prueba:** 13 de octubre de 2026
**Objetivo:** comprobar, antes de programar, cómo exponen hoy los iPhone las cinco cadenas y qué permite su `robots.txt`.
**Método:** peticiones HTTP manuales (curl o Python) desde un equipo local, con pausas entre llamadas. No se usaron credenciales ni se superaron restricciones de acceso.

## 1. Resumen por sitio

| Sitio | Plataforma | ¿Publica EAN? | Vía permitida y viable | Herramienta |
|---|---|---|---|---|
| Alkosto | SAP Commerce | Sí, en la URL `/p/{EAN}` | La ficha de producto resuelve directamente por EAN; precio y disponibilidad en microdatos schema.org | `httpx` + BeautifulSoup |
| Ktronix | SAP Commerce | Sí, en la URL `/p/{EAN}` | Igual que Alkosto | `httpx` + BeautifulSoup |
| Jumbo | VTEX | Sí (`items[].ean`) | API pública de catálogo VTEX (JSON), permitida por robots.txt | `httpx` (JSON) |
| Olímpica | VTEX | Sí (`items[].ean`) | API pública de catálogo VTEX (JSON), permitida por robots.txt | `httpx` (JSON) |
| Éxito | VTEX + Next.js | Sí (a confirmar en la ficha) | **robots.txt prohíbe `/api/`**. La página de marca `/apple` carga los productos en el cliente, así que hay que renderizarla | **Playwright** |
| Falabella | Propia (Next.js) | **No** (`gtin13: null`) | HTML de búsqueda y ficha con `__NEXT_DATA__` (JSON incrustado) | `httpx` + JSON; atributos |

## 2. Evidencias

### 2.1 Alkosto y Ktronix
- `https://www.alkosto.com/p/195951409481` redirige a `/iphone-18-pro-max-1tb-5g-borgona/p/195951409481` (HTTP 200). En Ktronix pasa lo mismo.
- El precio aparece en `itemprop="price" content="4199010.0"` y la disponibilidad en `InStock`/`OutOfStock`.
- `robots.txt` prohíbe `/search/` y `*?q=`. No hace falta buscar: basta con recorrer los EAN del maestro.

### 2.2 Jumbo y Olímpica (VTEX)
Consulta: `/api/catalog_system/pub/products/search?ft=iphone`. Cada producto trae el EAN, la referencia, el vendedor, el precio, el precio de lista y el stock.

| | Jumbo | Olímpica | Éxito* |
|---|---|---|---|
| Ofertas iPhone (todas) | 204 | 450 | 1.789 |
| EAN distintos | 105 | 220 | 499 |
| EAN presentes en el maestro | 10 | 15 | 18 |
| Ofertas **del vendedor propio, nuevas y con stock** | **10** | **0** | **4** |

\* La medición de Éxito se hizo antes de revisar su robots.txt. Desde ese momento no se usa su API.

Hallazgos:
1. **La mayoría de las ofertas de iPhone son de vendedores externos del marketplace** (celucambio, quiero mac, mobilecomercial, Estilo Net…), y muchas son equipos reacondicionados. El vendedor `1` (la cadena) aparece en casi todos los ítems, pero con precio 0 y stock 0. Por eso el filtro correcto es **vendedor propio + stock > 0 + título sin "reacondicionado"**.
2. **Un equipo reacondicionado puede llevar el UPC original de Apple** (por ejemplo, `0194253119524` iPhone 13 Pro reacondicionado en Olímpica). El EAN por sí solo no basta para excluir reacondicionados: también hay que filtrar por título y vendedor.
3. **Formato del EAN:** las tiendas publican el mismo código con 12 o con 13 dígitos (`195949035913` frente a `0195949035913`). Se normaliza a GTIN-14.
4. Las 14 ofertas propias encontradas (Jumbo y Éxito) tienen todas su EAN en el maestro (14 de 14).

### 2.3 Falabella
- La búsqueda `iphone 17` devuelve 56 resultados en `__NEXT_DATA__`, con vendedor, precios (normal, internet y tarjeta CMR) y SKU propio de Falabella.
- La ficha `/product/73417515/...` trae `gtin13: null`. Las especificaciones incluyen "Nombre comercial" (Iphone 17), "Capacidad de almacenamiento" (256 GB), "Color" y "Condición del producto" (Nuevo), pero **ni EAN ni referencia del fabricante**.
- El vendedor propio es `FALABELLA_COLOMBIA`. También venden Homecenter y terceros.
- La primera petición sin cabeceras `Accept` devolvió una respuesta vacía; con cabeceras de navegador respondió normal.

### 2.4 Éxito
- `robots.txt`: `Disallow: /api/`, `/s?`, `/*?*facets=`, `/*?*sort=`.
- El sitemap no incluye fichas de producto. Sí incluye la página de marca `https://www.exito.com/apple`, que llega sin productos en el HTML: los carga el navegador.
- Conclusión: Éxito se captura con Playwright, renderizando páginas permitidas como lo haría un visitante.

## 3. Implicaciones para el diseño
- La regla de emparejamiento necesita una alternativa por **atributos normalizados** (modelo + capacidad + color), porque Falabella no expone EAN ni referencia del fabricante.
- El volumen de productos comparables es **bajo** (decenas de SKU, no cientos). El análisis se centrará en los modelos vigentes que venden al menos dos cadenas.
- Olímpica no tenía iPhone propios con stock el día de la prueba. Se mantiene como fuente y se registrarán sus resultados aunque salgan vacíos.

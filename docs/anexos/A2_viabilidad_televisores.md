# Anexo A2 — Cambio de categoría: de iPhone a Televisores

**Fecha:** 13 de octubre de 2026

## 1. Motivo del cambio
La prueba del Anexo A1 mostró que las cadenas venden muy pocos iPhone directamente: 10 en Jumbo, 4 en Éxito y 0 en Olímpica (nuevos y con stock). Con esa muestra no se podía validar el emparejamiento entre cadenas ni analizar brechas de precio. El equipo decidió cambiar a la categoría **Televisores** y **descartar Falabella**, porque no publica ni EAN ni referencia del fabricante.

## 2. Maestro disponible
La hoja `DIM_PRODUCTO` del archivo `DataFeed-30-09-2026.xlsx` (División *Video*, Línea *Tv*) tiene 4.659 registros. Con tecnologías vigentes (LED, QLED/QNED, OLED, Mini LED), GTIN válido y sin combos quedan **2.387 televisores en alcance**. La mayoría son LG (643), Samsung (617), Kalley, Hyundai, Challenger, Sony, TCL y Panasonic.

## 3. Prueba en las cadenas (13-oct-2026)

**Jumbo y Olímpica:** API pública de catálogo VTEX, búsqueda "televisor", solo el vendedor propio con stock y precio > 0.

> **Nota (Etapa 2):** la búsqueda paginada de Olímpica (`?ft=…&_from=…&_to=…`) usa `&`, y su robots.txt prohíbe toda URL con `&` o `%`. La regla se notó en la Etapa 2. Desde entonces, Olímpica se descubre por su sitemap y la API se consulta por ruta, sin parámetros (ver `docs/02_Etapa2_Extraccion.md`, sección 3).

| | Jumbo | Olímpica |
|---|---|---|
| Televisores propios con stock | **59** | **67** |
| Emparejados por EAN con el maestro | 44 | 44 |
| Emparejados por referencia del fabricante | 1 | 0 |
| No emparejados | 14 | 23 |

Los no emparejados son, casi todos, **marcas que Alkosto no vende**: Caixun, Hisense y Olimpo (marca propia de Olímpica). No son errores de la regla. Varios de ellos coinciden entre Jumbo y Olímpica por EAN.

**Alkosto y Ktronix:** se consultó la ficha `/p/{EAN}` de los 91 EAN propios de Jumbo y Olímpica.

| | Alkosto | Ktronix |
|---|---|---|
| Fichas encontradas | 45 | 46 |
| Con disponibilidad `InStock` | 36 | 37 |

**Coincidencia entre cadenas** (sin Éxito, que se medirá con Playwright en la Etapa 2):
- 20 EAN están a la vez en Jumbo y en Olímpica.
- **52 de los 91 EAN están en dos o más cadenas**, y 14 en las tres.

Con iPhone, la cifra comparable era de apenas unos pocos productos.

**Éxito:** el sitemap expone `https://www.exito.com/tecnologia/televisores` y una página por marca (`/televisores-lg`, `/televisores-samsung`…). Son páginas permitidas por robots.txt y se capturarán con Playwright.

## 4. Consecuencias para el diseño
1. **Vuelve a valer el criterio original del planteamiento:** EAN y, como alternativa, **referencia del fabricante**. Los títulos de las tiendas y las descripciones del maestro traen la referencia (por ejemplo, `65TG380`, `55QNED80SRA`). La clave alternativa es `marca | pulgadas | referencia normalizada`; las pulgadas son necesarias porque los fabricantes repiten la referencia de la serie en todos los tamaños.
2. **El universo de productos es la unión de lo que venden las cuatro cadenas**, no solo el catálogo de Alkosto. El maestro de Alkosto enriquece la dimensión de producto, pero un Caixun que venden Jumbo y Olímpica también se compara.
3. Se excluyen los **combos** (TV + barra de sonido, "Combo Televisor…"), porque su precio no es comparable.

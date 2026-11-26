-- Etapa 4. Se ejecuta en `tfm_oro`. Controles del modelo estrella (solo lectura).

-- 1. Filas por vista
SELECT 'dim_producto' AS vista, COUNT_BIG(*) AS filas FROM oro.dim_producto
UNION ALL SELECT 'dim_tienda', COUNT_BIG(*) FROM oro.dim_tienda
UNION ALL SELECT 'dim_calendario', COUNT_BIG(*) FROM oro.dim_calendario
UNION ALL SELECT 'fact_precio_diario', COUNT_BIG(*) FROM oro.fact_precio_diario
UNION ALL SELECT 'fact_ejecucion', COUNT_BIG(*) FROM oro.fact_ejecucion
UNION ALL SELECT 'kpi_brecha_precio', COUNT_BIG(*) FROM oro.kpi_brecha_precio
UNION ALL SELECT 'kpi_calidad_captura', COUNT_BIG(*) FROM oro.kpi_calidad_captura;
GO

-- 2. Claves únicas (RNF-04: 0 duplicados en el historial diario) y claves de dimensión
SELECT 'fact_precio_diario (fecha, producto, tienda)' AS control, COUNT_BIG(*) AS duplicados
FROM (SELECT fecha_key, producto_key, tienda_key FROM oro.fact_precio_diario
      GROUP BY fecha_key, producto_key, tienda_key HAVING COUNT(*) > 1) d
UNION ALL
SELECT 'dim_producto (producto_key)', COUNT_BIG(*)
FROM (SELECT producto_key FROM oro.dim_producto GROUP BY producto_key HAVING COUNT(*) > 1) d
UNION ALL
SELECT 'dim_calendario (fecha_key)', COUNT_BIG(*)
FROM (SELECT fecha_key FROM oro.dim_calendario GROUP BY fecha_key HAVING COUNT(*) > 1) d;
GO

-- 3. Integridad referencial: filas de hechos sin su dimensión (deben ser 0)
SELECT 'fact_precio_diario -> dim_producto' AS relacion, COUNT_BIG(*) AS huerfanas
FROM oro.fact_precio_diario f LEFT JOIN oro.dim_producto p ON p.producto_key = f.producto_key
WHERE p.producto_key IS NULL
UNION ALL
SELECT 'fact_precio_diario -> dim_tienda', COUNT_BIG(*)
FROM oro.fact_precio_diario f LEFT JOIN oro.dim_tienda t ON t.tienda_key = f.tienda_key WHERE t.tienda_key IS NULL
UNION ALL
SELECT 'fact_precio_diario -> dim_calendario', COUNT_BIG(*)
FROM oro.fact_precio_diario f LEFT JOIN oro.dim_calendario c ON c.fecha_key = f.fecha_key WHERE c.fecha_key IS NULL
UNION ALL
SELECT 'kpi_brecha_precio -> dim_producto', COUNT_BIG(*)
FROM oro.kpi_brecha_precio k LEFT JOIN oro.dim_producto p ON p.producto_key = k.producto_key
WHERE p.producto_key IS NULL
UNION ALL
SELECT 'fact_ejecucion -> dim_tienda', COUNT_BIG(*)
FROM oro.fact_ejecucion e LEFT JOIN oro.dim_tienda t ON t.tienda_key = e.tienda_key WHERE t.tienda_key IS NULL;
GO

-- 4. Resumen diario: ofertas, emparejamiento (meta >= 80 %) y brecha máxima entre cadenas
SELECT c.fecha, f.ofertas, k.emparejadas, k.ofertas_con_stock,
       CAST(1.0 * k.emparejadas / NULLIF(k.ofertas_con_stock, 0) AS decimal(9, 4)) AS emparejamiento,
       b.productos_comparados, b.brecha_max
FROM oro.dim_calendario c
LEFT JOIN (SELECT fecha_key, COUNT_BIG(*) AS ofertas FROM oro.fact_precio_diario GROUP BY fecha_key) f
       ON f.fecha_key = c.fecha_key
LEFT JOIN (SELECT fecha_key, SUM(emparejadas) AS emparejadas, SUM(ofertas_con_stock) AS ofertas_con_stock
           FROM oro.kpi_calidad_captura GROUP BY fecha_key) k ON k.fecha_key = c.fecha_key
LEFT JOIN (SELECT fecha_key, COUNT_BIG(*) AS productos_comparados, MAX(brecha_pct) AS brecha_max
           FROM oro.kpi_brecha_precio GROUP BY fecha_key) b ON b.fecha_key = c.fecha_key
ORDER BY c.fecha;
GO

-- 5. Textos con tildes (la collation UTF-8 debe conservarlas)
SELECT tienda_key, sitio, tienda, cadena FROM oro.dim_tienda ORDER BY tienda_key;
GO

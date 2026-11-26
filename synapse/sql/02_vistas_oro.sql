-- Etapa 4. Se ejecuta en `tfm_oro`. Modelo estrella (constelación) sobre las tablas Delta de oro/.
--
--   dimensiones  oro.dim_producto, oro.dim_tienda, oro.dim_calendario
--   hechos       oro.fact_precio_diario (producto × tienda × día), oro.fact_ejecucion (corrida × sitio)
--   indicadores  oro.kpi_brecha_precio (producto × día), oro.kpi_calidad_captura (tienda × día)
--
-- Cada vista lee la versión vigente de la tabla Delta (FORMAT = 'DELTA'), así que no hay que
-- volver a crearlas cuando corre el medallón. Los tipos se fijan en WITH: así no dependen de la
-- inferencia y los textos quedan con largo acotado (mejores planes y menos memoria en Power BI).
-- Los largos tienen holgura frente a los máximos observados el 16-oct (comentario al lado).
-- Las relaciones son: fecha_key -> dim_calendario, producto_key -> dim_producto, tienda_key -> dim_tienda.

CREATE OR ALTER VIEW oro.dim_producto AS
SELECT *
FROM OPENROWSET(BULK 'dimensiones/dim_producto/', DATA_SOURCE = 'ds_oro', FORMAT = 'DELTA')
WITH (
    producto_key      varchar(60),    -- 14: GTIN-14, o sitio:sku si no se emparejó
    gtin14            varchar(14),
    descripcion       varchar(400),   -- 115
    marca             varchar(60),    -- 10
    pulgadas          int,
    referencia        varchar(80),    -- 19
    tecnologia        varchar(40),    -- 8
    resolucion        varchar(20),    -- 3
    en_maestro        bit,
    origen_atributos  varchar(20),    -- 7: MAESTRO o TIENDA
    tiene_gtin        bit,
    rango_pulgadas    varchar(20)     -- 9
) AS t;
GO

CREATE OR ALTER VIEW oro.dim_tienda AS
SELECT *
FROM OPENROWSET(BULK 'dimensiones/dim_tienda/', DATA_SOURCE = 'ds_oro', FORMAT = 'DELTA')
WITH (
    tienda_key  int,
    sitio       varchar(20),    -- 8
    tienda      varchar(40),    -- 8
    cadena      varchar(100)    -- 40
) AS t;
GO

CREATE OR ALTER VIEW oro.dim_calendario AS
SELECT *
FROM OPENROWSET(BULK 'dimensiones/dim_calendario/', DATA_SOURCE = 'ds_oro', FORMAT = 'DELTA')
WITH (
    fecha_key         int,
    fecha             date,
    anio              int,
    mes               int,
    nombre_mes        varchar(12),
    anio_mes          char(7),
    semana_iso        int,
    inicio_semana     date,
    dia_semana        int,            -- 1 = lunes … 7 = domingo
    nombre_dia        varchar(12),
    es_fin_de_semana  bit
) AS t;
GO

CREATE OR ALTER VIEW oro.fact_precio_diario AS
SELECT fecha_key, producto_key, tienda_key, precio_lista, precio_venta,
       CAST(descuento_pct AS decimal(9, 4)) AS descuento_pct,
       disponible, stock, metodo_emparejamiento, fecha_captura_utc, id_ejecucion, ruta_bronze, url,
       motivos_atipico, precio_referencia_30d, dias_observados_30d,
       CAST(descuento_respaldado AS decimal(9, 4)) AS descuento_respaldado, descuento_sin_respaldo
FROM OPENROWSET(BULK 'hechos/fact_precio_diario/', DATA_SOURCE = 'ds_oro', FORMAT = 'DELTA')
WITH (
    fecha_key              int,
    producto_key           varchar(60),
    tienda_key             int,
    precio_lista           bigint,
    precio_venta           bigint,
    descuento_pct          float,
    disponible             bit,
    stock                  bigint,
    metodo_emparejamiento  varchar(20),    -- EAN, REFERENCIA o SIN_EMPAREJAR
    fecha_captura_utc      datetime2(6),
    id_ejecucion           varchar(40),    -- 22
    ruta_bronze            varchar(400),   -- 161: evidencia en bronce (RNF-05)
    url                    varchar(800),   -- 119
    motivos_atipico        varchar(200),   -- control de calidad (Etapa 6): motivos separados por coma, o NULL
    -- Detector de descuentos sin respaldo (src/medallon/detector.py; NULL si la oferta no es evaluable)
    precio_referencia_30d  bigint,
    dias_observados_30d    int,
    descuento_respaldado   float,
    descuento_sin_respaldo bit
) AS t;
GO

-- Eventos comerciales de las alertas y el resumen diario (src/medallon/eventos.py)
CREATE OR ALTER VIEW oro.fact_evento_comercial AS
SELECT fecha_key, tipo_evento, producto_key, tienda_key, precio_anterior, precio_actual,
       CAST(variacion_pct AS decimal(9, 4)) AS variacion_pct, precio_lista,
       CAST(descuento_anunciado AS decimal(9, 4)) AS descuento_anunciado,
       CAST(descuento_respaldado AS decimal(9, 4)) AS descuento_respaldado,
       precio_referencia_30d, dias_observados_30d, fecha_anterior_key, dias_desde_anterior, revisar_atipico,
       url, ruta_bronze
FROM OPENROWSET(BULK 'hechos/fact_evento_comercial/', DATA_SOURCE = 'ds_oro', FORMAT = 'DELTA')
WITH (
    fecha_key              int,
    tipo_evento            varchar(30),    -- CAMBIO_PRECIO, AGOTADO, FIN_PROMOCION, PRODUCTO_NUEVO, DESCUENTO_SIN_RESPALDO
    producto_key           varchar(60),
    tienda_key             int,
    precio_anterior        bigint,
    precio_actual          bigint,
    variacion_pct          float,
    precio_lista           bigint,
    descuento_anunciado    float,
    descuento_respaldado   float,
    precio_referencia_30d  bigint,
    dias_observados_30d    int,
    fecha_anterior_key     int,
    dias_desde_anterior    int,
    revisar_atipico        bit,
    url                    varchar(800),
    ruta_bronze            varchar(400)
) AS t;
GO

CREATE OR ALTER VIEW oro.fact_ejecucion AS
SELECT *
FROM OPENROWSET(BULK 'hechos/fact_ejecucion/', DATA_SOURCE = 'ds_oro', FORMAT = 'DELTA')
WITH (
    fecha_key       int,
    tienda_key      int,
    id_ejecucion    varchar(40),
    modo            varchar(20),     -- completo o seguimiento
    inicio          datetime2(6),
    fin             datetime2(6),
    duracion_s      float,
    descubiertos    int,
    consultados     int,
    ok              int,
    sin_stock       int,
    no_encontrados  int,
    errores         int,
    bloqueados      int,
    registros       int,
    en_alcance      int,
    estado          varchar(20),     -- EXITOSA, PARCIAL o FALLIDA
    mensaje         varchar(1000)    -- 19
) AS t;
GO

CREATE OR ALTER VIEW oro.kpi_brecha_precio AS
SELECT fecha_key, producto_key, n_cadenas, precio_min, precio_max,
       CAST(precio_promedio AS bigint) AS precio_promedio, cadena_mas_barata, brecha_abs,
       CAST(brecha_pct AS decimal(9, 4)) AS brecha_pct
FROM OPENROWSET(BULK 'kpis/kpi_brecha_precio/', DATA_SOURCE = 'ds_oro', FORMAT = 'DELTA')
WITH (
    fecha_key          int,
    producto_key       varchar(60),
    n_cadenas          bigint,
    precio_min         bigint,
    precio_max         bigint,
    precio_promedio    float,
    cadena_mas_barata  varchar(100),
    brecha_abs         bigint,
    brecha_pct         float
) AS t;
GO

CREATE OR ALTER VIEW oro.kpi_calidad_captura AS
SELECT fecha_key, tienda_key, id_ejecucion, registros, registros_con_datos, tv_en_alcance,
       CAST(completitud_pct AS decimal(9, 4)) AS completitud_pct,
       ofertas_con_stock, por_ean, por_referencia, sin_emparejar, emparejadas,
       CAST(emparejamiento_pct AS decimal(9, 4)) AS emparejamiento_pct
FROM OPENROWSET(BULK 'kpis/kpi_calidad_captura/', DATA_SOURCE = 'ds_oro', FORMAT = 'DELTA')
WITH (
    tienda_key           int,
    id_ejecucion         varchar(40),
    registros            bigint,
    registros_con_datos  bigint,
    tv_en_alcance        bigint,
    completitud_pct      float,
    ofertas_con_stock    bigint,
    por_ean              bigint,
    por_referencia       bigint,
    sin_emparejar        bigint,
    emparejadas          bigint,
    emparejamiento_pct   float,
    fecha_key            int
) AS t;
GO

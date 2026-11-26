-- Etapa 4. Se ejecuta en `master` del endpoint serverless (syn-tfm-webscraping-ondemand).
-- Base de datos de las vistas del modelo estrella. La collation UTF-8 evita la conversión
-- de los textos de Parquet (UTF-8) y mantiene tildes y eñes; CI = sin distinguir mayúsculas.
IF DB_ID('tfm_oro') IS NULL
    CREATE DATABASE tfm_oro COLLATE Latin1_General_100_CI_AS_SC_UTF8;
GO

-- Tope de datos procesados por día en todo el endpoint (decisión del equipo, 16-oct): si una consulta
-- o una actualización mal configurada lo supera, el endpoint rechaza las consultas hasta el día
-- siguiente. 1 TB son unos USD 5; el uso normal es de decenas de MB.
EXEC sp_set_data_processed_limit @type = N'daily', @limit_tb = 1;
GO

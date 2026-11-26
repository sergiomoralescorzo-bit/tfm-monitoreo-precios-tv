-- Etapa 4. Se ejecuta en `tfm_oro`.
-- Acceso al lago con la identidad administrada de Synapse (ya tiene Storage Blob Data Contributor
-- sobre sttfmwebscraping). Así quien consulta las vistas no necesita permisos sobre el lago.
-- La clave maestra solo protege la credencial (que no guarda secretos); el script de despliegue
-- reemplaza $(CLAVE_MAESTRA) por un valor aleatorio que no se guarda en ningún lado.
IF NOT EXISTS (SELECT 1 FROM sys.symmetric_keys WHERE name = '##MS_DatabaseMasterKey##')
    CREATE MASTER KEY ENCRYPTION BY PASSWORD = '$(CLAVE_MAESTRA)';
GO

IF NOT EXISTS (SELECT 1 FROM sys.database_scoped_credentials WHERE name = 'cred_identidad_synapse')
    CREATE DATABASE SCOPED CREDENTIAL cred_identidad_synapse WITH IDENTITY = 'Managed Identity';
GO

IF NOT EXISTS (SELECT 1 FROM sys.external_data_sources WHERE name = 'ds_oro')
    CREATE EXTERNAL DATA SOURCE ds_oro WITH (
        LOCATION = 'https://sttfmwebscraping.dfs.core.windows.net/datalake-tfm/oro',
        CREDENTIAL = cred_identidad_synapse);
GO

IF SCHEMA_ID('oro') IS NULL
    EXEC ('CREATE SCHEMA oro');
GO

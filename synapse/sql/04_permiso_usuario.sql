-- Etapa 4. Se ejecuta en `tfm_oro`, una vez por usuario ($(USUARIO) = correo de Entra ID).
-- Lectura de las vistas (Power BI) sin ser administrador de Synapse ni tener permisos sobre el lago:
-- el usuario usa la credencial con la identidad de Synapse (REFERENCES) para que las vistas lean oro/.
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'$(USUARIO)')
    CREATE USER [$(USUARIO)] FROM EXTERNAL PROVIDER;
GO

ALTER ROLE db_datareader ADD MEMBER [$(USUARIO)];
GO

GRANT REFERENCES ON DATABASE SCOPED CREDENTIAL::cred_identidad_synapse TO [$(USUARIO)];
GO

SELECT p.name AS usuario, p.type_desc AS tipo, r.name AS rol
FROM sys.database_principals p
LEFT JOIN sys.database_role_members m ON m.member_principal_id = p.principal_id
LEFT JOIN sys.database_principals r ON r.principal_id = m.role_principal_id
WHERE p.name = N'$(USUARIO)';
GO

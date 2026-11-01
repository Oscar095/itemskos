/* ============================================================================
   Migracion 02 — vendedores, tracking de etapas, adjuntos y observaciones
   ----------------------------------------------------------------------------
   Se aplica sobre el esquema `items` de kx_ecommerce (ver
   plataforma_web_schema.sql). Cubre:

     2. Tabla de vendedores con correo y estado (para dar de baja)
     3. `titulo` deja de ser obligatorio (se quita del formulario)
     4. Adjuntos: metadatos aqui, archivo en el Datalake (datalakekos)
     5. Observaciones y tracking por etapa del proceso
   ============================================================================ */

/* ---------------------------------------------------------------- vendedores */
CREATE TABLE items.vendedores (
    id                INT IDENTITY(1,1) PRIMARY KEY,
    email             NVARCHAR(200) NOT NULL,
    nombre            NVARCHAR(200) NOT NULL,
    activo            BIT           NOT NULL CONSTRAINT DF_vend_activo DEFAULT 1,
    -- Ultima vez que aparecio como Vendedor en la lista de SharePoint. Es el
    -- dato con el que se decide a quien dar de baja, no una suposicion.
    ultima_actividad  DATE          NULL,
    fecha_creado      DATETIME2     NOT NULL CONSTRAINT DF_vend_fcreado DEFAULT SYSUTCDATETIME()
);
CREATE UNIQUE INDEX IX_vendedores_email ON items.vendedores(email);
GO

/* ------------------------------------------------------- etapas del proceso */
-- Catalogo fijo y ordenado. El `orden` es lo que permite saber "hasta donde
-- va" una solicitud sin tener que interpretar nombres.
CREATE TABLE items.etapas (
    id      INT           NOT NULL PRIMARY KEY,
    nombre  NVARCHAR(60)  NOT NULL,
    orden   INT           NOT NULL
);
GO

-- OJO: el prefijo N es obligatorio en literales de columnas NVARCHAR. Sin el,
-- SQL Server convierte la cadena al codepage por defecto y las tildes/ñ se
-- corrompen. Ademas, este archivo se debe leer como UTF-8 al ejecutarlo:
-- en PowerShell 5.1, Get-Content sin -Encoding UTF8 lo lee como ANSI y guarda
-- mojibake ("Diseño" -> "DiseÃ±o"). Las dos cosas juntas ya rompieron esta
-- tabla una vez.
INSERT INTO items.etapas (id, nombre, orden) VALUES
    (1, N'Solicitud de Diseño',  1),
    (2, N'Aprobación de Diseño', 2),
    (3, N'Creación de item',     3),
    (4, N'Digitación de Pedido', 4),
    (5, N'Llegada de Planchas',  5),
    (6, N'En producción',        6);
GO

/* ------------------------------------------------------ seguimiento (tracking) */
-- Un registro por evento. El historial completo de la solicitud sale de aqui;
-- `solicitudes.etapa_actual_id` es solo un espejo de la ultima, para que el
-- listado no tenga que agregar por cada fila.
CREATE TABLE items.seguimiento (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    solicitud_id    INT           NOT NULL REFERENCES items.solicitudes(id),
    etapa_id        INT           NOT NULL REFERENCES items.etapas(id),
    observacion     NVARCHAR(MAX) NULL,
    usuario_email   NVARCHAR(200) NULL,
    usuario_nombre  NVARCHAR(200) NULL,
    fecha           DATETIME2     NOT NULL CONSTRAINT DF_seg_fecha DEFAULT SYSUTCDATETIME()
);
CREATE INDEX IX_seguimiento_solicitud ON items.seguimiento(solicitud_id, fecha);
GO

/* ----------------------------------------------------------------- adjuntos */
-- El archivo NO se guarda en SQL: va al Datalake (cuenta datalakekos) y aqui
-- solo queda la ruta y los metadatos.
CREATE TABLE items.adjuntos (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    solicitud_id    INT           NOT NULL REFERENCES items.solicitudes(id),
    nombre_archivo  NVARCHAR(300) NOT NULL,
    tipo_contenido  NVARCHAR(120) NULL,
    tamano_bytes    BIGINT        NULL,
    blob_path       NVARCHAR(500) NOT NULL,   -- ruta dentro del contenedor
    subido_por      NVARCHAR(200) NULL,
    fecha           DATETIME2     NOT NULL CONSTRAINT DF_adj_fecha DEFAULT SYSUTCDATETIME()
);
CREATE INDEX IX_adjuntos_solicitud ON items.adjuntos(solicitud_id);
GO

/* ------------------------------------------------- cambios en solicitudes */
-- El titulo era texto libre que se usaba para adivinar el item base. Ahora que
-- el item base se elige del catalogo de Siesa, dejo de ser necesario: se vuelve
-- opcional en vez de borrarlo, para no perder el dato de las filas migradas.
ALTER TABLE items.solicitudes ALTER COLUMN titulo NVARCHAR(200) NULL;
GO

ALTER TABLE items.solicitudes ADD
    vendedor_id      INT           NULL REFERENCES items.vendedores(id),
    etapa_actual_id  INT           NULL REFERENCES items.etapas(id),
    observaciones    NVARCHAR(MAX) NULL;   -- nota inicial al crear la solicitud
GO

CREATE INDEX IX_solicitudes_etapa ON items.solicitudes(etapa_actual_id);
GO

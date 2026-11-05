/* ============================================================================
   Esquema `items` - plataforma web de creacion de items-extension en Siesa
   ----------------------------------------------------------------------------
   DESTINO REAL (verificado conectandose, 2026-09-03):
     Servidor : myappskos.database.windows.net   (Azure SQL, NO el server de Siesa)
     Base     : kx_ecommerce                      (existente, 105 tablas)
     Usuario  : kos -> mapea a dbo, permiso CONTROL

   kx_ecommerce ya aloja 5 aplicaciones y usa la convencion de UN ESQUEMA POR
   APLICACION (calidad, evaluaciones, facturas, importacion, y dbo para
   e-commerce/PQRS). Por eso esto NO crea una base nueva: crea el esquema
   `items` dentro de kx_ecommerce, siguiendo esa misma convencion.

   Estructura de la lista de SharePoint que reemplaza: verificada via REST API.
     Sitio : https://koscolombiacali.sharepoint.com/sites/INTRANETKOS
     Lista : "PLATAFORMA DE ITEMS Y PEDIDO DE PLANCHAS"
     GUID  : c0b3e740-d705-4f48-9c6a-d8e88082bae0
   ============================================================================ */

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'items')
    EXEC('CREATE SCHEMA items');
GO

/* ----------------------------------------------------------------------------
   1) CACHE de los catalogos de Siesa (Ext1/marca, Ext2/calibre, items base).

   koscolombia_Items_odoo_crm tarda ~350 segundos contra Siesa (medido). Un
   dropdown no puede esperar eso: un job refresca estas tablas y la web lee
   siempre de aqui. Los clientes NO se cachean aqui — ya existen en
   dbo.PQRS_ClientesSiesa, ver seccion 2.
   ---------------------------------------------------------------------------- */

CREATE TABLE items.cat_marcas (              -- koscolombia_ext1_odoo (Ext1 / MK)
    id            NVARCHAR(20)   NOT NULL PRIMARY KEY,   -- f117_id (trim)
    descripcion   NVARCHAR(200)  NOT NULL,                -- f117_descripcion
    fecha_siesa   DATETIME2      NULL,                    -- f117_ts; desempata duplicados (mas reciente gana): EMA, 20 DE JULIO, CORRAL VAINILLA tienen 2+ codigos con el mismo nombre
    actualizado   DATETIME2      NOT NULL CONSTRAINT DF_cat_marcas_act DEFAULT SYSUTCDATETIME()
);
CREATE INDEX IX_cat_marcas_descripcion ON items.cat_marcas(descripcion);

CREATE TABLE items.cat_calibres (            -- koscolombia_ext2_Odoo (Ext2 / CK)
    id            NVARCHAR(20)   NOT NULL PRIMARY KEY,   -- f119_id
    descripcion   NVARCHAR(200)  NOT NULL,                -- f119_descripcion
    actualizado   DATETIME2      NOT NULL CONSTRAINT DF_cat_calibres_act DEFAULT SYSUTCDATETIME()
);

CREATE TABLE items.cat_items_base (          -- una fila por REFERENCIA unica (187 al momento de escribir esto)
    referencia    NVARCHAR(50)   NOT NULL PRIMARY KEY,   -- f120_referencia (trim)
    descripcion   NVARCHAR(200)  NOT NULL,
    tipo_item     INT            NULL,
    actualizado   DATETIME2      NOT NULL CONSTRAINT DF_cat_items_base_act DEFAULT SYSUTCDATETIME()
);

CREATE TABLE items.cat_extensiones_existentes (   -- koscolombia_Items_odoo_crm completa (7023 SKUs)
    sku_siesa       INT            NOT NULL PRIMARY KEY,  -- f121_rowid
    referencia      NVARCHAR(50)   NOT NULL REFERENCES items.cat_items_base(referencia),
    marca_id        NVARCHAR(20)   NULL,
    marca_desc      NVARCHAR(200)  NULL,
    calibre_id      NVARCHAR(20)   NULL,
    estado_ext      NVARCHAR(5)    NULL,                   -- f121_ind_estado
    costo_prom_uni  DECIMAL(18,4)  NULL,                    -- NULL = sin movimientos aun (normal en items recien creados)
    actualizado     DATETIME2      NOT NULL CONSTRAINT DF_cat_ext_act DEFAULT SYSUTCDATETIME()
);
-- Hace instantanea la deteccion de duplicados (equivalente a Catalogo.existentes en catalogo.py)
CREATE UNIQUE INDEX IX_cat_ext_combo ON items.cat_extensiones_existentes(referencia, marca_id, calibre_id);


/* ----------------------------------------------------------------------------
   2) SOLICITUDES: reemplaza la lista de SharePoint.

   El punto de todo el proyecto: Marca, Calibre, Item base y Cliente dejan de
   ser texto libre y pasan a ser FK contra datos reales. Ahi es donde nacian
   los typos que bloqueaban la creacion ("VIBER CAFE" vs "VIBES CAFE",
   "JESSIZA LOZANO" vs "JESSICA LOZANO", "MUSETTI" vs "MUSETI").

   Cliente apunta a dbo.PQRS_ClientesSiesa (1097 clientes sincronizados desde
   Siesa) — se reutiliza en vez de duplicar.
   ---------------------------------------------------------------------------- */

CREATE TABLE items.solicitudes (
    id                    INT IDENTITY(1,1) PRIMARY KEY,
    sharepoint_item_id    INT            NULL,             -- Id original; solo en filas migradas

    titulo                NVARCHAR(200)  NOT NULL,         -- Title

    -- Marca: FK a Ext1. NULL = el usuario pidio una marca que aun no existe en
    -- Siesa; queda el texto en marca_nueva_texto y la solicitud espera a que
    -- alguien la cree en Ext1 (hoy eso se reporta en marcas_faltantes.txt).
    marca_id              NVARCHAR(20)   NULL REFERENCES items.cat_marcas(id),
    marca_nueva_texto     NVARCHAR(200)  NULL,

    -- Cliente: FK a la tabla que ya mantiene PQRS. cliente_texto conserva el
    -- valor original de SharePoint — imprescindible para migrar el historico,
    -- donde muchos nombres no van a casar exacto contra los 1097 sincronizados.
    cliente_id            INT            NULL REFERENCES dbo.PQRS_ClientesSiesa(Id),
    cliente_texto         NVARCHAR(200)  NULL,

    calibre_id            NVARCHAR(20)   NULL REFERENCES items.cat_calibres(id),
    tipo_material         NVARCHAR(20)   NOT NULL,         -- Choice: P1|P2|SP|PEFC|Bio Natura|EARTHPACK|Kraft Corrugado
    cantidad              INT            NOT NULL,

    -- Vendedor es un People field en SharePoint (no texto): se guarda el correo
    -- como llave estable, que es lo que amarra esto a login corporativo (Entra ID).
    vendedor_email        NVARCHAR(200)  NOT NULL,
    vendedor_nombre       NVARCHAR(200)  NOT NULL,

    item_base_referencia  NVARCHAR(50)   NULL REFERENCES items.cat_items_base(referencia),
    estado                NVARCHAR(20)   NOT NULL CONSTRAINT DF_solicitudes_estado DEFAULT 'Pendiente',  -- Pendiente | Creado | Bloqueado
    motivo_bloqueo        NVARCHAR(400)  NULL,             -- equivalente a la columna "motivo" de revision_manual.csv

    pedido_unoe           NVARCHAR(20)   NULL,             -- Choice: Por Subir | Montado
    op_entregada_diseno   DATETIME2      NULL,             -- OJO: es DateTime, no booleano
    cab_plancha           NVARCHAR(100)  NULL,
    planchas              NVARCHAR(20)   NULL,             -- Choice: Pendiente | En Planta | En Proceso (columna DISTINTA de `estado`, no confundir)
    fecha_planchas        DATETIME2      NULL,

    -- Estos 3 no estaban en las 17 columnas que traia el Excel: describen un
    -- flujo de aprobacion de diseño que el proceso actual ignora por completo.
    tipo_solicitud        NVARCHAR(200)  NULL,             -- MultiChoice como CSV: Diseño Nuevo|Cambio de Arte|Destruir Planchas|Solicitud de Arte|Cambio de Calibre
    aprobacion            BIT            NOT NULL CONSTRAINT DF_solicitudes_aprob DEFAULT 0,
    disenador             NVARCHAR(100)  NULL,             -- Choice: Cristhian Santana | Karol Michelle | Diana Nieto

    creado_por            NVARCHAR(200)  NULL,
    modificado_por        NVARCHAR(200)  NULL,
    fecha_creado          DATETIME2      NOT NULL CONSTRAINT DF_solicitudes_fcreado DEFAULT SYSUTCDATETIME(),
    fecha_modificado      DATETIME2      NULL,

    sku_creado            INT            NULL,             -- SKU_SIESA una vez creado
    origen                NVARCHAR(20)   NOT NULL CONSTRAINT DF_solicitudes_origen DEFAULT 'web'  -- 'web' | 'migracion_sharepoint'
);
CREATE INDEX IX_solicitudes_estado ON items.solicitudes(estado);
CREATE UNIQUE INDEX IX_solicitudes_sharepoint_id
    ON items.solicitudes(sharepoint_item_id) WHERE sharepoint_item_id IS NOT NULL;


/* ----------------------------------------------------------------------------
   3) AUDITORIA de cada llamada al conector de creacion de Siesa.
      Reemplaza salida/log_creacion.csv (que hoy vive suelto en el disco de
      quien corre el script, y que ya se rompio una vez por tenerlo abierto
      en Excel mientras el proceso escribia).
   ---------------------------------------------------------------------------- */

CREATE TABLE items.log_creacion (
    id               INT IDENTITY(1,1) PRIMARY KEY,
    solicitud_id     INT            NOT NULL REFERENCES items.solicitudes(id),
    fecha            DATETIME2      NOT NULL CONSTRAINT DF_log_fecha DEFAULT SYSUTCDATETIME(),
    usuario_web      NVARCHAR(200)  NULL,
    http_status      INT            NULL,
    codigo_conector  INT            NULL,
    mensaje          NVARCHAR(MAX)  NULL,
    sku_creado       INT            NULL,
    payload_enviado  NVARCHAR(MAX)  NULL                    -- JSON exacto enviado, para auditar y reproducir
);
GO

-- Altas de marca en Ext1 desde la web (conector "Creacion Extensiones").
-- Tabla aparte de log_creacion porque la marca se crea ANTES de que exista
-- la solicitud: no hay solicitud_id que poner.
CREATE TABLE items.log_marcas (
    id               INT IDENTITY(1,1) PRIMARY KEY,
    fecha            DATETIME2      NOT NULL CONSTRAINT DF_log_marcas_fecha DEFAULT SYSUTCDATETIME(),
    usuario_web      NVARCHAR(200)  NULL,
    marca_id         NVARCHAR(20)   NULL,                   -- codigo intentado / creado (K####)
    descripcion      NVARCHAR(200)  NULL,
    http_status      INT            NULL,
    codigo_conector  INT            NULL,
    mensaje          NVARCHAR(MAX)  NULL,
    payload_enviado  NVARCHAR(MAX)  NULL
);
GO


/* ----------------------------------------------------------------------------
   MAPEO SharePoint (InternalName real) -> items.solicitudes
   ----------------------------------------------------------------------------
   Title                            -> titulo
   Marca                            -> marca_id via cat_marcas.descripcion; si no casa -> marca_nueva_texto
   CLIENTE                          -> cliente_id via dbo.PQRS_ClientesSiesa.Nombre; original siempre a cliente_texto
   Calibre                          -> calibre_id via cat_calibres.descripcion
   TipodeMaterial                   -> tipo_material
   Cantidad                         -> cantidad
   Vendedor (People: Title, EMail)  -> vendedor_nombre, vendedor_email
   ItemenSistema                    -> estado
   PedidoUnoe                       -> pedido_unoe
   SOLICITUDENTREGADAADISE_x00d1_O  -> op_entregada_diseno
   CabPlancha                       -> cab_plancha
   Planchas                         -> planchas
   FechaPlanchas                    -> fecha_planchas
   TipoSolicitud (MultiChoice)      -> tipo_solicitud (CSV)
   Aprobacion                       -> aprobacion
   Dise_x00f1_ador                  -> disenador
   Author/Title                     -> creado_por
   Editor/Title                     -> modificado_por
   Created                          -> fecha_creado
   Id                               -> sharepoint_item_id
   ---------------------------------------------------------------------------- */

/* ============================================================================
   Parametros de planeacion y cargues (2026-10-31)
   ----------------------------------------------------------------------------
   "Aprobación de Diseño" ya no crea el item: lo AUTORIZA (fecha_autorizacion).
   El planeador elige ruta y bodega de asignacion en "Items listos a crear" y
   confirma; un cargue crea el item-extension y luego le asocia sus
   parametros (conector PARAMETROS_ITEMS_V5). fecha_autorizacion es un campo
   propio y no `aprobacion` porque 282 filas migradas de SharePoint ya traen
   aprobacion = 1 y no deben aparecer como pendientes de cargar.
   ============================================================================ */
IF COL_LENGTH('items.solicitudes', 'fecha_autorizacion') IS NULL
    ALTER TABLE items.solicitudes ADD
        fecha_autorizacion  datetime2     NULL,
        ruta_id             nvarchar(20)  NULL,
        bodega_asignacion   nvarchar(5)   NULL,
        planeacion_estado   nvarchar(20)  NULL,   -- NULL | 'Cargada' | 'Error'
        planeacion_mensaje  nvarchar(600) NULL;
GO

-- f120_id (codigo numerico de 7 posiciones): el conector de parametros pide
-- el item por codigo, no por referencia. Lo llena el sync cuando la consulta de
-- items trae la columna 'ITEM ID', o el planeador a mano una vez por item base.
IF COL_LENGTH('items.cat_items_base', 'item_id') IS NULL
    ALTER TABLE items.cat_items_base ADD item_id int NULL;
GO

IF OBJECT_ID('items.cargues') IS NULL
CREATE TABLE items.cargues (
    id          int IDENTITY PRIMARY KEY,
    fecha       datetime2     NOT NULL DEFAULT SYSUTCDATETIME(),
    fecha_fin   datetime2     NULL,
    usuario     nvarchar(200) NULL,
    estado      nvarchar(20)  NOT NULL DEFAULT 'En proceso',  -- 'En proceso' | 'Terminado'
    total       int           NOT NULL DEFAULT 0,
    exitosos    int           NOT NULL DEFAULT 0,
    con_error   int           NOT NULL DEFAULT 0
);
GO

IF OBJECT_ID('items.cargue_detalle') IS NULL
CREATE TABLE items.cargue_detalle (
    id              int IDENTITY PRIMARY KEY,
    cargue_id       int           NOT NULL REFERENCES items.cargues(id),
    solicitud_id    int           NOT NULL REFERENCES items.solicitudes(id),
    referencia      nvarchar(50)  NULL,
    item_codigo     int           NULL,
    marca_id        nvarchar(20)  NULL,
    calibre_id      nvarchar(20)  NULL,
    ruta_id         nvarchar(20)  NULL,
    bodega          nvarchar(5)   NULL,
    estado          nvarchar(20)  NOT NULL DEFAULT 'En cola',  -- 'En cola' | 'Exitoso' | 'Error'
    item_ok         bit           NULL,
    item_mensaje    nvarchar(1000) NULL,
    param_ok        bit           NULL,
    param_mensaje   nvarchar(1000) NULL,
    param_http      int           NULL,
    param_codigo    int           NULL,
    param_payload   nvarchar(max) NULL,
    fecha           datetime2     NULL
);
GO

/* ============================================================================
   Usuarios, roles y permisos (2026-10-31)
   ----------------------------------------------------------------------------
   Mismo modelo que la app produccionweb (planeacion.roles / rol_permisos):
   roles dinamicos con permisos por modulo (ver/crear/editar/eliminar),
   editables desde Usuarios > Roles y Permisos. La lista de modulos es fija y
   vive en app/auth/seguridad.py (MODULOS); el backend valida cada endpoint
   contra esta matriz.
   Sesiones: token aleatorio en cookie HttpOnly; aqui solo se guarda su SHA-256,
   asi desactivar un usuario o cerrar sesion la invalida de inmediato.
   Claves: hash scrypt (stdlib), nunca en claro.
   ============================================================================ */
IF OBJECT_ID('items.roles') IS NULL
CREATE TABLE items.roles (
    id           int IDENTITY PRIMARY KEY,
    nombre       nvarchar(100) NOT NULL UNIQUE,
    descripcion  nvarchar(255) NULL,
    activo       bit           NOT NULL DEFAULT 1,
    created_at   datetime2     NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

IF OBJECT_ID('items.rol_permisos') IS NULL
CREATE TABLE items.rol_permisos (
    id              int IDENTITY PRIMARY KEY,
    rol_id          int          NOT NULL REFERENCES items.roles(id),
    modulo          nvarchar(50) NOT NULL,
    puede_ver       bit          NOT NULL DEFAULT 0,
    puede_crear     bit          NOT NULL DEFAULT 0,
    puede_editar    bit          NOT NULL DEFAULT 0,
    puede_eliminar  bit          NOT NULL DEFAULT 0,
    CONSTRAINT UQ_rol_permisos UNIQUE (rol_id, modulo)
);
GO

IF OBJECT_ID('items.usuarios') IS NULL
CREATE TABLE items.usuarios (
    id                 int IDENTITY PRIMARY KEY,
    username           nvarchar(50)  NOT NULL UNIQUE,     -- se guarda en minusculas
    nombre             nvarchar(100) NOT NULL,
    password_hash      nvarchar(256) NOT NULL,
    rol_id             int           NOT NULL REFERENCES items.roles(id),
    activo             bit           NOT NULL DEFAULT 1,
    vendedor_id        int           NULL REFERENCES items.vendedores(id),  -- Comercial: su vendedor
    created_at         datetime2     NOT NULL DEFAULT SYSUTCDATETIME(),
    creado_por         nvarchar(100) NULL,
    ultimo_ingreso     datetime2     NULL
);
GO

IF OBJECT_ID('items.sesiones') IS NULL
CREATE TABLE items.sesiones (
    token_hash   char(64)   NOT NULL PRIMARY KEY,
    usuario_id   int        NOT NULL REFERENCES items.usuarios(id),
    creada       datetime2  NOT NULL DEFAULT SYSUTCDATETIME(),
    expira       datetime2  NOT NULL
);
GO

/* ============================================================================
   Correo y cargo de los usuarios (2026-10-31)
   ----------------------------------------------------------------------------
   email: obligatorio al crear (lo exige la API, no la columna: los usuarios
   anteriores no lo tenian). Unico entre usuarios. Sera el destino de las
   notificaciones de avance que enviara un workflow de n8n.
   cargo: area de la persona (Comercial | Diseño | Producción), distinto del
   rol (que solo define permisos). Lista fija en app/auth/seguridad.py (CARGOS).
   ============================================================================ */
IF COL_LENGTH('items.usuarios', 'email') IS NULL
    ALTER TABLE items.usuarios ADD email nvarchar(200) NULL, cargo nvarchar(50) NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_usuarios_email')
    CREATE UNIQUE INDEX UX_usuarios_email ON items.usuarios(email) WHERE email IS NOT NULL;
GO

/* ============================================================================
   Configuracion: listas editables (2026-10-31)
   ----------------------------------------------------------------------------
   Tipos de material y tipos de solicitud dejan de estar fijos en el codigo.
   Se agregan o se desactivan desde la pantalla Configuracion; no se renombran
   ni se borran, porque items.solicitudes guarda el NOMBRE (texto) y el
   historico no debe cambiar. UNIQUE (lista, nombre) con la collation CI:
   "p1" y "P1" son la misma opcion.
   ============================================================================ */
IF OBJECT_ID('items.config_opciones') IS NULL
CREATE TABLE items.config_opciones (
    id          int IDENTITY PRIMARY KEY,
    lista       nvarchar(30)  NOT NULL,          -- 'materiales' | 'tipos_solicitud'
    nombre      nvarchar(60)  NOT NULL,
    activo      bit           NOT NULL DEFAULT 1,
    orden       int           NOT NULL DEFAULT 0,
    created_at  datetime2     NOT NULL DEFAULT SYSUTCDATETIME(),
    creado_por  nvarchar(100) NULL,
    CONSTRAINT UQ_config_opciones UNIQUE (lista, nombre)
);
GO

-- tipo_material era nvarchar(20): un material nuevo con nombre largo fallaria al guardar.
IF COL_LENGTH('items.solicitudes', 'tipo_material') < 120   -- 120 bytes = 60 nvarchar
    ALTER TABLE items.solicitudes ALTER COLUMN tipo_material nvarchar(60) NOT NULL;
GO

-- Siembra con las listas que estaban en el codigo (solo si la lista esta vacia).
IF NOT EXISTS (SELECT 1 FROM items.config_opciones WHERE lista = 'materiales')
    INSERT INTO items.config_opciones (lista, nombre, orden, creado_por) VALUES
        ('materiales', 'P1', 1, 'sistema'), ('materiales', 'P2', 2, 'sistema'),
        ('materiales', 'SP', 3, 'sistema'), ('materiales', 'PEFC', 4, 'sistema'),
        ('materiales', 'Bio Natura', 5, 'sistema'), ('materiales', 'EARTHPACK', 6, 'sistema'),
        ('materiales', 'Kraft Corrugado', 7, 'sistema');
GO
IF NOT EXISTS (SELECT 1 FROM items.config_opciones WHERE lista = 'tipos_solicitud')
    INSERT INTO items.config_opciones (lista, nombre, orden, creado_por) VALUES
        ('tipos_solicitud', N'Diseño Nuevo', 1, 'sistema'), ('tipos_solicitud', 'Cambio de Arte', 2, 'sistema'),
        ('tipos_solicitud', 'Destruir Planchas', 3, 'sistema'), ('tipos_solicitud', 'Solicitud de Arte', 4, 'sistema'),
        ('tipos_solicitud', 'Cambio de Calibre', 5, 'sistema');
GO

/* ============================================================================
   Cargos como lista configurable (2026-10-31)
   ----------------------------------------------------------------------------
   Los cargos dejan de estar fijos en el codigo y se administran en
   Configuracion como las demas listas. "Comercial" no se puede desactivar: de
   el salen los vendedores de las solicitudes (app/opciones.py, PROTEGIDAS).
   usuarios.cargo pasa a nvarchar(60), el maximo de cualquier opcion.
   ============================================================================ */
IF COL_LENGTH('items.usuarios', 'cargo') < 120
    ALTER TABLE items.usuarios ALTER COLUMN cargo nvarchar(60) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM items.config_opciones WHERE lista = 'cargos')
    INSERT INTO items.config_opciones (lista, nombre, orden, creado_por) VALUES
        ('cargos', 'Comercial', 1, 'sistema'), ('cargos', N'Diseño', 2, 'sistema'),
        ('cargos', N'Producción', 3, 'sistema');
GO

/* ============================================================================
   Notificaciones por correo (2026-11-05)
   ----------------------------------------------------------------------------
   Registro de cada correo de avance y cola de envio (outbox). La plataforma
   arma el correo completo y lo deja aqui; un hilo del backend lo manda al
   Webhook del flujo de n8n, que envia con la credencial "Formularios". Ver
   plataforma-web/backend/app/notificaciones.py.
   estado: Pendiente (en cola, tambien entre reintentos) | Enviando | Enviado |
           Error (fallo los 5 intentos) | Omitido (nadie a quien enviar) |
           Vencido (24 h sin salir)
   destino: vendedor | diseno | planeacion. para: correos separados por coma.
   ============================================================================ */
IF OBJECT_ID('items.notificaciones') IS NULL
CREATE TABLE items.notificaciones (
    id               int IDENTITY PRIMARY KEY,
    solicitud_id     int            NULL REFERENCES items.solicitudes(id),
    evento           nvarchar(40)   NOT NULL,
    destino          nvarchar(20)   NOT NULL,
    para             nvarchar(1000) NULL,
    asunto           nvarchar(300)  NOT NULL,
    cuerpo_html      nvarchar(max)  NOT NULL,
    cuerpo_texto     nvarchar(max)  NULL,
    estado           nvarchar(20)   NOT NULL DEFAULT 'Pendiente',
    intentos         int            NOT NULL DEFAULT 0,
    detalle          nvarchar(1000) NULL,
    creado           datetime2      NOT NULL DEFAULT SYSUTCDATETIME(),
    actualizado      datetime2      NULL,
    proximo_intento  datetime2      NULL,
    enviado          datetime2      NULL
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_notificaciones_cola')
    CREATE INDEX IX_notificaciones_cola ON items.notificaciones(estado, proximo_intento);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_notificaciones_solicitud')
    CREATE INDEX IX_notificaciones_solicitud ON items.notificaciones(solicitud_id, id);
GO

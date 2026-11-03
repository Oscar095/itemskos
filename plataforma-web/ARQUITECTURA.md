# Plataforma web de creacion de items - estado del proyecto

## Decisiones ya tomadas (2026-09-03)

| Decision | Elegido |
|---|---|
| Motor SQL | SQL Server, base **nueva** (`KOS_ItemsWeb`), misma instancia que Siesa. No se toca el esquema de Siesa/UnoEE. |
| Alcance | La web **reemplaza** la lista de SharePoint. Se migra el historico una sola vez; de ahi en adelante la web es la unica fuente. |
| Backend | Python (FastAPI), reutilizando `catalogo.py` y `siesa_api.py` del proceso de creacion masiva ya construido y probado. |
| Frontend | Node/React. |
| Revision de SharePoint | Via navegador (sesion de Chrome del usuario), solo lectura, sin credenciales nuevas para la fase de revision. |

## Por que una plataforma web (el problema que resuelve)

El proceso actual (`analizar.py` / `crear.py` en la carpeta raiz) usa una lista de
SharePoint donde Marca/Calibre/Item base son **texto libre**. Eso obliga a un
matcher que adivina contra los catalogos de Siesa, y cuando no hay coincidencia
exacta la fila queda bloqueada para revision manual (ver `salida/revision_manual.csv`
de la corrida del 2026-09-02: 13 de 76 filas bloqueadas, la mitad por typos o
variantes de nombre). La plataforma web elimina la adivinanza en el origen:
el usuario **selecciona** de listas pobladas con los datos reales de Siesa, no
escribe.

## Lo que ya existe en este repo (reutilizado, no reescrito)

- `catalogo.py` / `plataforma-web/backend/app/siesa/matcher.py` (copia identica):
  normalizacion y los tres matchers. Es logica pura, sin I/O, se reutiliza tal cual.
- `siesa_api.py` -> adaptado en `plataforma-web/backend/app/siesa/client.py`:
  mismo contrato de API ya descubierto y verificado (ver los comentarios de
  ese archivo), pero leyendo config de `.env` via `pydantic-settings` en vez
  de parsear `.env.txt` a mano.
- `sql/koscolombia_Items_odoo_crm_v2.sql`: la consulta de items corregida
  (sin el EXISTS que ocultaba items recien creados). La plataforma la sigue
  necesitando para poblar `cat_extensiones_existentes`, pero NUNCA en vivo
  por request — tarda ~350s. Ver `cat_*` en el schema.

## Estructura

```
plataforma-web/
  backend/
    requirements.txt
    .env.example          <- copiar a .env y llenar (ver bloqueos abajo)
    app/
      main.py              <- FastAPI: routers, sesion obligatoria, anti-CSRF
      config.py             <- pydantic-settings, carga .env
      siesa/
        client.py            <- llamadas a Siesa Connekta (adaptado de siesa_api.py)
        matcher.py            <- matching item base/marca/calibre (= catalogo.py)
      db/                    <- VACIO: modelos SQLAlchemy, bloqueado en credenciales SQL
      api/                   <- VACIO: rutas REST, bloqueado en lo mismo
  frontend/
    package.json            <- Vite + React, sin componentes aun
sql/
  plataforma_web_schema.sql <- DDL borrador (marcado con lo que falta confirmar)
```

## Revision de SharePoint: HECHA (2026-09-03)

Via REST API con la sesion de navegador (sin necesitar Graph API todavia).
Resultado completo en `sql/plataforma_web_schema.sql`. Lo mas importante:

- El sitio es `https://koscolombiacali.sharepoint.com/sites/INTRANETKOS`
  (confirmado — su pagina de inicio da un 404 en texto plano, pero eso es
  solo la pagina de inicio rota; la API y las listas andan bien).
- La lista se llama en realidad **"PLATAFORMA DE ITEMS Y PEDIDO DE PLANCHAS"**,
  GUID `c0b3e740-d705-4f48-9c6a-d8e88082bae0`, 952 items, en uso activo
  (modificada el mismo dia de esta revision).
- `Vendedor` es un campo **People** real (Title + EMail de Microsoft 365),
  no texto libre — buena noticia, se puede atar directo a login corporativo.
- Tres correcciones al schema que tenia yo mal adivinado desde el Excel:
  `OP Entregada a diseño` es **DateTime**, no booleano; `Planchas` y
  `Pedido Unoe` son **Choice** de valores fijos, no texto libre.
- **4 campos que el Excel nunca trajo** y por tanto el proceso actual de
  creacion de items ignora por completo: `Tipo Solicitud` (MultiChoice —
  Diseño Nuevo, Cambio de Arte, Destruir Planchas, Solicitud de Arte,
  Cambio de Calibre), `Aprobacion` (booleano), `Diseñador` (Cristhian
  Santana / Karol Michelle / Diana Nieto) y `Fecha Planchas`. Describen un
  flujo de aprobacion de diseño que vale la pena que la plataforma nueva
  sí capture.

### Hallazgo operativo (no es de arquitectura, pero es urgente)

De los 952 items, **25 siguen en "Pendiente"** ahora mismo. Al revisarlos uno
por uno contra lo que ya procesamos:

| Situacion | Filas |
|---|---|
| Genuinamente bloqueadas (falta marca o item base en Siesa) | 9 |
| Creadas en Siesa el 2026-09-02, pero el flag de SharePoint nunca se actualizo | 8 |
| Ya existian en Siesa desde antes, flag nunca actualizado | 2 |
| Nuevas de hoy, marca **NOOK** (cliente Daniela Fernandez) — sin procesar | 4 |
| Arregladas hoy con la regla Tazon->Cont (900, 901) | 2 |

Es decir: **10 de las 25 filas "Pendiente" ya estan resueltas en Siesa** y solo
falta reflejarlo en SharePoint — exactamente el tipo de desincronizacion que
esta plataforma existe para eliminar. Se puede corregir ya mismo via la misma
API (con permiso explicito, es escritura sobre datos de produccion que otros
consultan). Las 4 de NOOK son trabajo nuevo, no relacionado con lo ya hecho.

## Base de datos: CONECTADA Y DESPLEGADA (2026-09-03)

Las credenciales estaban en el `.env.txt` de la raiz todo el tiempo (`BD_HOST`,
`BD_NAME`, `BD_USER`, `BD_PASSWORD`). El destino real **no** es el servidor de
Siesa como se habia decidido, sino:

- **Azure SQL** `myappskos.database.windows.net`, base **`kx_ecommerce`**
- Usuario `kos`, mapea a `dbo`, permiso `CONTROL` (puede crear esquemas y tablas)
- La base ya aloja **105 tablas de 5 aplicaciones**, con convencion de
  **un esquema por aplicacion**: `calidad`, `evaluaciones`, `facturas`,
  `importacion`, y `dbo` (e-commerce + PQRS)

Por eso la plataforma vive en un **esquema `items`** dentro de esa base, no en
una base nueva. Ya desplegado (`sql/plataforma_web_schema.sql`): 6 tablas
—`cat_marcas`, `cat_calibres`, `cat_items_base`, `cat_extensiones_existentes`,
`solicitudes`, `log_creacion`— con FK cruzada a `dbo.PQRS_ClientesSiesa`.

### Driver de Python: pymssql, no pyodbc

`pyodbc` no tiene wheel para Python 3.14 y compilarlo exige Visual C++ Build
Tools que no estan instalados. `pymssql` trae wheel y conecta a Azure SQL sin
driver ODBC del sistema. Ya verificado funcionando.

### OJO con el selector de clientes

Se decidio alimentar el campo CLIENTE desde `dbo.PQRS_ClientesSiesa` (1097
clientes sincronizados desde Siesa). Al medirlo contra los 464 clientes
distintos que hay hoy en la lista de SharePoint:

| Criterio de comparacion | Casan |
|---|---|
| Exacto | 88 (18%) |
| Ignorando espacios y puntuacion | 161 (34%) |
| Ignorando ademas el sufijo legal (SAS, SA, LTDA) | 233 (50%) |

**La mitad no casa ni con el criterio mas laxo**, y al mirarlos son nombres de
personas: ANDREA, ALEXANDER TORRES, ANGELICA ABADIA, ANDRES PINILLA. Son
contactos o prospectos, no clientes registrados en Siesa.

Conclusion: un selector *estricto* contra esa tabla bloquearia la mitad del uso
real. El esquema ya contempla ambos casos (`cliente_id` nullable + `cliente_texto`
que siempre conserva el valor original), pero **falta decidir que hace la UI**:
obligar a elegir de la lista, o permitir texto libre cuando el cliente aun no
existe en Siesa.

## Alta de marcas (Ext1) desde el formulario (2026-10-31)

El selector de marca ya no deja la solicitud "Bloqueada" por marca inexistente:
si lo escrito no coincide con ninguna marca, ofrece **crearla en Siesa** con el
siguiente consecutivo (conector `API_CREACION_MARCAS`, "Creacion Extensiones").
Logica en `backend/app/siesa/marcas.py`, endpoints en `routes_catalogo.py`:

- `GET /catalogos/marcas` refresca `items.cat_marcas` contra Ext1 en vivo cada
  5 min (upsert, nunca DELETE). La cache congelada era la causa de duplicados
  (NOOK quedo creada dos veces: K1949 y K1968).
- `GET /catalogos/marcas/vista-previa` dice que codigo tomaria y si ya existe una
  igual (sin acentos/signos/mayusculas). No crea nada.
- `POST /catalogos/marcas` crea, vuelve a consultar Ext1 para confirmar y audita
  en `items.log_marcas`.
- Consecutivo: numeracion unica compartida por `K`/`k`, ignorando el bloque de
  cargas masivas K4000+. Se crea con `K` mayuscula.
- Prueba real hecha: **K2019 PRUEBA API KOS** (2026-10-31). Hay que inactivarla en Siesa.

## Flujo con parametros de planeacion (2026-10-31)

Reemplaza la creacion automatica al aprobar (que se uso solo unas horas).

1. **Vendedor** crea la solicitud. La marca inexistente se crea en Ext1 desde el
   selector. El backend rechaza (409) un item que ya existe en Siesa o que ya
   tiene otra solicitud abierta, y exige calibre. El aviso del formulario
   (`GET /solicitudes/verificar`) usa esa misma regla (`routes_solicitudes.duplicado`):
   hasta el 2026-11-03 solo miraba el catalogo de Siesa y decia "se puede crear"
   a combinaciones ya pedidas o creadas desde la plataforma.
2. **Diseño** registra "Aprobación de Diseño": se corren las validaciones que no
   necesitan Siesa (`creacion.revisar`) y la solicitud queda **autorizada**
   (`fecha_autorizacion`). No se crea nada. Si falla una validacion queda
   `Bloqueado` y no llega al planeador.
3. **Planeador**, pestaña *Planeación → Items listos a crear*: elige ruta (lista
   en vivo de `API_RUTAS`, solo activas, cache 10 min) y bodega de asignacion
   (020 / 018, fija en codigo) y confirma. Lo que elige se guarda como borrador.
4. **Cargue** (`app/siesa/planeacion.py`, hilo en segundo plano, uno a la vez):
   por cada fila crea el item-extension y, solo si quedo creado, envia sus
   parametros (`API_CREACION_PARAM_PLANEACION`, PARAMETROS_ITEMS_V5). Si el item
   ya estaba creado y fallaron solo los parametros, el reintento no reenvia el item.
5. **Historial de cargues** (`items.cargues`, `items.cargue_detalle`): resultado
   de cada paso por item, con el motivo legible de Siesa.

`fecha_autorizacion` es un campo nuevo y no se reutiliza `aprobacion`, porque
282 filas migradas ya traen `aprobacion = 1`. Un cargue cortado por un reinicio
del servidor queda `Terminado` y sus filas en `Error` al arrancar.

### Contrato del conector de parametros

- Seccion `"Versión"` **con tilde**. Campos: `Ruta` (20), `Bodega de asignación`
  (5), `Codigo item` (7: es el **f120_id numerico**, no la referencia),
  `Extension 1` / `Extension 2` (20). La respuesta viene en latin-1. Genera
  registros tipo 132.
- Validaciones confirmadas sin escribir nada (400): "El item - extensión no
  existe", "La ruta no es valida", "La bodega de asignación no es valida".
  El aviso de unidad de medida `UND` solo sale cuando el item no existe.
- El registro tipo 0 que faltaba y `ITEM ID` en la consulta de items se
  corrigieron en Connekta el 2026-10-31. El sync ya llena `cat_items_base.item_id`
  (204 de 205 referencias; la que falta ya no sale en la consulta).
- **Primera carga real:** cargue #6 (2026-10-31, OSCAR OROZCO), SOL-00971:
  VASO 7 OZ `KPT0009349` (9349) · K2020 BUTHER · K012, ruta VASO 7 OZ, bodega
  020. Los dos conectores respondieron 200 / codigo 0.

### Sync de catalogos

`python -m app.siesa.sync` ya no borra marcas, calibres ni items base: hace
MERGE (`_merge`), porque `solicitudes` tiene FK a las tres y el DELETE fallaba
en cuanto habia una solicitud. Solo `cat_extensiones_existentes` se recarga
completa. La consulta de items tardo 564 s el 2026-10-31 (9.856 filas); el
timeout del cliente subio a 900 s.

### Concurrencia del cargue

`iniciar_cargue` toma el lock (sin esperar) antes de validar y lo suelta el hilo
al terminar: un segundo cargue simultaneo recibe 400. Si una fila revienta, se
marca Error solo si seguia "En cola" y el cargue igual se cierra. Una solicitud
que ya esta "Cargada" no se reenvia. El POST de solicitudes tambien rechaza una
combinacion que otra solicitud ya creo, aunque el catalogo aun no la tenga.

## Duplicados validados en vivo contra Siesa (2026-11-03)

- `koscolombia_Items_odoo_crm` se publicó **sin la columna de costo**: responde en ~1 s
  (9.859 filas) en vez de ~10 min. Medido: 16 de 17 llamadas entre 0,9 y 1,2 s; una de 27,7 s.
- La regla de duplicados (`routes_solicitudes.duplicado`) consulta Siesa **en vivo**
  (`app/siesa/extensiones.py`). El aviso del formulario usa una cache en memoria de 60 s;
  guardar, aprobar (`creacion.revisar`) y cargar vuelven a consultar. Tope de espera: 5 s
  para conectar y 15 s para responder. Si Siesa no responde se usa la copia
  `cat_extensiones_existentes` y el aviso lo dice; tras un fallo no se le insiste por 30 s.
- Las solicitudes siguen en la regla: cubren lo pedido y aún no creado, que Siesa no conoce.
  Primera prueba real: SOL-00001 y SOL-00002 (SKU 51163 y 51164) estaban en Siesa y no en la
  copia; en vivo se detectan.
- **Pendiente:** la versión publicada solo trae 5 columnas y el sync (`python -m app.siesa.sync`)
  necesita además DESCRIPCION, TIPO ITEM, ITEM ID y MARCA KOS: falla con `KeyError` antes de
  escribir nada. `sql/koscolombia_Items_odoo_crm_v3.sql` las devuelve sin el costo. Si Odoo usa
  el costo de esta consulta, publicar la v3 con otro nombre y ponerlo en `CONSULTA_ITEMS`.

## Usuarios, roles y login (2026-10-31)

Mismo modelo y mismo diseño que la app **produccionweb** (repo `Oscar095/produccionweb`),
para que las apps de KOS se vean y administren igual.

- **Roles dinámicos** (`items.roles`, `items.rol_permisos`) con matriz por módulo
  Ver/Crear/Editar/Eliminar, editable en *Usuarios → Roles y Permisos*. Módulos fijos
  en `app/auth/seguridad.py` (`MODULOS`, con lo que significa cada casilla):
  `seguimiento`, `solicitudes`, `marcas`, `diseno`, `pedidos`, `planeacion`, `usuarios`.
- Roles sembrados al arrancar (solo si no existen):

  | Rol | Puede |
  |---|---|
  | Admin | Todo |
  | Comercial | Ver seguimiento y adjuntar; crear solicitudes y marcas; registrar Digitación de Pedido |
  | Diseño | Ver seguimiento y adjuntar; registrar Solicitud/Aprobación de Diseño y Llegada de Planchas |
  | Planeación | Ver seguimiento y adjuntar; Items listos a crear, cargues, ruta/bodega; Creación de item y En producción |

- El backend valida **cada endpoint** contra la matriz (`requiere(modulo, accion)`), no
  el nombre del rol. Las etapas se mapean en `routes_solicitudes.ETAPA_MODULO`.
  Autoría (eventos, `creado_por`, marcas, cargues) sale de la sesión, nunca del navegador.
  Un usuario ligado a un vendedor solo crea solicitudes a nombre de ese vendedor.
- **Sesión**: token aleatorio en cookie HttpOnly `kos_items_sesion` (SameSite=Lax), en
  base como SHA-256. 8 h deslizantes, tope absoluto 12 h. Desactivar, resetear clave o
  cambiar la propia cierra las sesiones afectadas al instante. Claves con scrypt (stdlib).
- **Defensas** (auditoría del 2026-10-31): encabezado `X-KOS: 1` obligatorio en toda
  escritura (anti-CSRF; sin CORS), regla de **no escalar** (nadie asigna, crea o toca
  roles/usuarios con más permisos que los suyos, ni cambia su propio rol), bloqueo de 5
  intentos por usuario normalizado NFKC, `sp_getapplock` para no quedar sin administradores.
- **Primer Admin / recuperación**: `python -m app.auth.crear_admin --usuario X --nombre "..."`
  (pide la clave; `--generar` crea una aleatoria).
- **Producción (HTTPS)**: poner `COOKIE_SECURE=1` en el `.env`.
- **Frontend**: Tailwind 3 + lucide-react + react-router + zustand, como produccionweb.
  Piezas compartidas en `frontend/src/components/ui.jsx` (PageHero, HeroTabs, KpiCard,
  Modal, Field, Loading, Pill, `fechaHora`). Todo llamado al API pasa por `src/api.js`.
- La migración desde SharePoint quedó solo para Admin y ya no funciona desde la pestaña de
  SharePoint (se quitó el CORS): el histórico ya está migrado.

## Usuarios: correo, cargo, Activo y vendedores (2026-10-31)

- **Correo obligatorio** al crear un usuario (único, en minúsculas): será el destino de
  las notificaciones de avance del workflow de n8n. Los usuarios anteriores sin correo
  (hoy solo `oscar`) se completan en *Editar*, que ya no deja guardar sin correo.
- **Cargo**: lista de *Configuración* (sembrada con Comercial, Diseño y Producción;
  Planeación va en Producción). Es el área de la persona; el **rol** solo define
  permisos. "Comercial" no se puede desactivar (de él salen los vendedores). Si un cargo
  se desactiva, quien ya lo tiene lo conserva y se le puede seguir editando.
- **Casilla Activo** (crear, editar y en la tabla). Inactivo = no entra ni aparece en
  listados, pero su historial se conserva; se puede crear inactivo para registrar a
  alguien que ya no está. Filtro Activos / Inactivos / Todos.
- **Vendedor de una solicitud = usuario activo con cargo Comercial**
  (`GET /catalogos/comerciales`). `routes_auth.sincronizar_vendedor` liga cada Comercial
  a `items.vendedores` por correo (crea el vendedor si no existe) y deja
  `vendedores.activo` como espejo. Si un vendedor migrado de SharePoint recibe un usuario
  con su mismo correo, conserva todo su historial. Un Comercial solo crea a su nombre;
  los demás eligen entre los comerciales activos. El filtro de vendedor del Seguimiento
  sigue mostrando todos (también los históricos). Si a un Comercial le corrigen el
  correo, se actualiza su MISMO vendedor (no se parte el historial); si el correo nuevo
  ya es de otro vendedor con historial, se rechaza.
  **Hasta que se creen los usuarios comerciales, el desplegable de vendedor está vacío.**

## Configuración (2026-10-31)

- Pantalla *Configuración* (módulo de permisos `configuracion`; el Admin lo recibe
  solo al arrancar, como cualquier módulo nuevo que ningún rol tenga aún) con las listas
  **Tipo de material**, **Tipo de solicitud** y **Cargo** (`items.config_opciones`,
  `app/opciones.py`; las que el código usa por nombre están en `PROTEGIDAS`).
- Se agregan o se desactivan; no se renombran ni se borran, porque cada solicitud
  guarda el nombre y el historial no debe cambiar. Sin comas (el histórico separa varios
  tipos por coma), máx. 60 caracteres, sin duplicados (sin distinguir mayúsculas).
  No se puede desactivar la última opción activa de una lista (serializado con
  `sp_getapplock` por lista).
- La regla Bio Natura / P1 / P2 de `creacion._revisar_material` depende de esos nombres.
- `tipo_material` pasó de nvarchar(20) a nvarchar(60).

## Pantallas sin tarjetas de indicadores (2026-10-31)

Por pedido: sin KPIs ni bloques tipo dashboard. Cada pantalla es encabezado + barra de
filtros/acciones en tarjeta + tabla. El primer bloque bajo el encabezado siempre es una
tarjeta blanca (queda montado sobre el degradado). Los filtros que daban las tarjetas
de Seguimiento pasaron a pastillas de estado y a un desplegable de etapa.

## Base limpia: arranque desde cero (2026-10-31)

Por decisión del dueño la plataforma no arrastra el histórico de SharePoint. Se
borraron las 954 solicitudes (953 migradas + SOL-00971), su seguimiento, el cargue #6,
los logs de creación de items y marcas y los 14 vendedores históricos, y se reiniciaron
los contadores (la primera solicitud real es SOL-00001). Se conservaron usuarios, roles,
permisos, configuración, etapas y los catálogos de Siesa. Respaldo JSON en
`respaldos/2026-10-31_antes_de_limpiar/` (fuera del repositorio: tiene datos de la empresa).
Lo creado en Siesa no se toca: el item SKU 51162 (VASO 7 OZ · K2020 BUTHER · K012) y las
marcas K2019/K2020 siguen allá.

## Despliegue en Azure (2026-11-01)

Web App **items** (Linux, Python 3.11), desplegada por GitHub Actions
(`.github/workflows/main_items.yml`) en cada push a `main`. Un solo servicio: el build
de React (`vite build`) se copia a `backend/static` y FastAPI lo sirve; `/api/*` llega a
la API sin el prefijo, igual que con el proxy de Vite (`app.main:servidor`). El paquete
solo lleva `app/`, `requirements.txt` y `static/`; Oryx hace el `pip install` en Azure.

- Arranque (lo fija el workflow): `python -m uvicorn app.main:servidor --host 0.0.0.0 --port 8000`.
  Un solo proceso a propósito: el candado de los cargues de planeación vive en memoria.
- Configuración: no hay `.env` en Azure; las claves de `backend/.env.example` van como
  variables de entorno de la Web App (con `COOKIE_SECURE=1`).
- El firewall de Azure SQL debe dejar entrar a la Web App.
- La sincronización del catálogo (`python -m app.siesa.sync`, ~10 min) sigue siendo manual:
  se puede correr desde un PC con el `.env`, escribe en la misma base.

## Bloqueado, por que, y que se necesita

| Bloqueo | Bloquea | Que hace falta |
|---|---|---|
| App Registration de Azure AD (Graph API) | Migracion del historico de SharePoint sin depender de una sesion de navegador interactiva | Un admin del tenant crea el App Registration con permiso `Sites.Read.All` o `Sites.Selected` sobre INTRANETKOS y da consentimiento. Tenant/Client ID y Secret van al `.env.txt` |

## Siguiente paso

1. Poblar las tablas `items.cat_*` con un job que llame las 3 consultas Connekta
   (la logica ya existe en `analizar.py` / `catalogo.py` de la raiz).
2. Decidir el comportamiento del selector de clientes (ver arriba).
3. Migrar los 952 items de SharePoint a `items.solicitudes`.

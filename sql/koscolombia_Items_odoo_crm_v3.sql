/* ============================================================================
   koscolombia_Items_odoo_crm  -  v3 (sin la columna de costo)
   ----------------------------------------------------------------------------
   POR QUE HAY UNA v3 (2026-11-03)

   La v2 tardaba ~10 min (564 s) por el costo (t470_cm_movto_invent). La
   plataforma ahora valida duplicados EN VIVO contra Siesa
   (plataforma-web/backend/app/siesa/extensiones.py) y para eso la consulta
   tiene que responder en segundos.

   Lo que se publico el 2026-11-03 fue una version de 5 columnas (SKU_SIESA,
   REFERENCIA, MARCA ID, CALIBRE, ESTADO EXT): 1,0 s y 9.859 filas, pero sin
   DESCRIPCION, TIPO ITEM, ITEM ID ni MARCA KOS. El sync de la plataforma
   (app/siesa/sync.py) las necesita para los items base y falla sin ellas.
   Esta v3 las devuelve sin volver a meter el costo: son columnas de t120 y un
   LEFT JOIN a t117, nada caro. Es la v2 menos el CTE de costo.

   OJO ODOO: si la sincronizacion con Odoo lee el costo de esta consulta, no se
   reemplaza. Se deja la v2 con este nombre, se publica esta v3 con otro nombre
   y ese nombre va en CONSULTA_ITEMS (.env local y variables de la Web App).
   ============================================================================ */

SELECT
       t121.f121_rowid                      AS 'SKU_SIESA'
      ,t120.f120_descripcion                AS 'DESCRIPCION'
      ,t120.f120_ind_tipo_item              AS 'TIPO ITEM'
      ,RTRIM(t120.f120_referencia)          AS 'REFERENCIA'
      ,t120.f120_id                         AS 'ITEM ID'
      ,t117.f117_descripcion                AS 'MARCA KOS'
      ,RTRIM(t121.f121_id_ext1_detalle)     AS 'MARCA ID'
      ,RTRIM(t121.f121_id_ext2_detalle)     AS 'CALIBRE'
      ,t121.f121_ind_estado                 AS 'ESTADO EXT'
FROM        t120_mc_items                   t120
INNER JOIN  t121_mc_items_extensiones       t121
        ON  t121.f121_rowid_item = t120.f120_rowid
LEFT  JOIN  t117_mc_extensiones1_detalle    t117
        ON  t117.f117_id = t121.f121_id_ext1_detalle
WHERE t120.f120_id_tipo_inv_serv = 'IN1430K.ex';

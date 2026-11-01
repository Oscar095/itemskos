/* ============================================================================
   koscolombia_Items_odoo_crm  -  v2 (corrige el rendimiento de la v1)
   ----------------------------------------------------------------------------
   POR QUE HAY UNA v2

   La v1 que te pase se quedo sin tiempo: el API aborta a los 300 segundos.
   El error fue mio y es de rendimiento, no de resultado.

   El OUTER APPLY es una subconsulta CORRELACIONADA: se ejecuta una vez POR CADA
   fila del resultado. Mientras el EXISTS estaba, el resultado eran 2.442 filas,
   asi que se ejecutaba 2.442 veces y aguantaba. Al quitar el EXISTS entran todas
   las extensiones (incluidas las que nunca tuvieron movimiento), y el APPLY pasa
   a golpear t470_cm_movto_invent decenas de miles de veces.

   LA CORRECCION: recorrer t470 UNA sola vez, agrupando, y pegar el resultado con
   un LEFT JOIN. Deja de ser N consultas y pasa a ser una agregacion + un join.

   Se mantiene todo lo demas de la v1 (sin EXISTS, INNER JOIN a t121, sin ORDER BY,
   RTRIM, MARCA ID) y se conserva el criterio de "costo del ultimo movimiento",
   ahora con ROW_NUMBER en vez de TOP 1 correlacionado.
   ============================================================================ */

WITH costo_ultimo AS (
    SELECT  f470_rowid_item_ext
           ,f470_costo_prom_uni
           ,ROW_NUMBER() OVER (
                PARTITION BY f470_rowid_item_ext
                ORDER BY     f470_rowid DESC
            ) AS rn
    FROM    t470_cm_movto_invent
    WHERE   f470_costo_prom_uni IS NOT NULL
)
SELECT
       t121.f121_rowid                      AS 'SKU_SIESA'
      ,t120.f120_descripcion                AS 'DESCRIPCION'
      ,t120.f120_ind_tipo_item              AS 'TIPO ITEM'
      ,RTRIM(t120.f120_referencia)          AS 'REFERENCIA'
      ,t120.f120_id                         AS 'ITEM ID'   -- 2026-10-31: lo pide el conector PARAMETROS_ITEMS_V5
      ,t117.f117_descripcion                AS 'MARCA KOS'
      ,RTRIM(t121.f121_id_ext1_detalle)     AS 'MARCA ID'
      ,RTRIM(t121.f121_id_ext2_detalle)     AS 'CALIBRE'
      ,t121.f121_ind_estado                 AS 'ESTADO EXT'
      ,costo.f470_costo_prom_uni            AS 'COSTO PROM UNIT'
FROM        t120_mc_items                   t120
INNER JOIN  t121_mc_items_extensiones       t121
        ON  t121.f121_rowid_item = t120.f120_rowid
LEFT  JOIN  t117_mc_extensiones1_detalle    t117
        ON  t117.f117_id = t121.f121_id_ext1_detalle
LEFT  JOIN  costo_ultimo                    costo
        ON  costo.f470_rowid_item_ext = t121.f121_rowid
       AND  costo.rn = 1
WHERE t120.f120_id_tipo_inv_serv = 'IN1430K.ex';


/* ----------------------------------------------------------------------------
   SI LA v2 TAMPOCO ALCANZA A RESPONDER

   Opcion A - el costo mas alto en vez del ultimo. Es lo que hacia la consulta
   original (con MAX), y una agregacion simple suele ser mas barata que
   ROW_NUMBER porque no tiene que ordenar dentro de cada particion.
   Reemplazar el CTE y su join por:

        LEFT JOIN (
              SELECT   f470_rowid_item_ext
                      ,MAX(f470_costo_prom_uni) AS f470_costo_prom_uni
              FROM     t470_cm_movto_invent
              WHERE    f470_costo_prom_uni IS NOT NULL
              GROUP BY f470_rowid_item_ext
        ) costo ON costo.f470_rowid_item_ext = t121.f121_rowid

   Ojo: MAX devuelve el costo historico mas alto, no el vigente. Si el costo de
   un item bajo, reporta uno que ya no existe. Es un compromiso consciente, no
   la respuesta correcta.

   Opcion B - pedirle al DBA el indice que le falta a t470. Es la solucion de
   fondo y sirve para las dos versiones:

        CREATE NONCLUSTERED INDEX IX_t470_item_ext_costo
            ON t470_cm_movto_invent (f470_rowid_item_ext, f470_rowid DESC)
            INCLUDE (f470_costo_prom_uni)
            WHERE f470_costo_prom_uni IS NOT NULL;

   Opcion C - separar responsabilidades. El costo no hace falta para crear items;
   solo lo usa la sincronizacion con Odoo. Se puede dejar esta consulta SIN la
   columna de costo (rapidisima, es solo t120+t121+t117) y publicar el costo en
   una segunda consulta aparte. Es la opcion mas limpia si la sincronizacion de
   Odoo tolera dos llamadas.

   ----------------------------------------------------------------------------
   PENDIENTES DE LA v1 QUE SIGUEN ABIERTOS
   ----------------------------------------------------------------------------
   * El join a t117 usa solo f117_id, cuando la llave es compuesta. Verificar:

        SELECT f117_id, COUNT(*) FROM t117_mc_extensiones1_detalle
        GROUP BY f117_id HAVING COUNT(*) > 1;

     Si devuelve filas, la consulta esta duplicando y hay que completar el join
     con f117_id_cia y f117_id_extension1.

   * COSTO PROM UNIT ahora puede venir NULL (item sin movimientos). No convertirlo
     a 0: ya existen SKUs con costo 0,0 reales.
   ---------------------------------------------------------------------------- */

/* ============================================================================
   koscolombia_Items_odoo_crm  -  version corregida
   ----------------------------------------------------------------------------
   Cambios frente a la version original:

   1. Se elimina el bloque EXISTS contra t470_cm_movto_invent.
      Era el que ocultaba los items recien creados: exigia al menos un movimiento
      de inventario con costo, y una extension nueva no tiene ninguno todavia.
      La subconsulta de costo ya devuelve NULL sola cuando no hay movimientos,
      que es la respuesta correcta ("existe, aun sin costo").

   2. LEFT JOIN a t121 -> INNER JOIN.
      El EXISTS referenciaba t121.f121_rowid, asi que las filas sin extension se
      caian igual: el LEFT JOIN nunca fue LEFT. Como SKU_SIESA *es* f121_rowid,
      un item sin extension no tiene SKU y no pinta nada aqui. Se deja explicito.

   3. MAX(f470_costo_prom_uni) -> el costo del ULTIMO movimiento (OUTER APPLY).
      MAX devuelve el costo historico mas alto, no el vigente. Para un item cuyo
      costo bajo, la consulta reportaba un costo que ya no existe.

   4. Se quita el ORDER BY.
      Es la causa del HTTP 500 al usar el parametro `paginacion` del API:
      Siesa envuelve la consulta en una subconsulta y SQL Server rechaza un
      ORDER BY ahi dentro sin TOP/OFFSET. Si se quiere conservar el orden,
      usar la variante comentada al final.

   5. RTRIM en los campos CHAR (venian con relleno: 'K1167               ').

   6. Se agrega MARCA ID: la marca salia solo como descripcion, y hay
      descripciones repetidas con distinto codigo (EMA, 20 DE JULIO,
      CORRAL VAINILLA), asi que la descripcion sola no identifica la extension.

   OJO: 'CALIBRE' sigue devolviendo el CODIGO (K016), no la descripcion.
   No cambiar eso: el proceso de creacion de items y la integracion con Odoo
   dependen de que sea el codigo. Si se quiere la descripcion, agregarla como
   columna NUEVA con un join a t119_mc_extensiones2_detalle.
   ============================================================================ */

SELECT
       t121.f121_rowid                      AS 'SKU_SIESA'
      ,t120.f120_descripcion                AS 'DESCRIPCION'
      ,t120.f120_ind_tipo_item              AS 'TIPO ITEM'
      ,RTRIM(t120.f120_referencia)          AS 'REFERENCIA'
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
OUTER APPLY (
        SELECT TOP (1) t470.f470_costo_prom_uni
        FROM   t470_cm_movto_invent t470
        WHERE  t470.f470_rowid_item_ext  = t121.f121_rowid
          AND  t470.f470_costo_prom_uni IS NOT NULL
        ORDER BY t470.f470_rowid DESC
     ) costo
WHERE t120.f120_id_tipo_inv_serv = 'IN1430K.ex';


/* ----------------------------------------------------------------------------
   VARIANTE: si de verdad se necesita el ORDER BY dentro de la consulta guardada.
   El OFFSET lo vuelve legal dentro de una subconsulta y `paginacion` sigue
   funcionando. Pegar al final, en lugar del punto y coma:

        ORDER BY t117.f117_descripcion
        OFFSET 0 ROWS

   ----------------------------------------------------------------------------
   PENDIENTE DE VERIFICAR - join a t117 incompleto
   ----------------------------------------------------------------------------
   El join usa solo f117_id. En Siesa la llave de t117_mc_extensiones1_detalle es
   compuesta (compania + tipo de extension + id), asi que si un mismo f117_id
   existe para otra compania o para otro grupo de extension, esta consulta
   DUPLICA filas. Correr esto para saber si pasa:

        SELECT f117_id, COUNT(*) AS veces
        FROM   t117_mc_extensiones1_detalle
        GROUP BY f117_id
        HAVING COUNT(*) > 1;

   Si devuelve filas, completar el join (confirmar antes los nombres exactos de
   las columnas de extension en t120 en esta instalacion):

        LEFT JOIN t117_mc_extensiones1_detalle t117
               ON t117.f117_id_cia        = t120.f120_id_cia
              AND t117.f117_id_extension1 = t120.f120_id_extension1
              AND t117.f117_id            = t121.f121_id_ext1_detalle

   ----------------------------------------------------------------------------
   EFECTO DEL CAMBIO
   ----------------------------------------------------------------------------
   La consulta va a devolver MAS filas que antes (2.442): entran todas las
   extensiones sin movimiento de inventario. Esas traen COSTO PROM UNIT en NULL.
   Conviene revisar que Odoo/CRM tolere el NULL. No reemplazarlo por 0: "sin
   costo" y "costo cero" no son lo mismo, y hoy ya existen 4 SKUs con costo 0,0
   reales que se confundirian.

   Para filtrar solo extensiones activas (confirmar antes que 1 = activo):
        AND t121.f121_ind_estado = 1
   ---------------------------------------------------------------------------- */

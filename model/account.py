import logging
from odoo import models, fields, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    direccion_origen = fields.Many2one("res.partner", string="Dirección Origen")
    direccion_destino = fields.Many2one("res.partner", string="Dirección Destino")


class AccountEdiXmlUblPeDetraccion(models.AbstractModel):
    _inherit = "account.edi.xml.ubl_pe"

    # --- SOLO ZIP (getter puro) ---
    def _get_partner_ubigeo(self, partner):
        return (partner.zip or "").strip() if partner else ""

    def _get_partner_address_line_simple(self, partner):
        if not partner:
            return "-"
        # simple y compatible con template
        return partner.street or partner.name or "-"

    # --- ESTE HOOK SÍ EXISTE EN TU MODELO ORIGINAL Y SE EJECUTA ---
    def _add_invoice_header_nodes(self, document_node, vals):
        super()._add_invoice_header_nodes(document_node, vals)

        invoice = vals.get("invoice")
        if not invoice:
            return

        # Solo detracción transporte carga
        op_type = str(getattr(invoice, "l10n_pe_edi_operation_type", "") or "")
        if op_type != "1004":
            return

        origin = invoice.direccion_origen
        dest = invoice.direccion_destino
        if not origin or not dest:
            raise UserError(_("Falta Dirección Origen/Destino para detracción 1004."))

        ubigeo_origen = self._get_partner_ubigeo(origin)
        ubigeo_destino = self._get_partner_ubigeo(dest)

        _logger.info(
            "[DETRACCION][HEADER] move=%s ubigeo_origen=%s ubigeo_destino=%s",
            invoice.name, ubigeo_origen, ubigeo_destino
        )

        if not ubigeo_origen:
            raise UserError(_("Dirección Origen sin ubigeo en ZIP."))
        if not ubigeo_destino:
            raise UserError(_("Dirección Destino sin ubigeo en ZIP."))

        # ------------------------------------------------------------------
        # CLAVE: NO inventamos tags nuevos (template restrictivo).
        # Solo aseguramos que exista Invoice/cac:Delivery/cac:DeliveryLocation/cac:Address/cbc:ID
        # y lo seteamos con el UBIGEO DE ORIGEN.
        # ------------------------------------------------------------------

        # Odoo a veces crea cac:Delivery como dict o lista.
        delivery = document_node.get("cac:Delivery")

        # Normalizamos: queremos trabajar con UN dict (header delivery).
        if isinstance(delivery, list):
            # Tomamos el primero como "header delivery" y lo modificamos
            delivery_node = delivery[0] if delivery else {}
            document_node["cac:Delivery"] = delivery_node
        elif isinstance(delivery, dict):
            delivery_node = delivery
        else:
            delivery_node = {}
            document_node["cac:Delivery"] = delivery_node

        # Asegurar DeliveryLocation/Address
        delivery_node.setdefault("cac:DeliveryLocation", {})
        delivery_node["cac:DeliveryLocation"].setdefault("cac:Address", {})

        addr_node = delivery_node["cac:DeliveryLocation"]["cac:Address"]

        # Setear UBIGEO ORIGEN (esto es lo que el OSE reclama)
        addr_node["cbc:ID"] = {"_text": ubigeo_origen}

        # Dirección (opcional pero útil)
        addr_node.setdefault("cac:AddressLine", {})
        addr_node["cac:AddressLine"]["cbc:Line"] = {"_text": self._get_partner_address_line_simple(origin)}

        # País (si el template lo permite aquí, normalmente sí)
        addr_node.setdefault("cac:Country", {})
        addr_node["cac:Country"]["cbc:IdentificationCode"] = {"_text": "PE"}

        _logger.info("[DETRACCION][HEADER] DeliveryLocation set to ORIGEN OK")
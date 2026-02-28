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

    # Getter puro: SOLO ZIP (como pediste)
    def _get_partner_ubigeo(self, partner):
        return (partner.zip or "").strip() if partner else ""

    def _get_partner_address_line_simple(self, partner):
        if not partner:
            return "-"
        return partner.street or partner.name or "-"

    def _add_invoice_header_nodes(self, document_node, vals):
        super()._add_invoice_header_nodes(document_node, vals)

        invoice = vals.get("invoice")
        if not invoice:
            return

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
            raise UserError(_("Dirección Origen sin ubigeo (ZIP)."))
        if not ubigeo_destino:
            raise UserError(_("Dirección Destino sin ubigeo (ZIP)."))

        # ------------------------------------------------------------
        # Odoo 19 template restrictivo:
        # NO se puede agregar Despatch ni DeliveryTerms ni Delivery en InvoiceLine.
        # SÍ se puede asegurar Invoice/cac:Delivery/cac:DeliveryLocation/cac:Address/cbc:ID.
        #
        # Para evitar que otro proceso/estructura pise el valor, forzamos
        # el ORIGEN en TODOS los cac:Delivery existentes en cabecera.
        # ------------------------------------------------------------

        def _ensure_origin_deliverylocation(delivery_node):
            delivery_node.setdefault("cac:DeliveryLocation", {})
            delivery_node["cac:DeliveryLocation"].setdefault("cac:Address", {})

            addr_node = delivery_node["cac:DeliveryLocation"]["cac:Address"]

            # UBIGEO ORIGEN (lo que reclama el OSE)
            addr_node["cbc:ID"] = {"_text": ubigeo_origen}

            # opcional: línea de dirección y país (solo si el template lo permite, normalmente sí)
            addr_node.setdefault("cac:AddressLine", {})
            addr_node["cac:AddressLine"]["cbc:Line"] = {
                "_text": self._get_partner_address_line_simple(origin)
            }

            addr_node.setdefault("cac:Country", {})
            addr_node["cac:Country"]["cbc:IdentificationCode"] = {"_text": "PE"}

        delivery = document_node.get("cac:Delivery")

        if isinstance(delivery, list):
            # Forzar en todos
            for d in delivery:
                if isinstance(d, dict):
                    _ensure_origin_deliverylocation(d)
            # Mantener como lista
            document_node["cac:Delivery"] = delivery

        elif isinstance(delivery, dict):
            _ensure_origin_deliverylocation(delivery)
            document_node["cac:Delivery"] = delivery

        else:
            # Si no existía, lo creamos como dict
            delivery_node = {}
            _ensure_origin_deliverylocation(delivery_node)
            document_node["cac:Delivery"] = delivery_node

        _logger.info("[DETRACCION][HEADER] Forced ORIGEN in all header cac:Delivery nodes")
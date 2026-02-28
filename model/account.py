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

    def _get_partner_ubigeo(self, partner):
        return (partner.zip or "").strip() if partner else ""

    def _addr_line(self, partner):
        if not partner:
            return "-"
        return partner.street or partner.name or "-"

    def _add_invoice_line_amount_nodes(self, line_node, vals):
        # Este método SÍ se ejecuta en Odoo 19 (está en tu original).
        super()._add_invoice_line_amount_nodes(line_node, vals)

        invoice = vals["invoice"]                 # account.move
        op_type = invoice.l10n_pe_edi_operation_type or ""
        if op_type != "1004":
            return

        origin = invoice.direccion_origen
        dest = invoice.direccion_destino
        if not origin or not dest:
            raise UserError(_("Falta Dirección Origen/Destino para detracción 1004."))

        ubigeo_origen = self._get_partner_ubigeo(origin)
        ubigeo_destino = self._get_partner_ubigeo(dest)

        _logger.info("[DETRACCION][LINE_NODE] move=%s origen=%s destino=%s",
                        invoice.name, ubigeo_origen, ubigeo_destino)

        if not ubigeo_origen or not ubigeo_destino:
            raise UserError(_("Origen/Destino sin ubigeo (zip)."))

        # Inyecta Delivery dentro de InvoiceLine (line_node), que el template permite.
        line_node["cac:Delivery"] = [
            {
                "cac:Despatch": {
                    "cbc:Instructions": {"_text": "Flete Primario"},
                    "cac:DespatchAddress": {
                        "cbc:ID": {"_text": ubigeo_origen},
                        "cac:AddressLine": {"cbc:Line": {"_text": self._addr_line(origin)}},
                    },
                }
            },
            {
                "cac:DeliveryLocation": {
                    "cac:Address": {
                        "cbc:ID": {"_text": ubigeo_destino},
                        "cac:AddressLine": {"cbc:Line": {"_text": self._addr_line(dest)}},
                    }
                }
            },
        ]
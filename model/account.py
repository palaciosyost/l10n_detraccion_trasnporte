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

        
    def _get_invoice_line_vals(self, line):
        vals = super()._get_invoice_line_vals(line)
        move = line.move_id

        op_type = str(getattr(move, "l10n_pe_edi_operation_type", "") or "")
        if op_type != "1004":
            return vals

        origin = move.direccion_origen
        dest = move.direccion_destino
        if not origin or not dest:
            raise UserError(_("Falta Dirección Origen/Destino para detracción 1004."))

        ubigeo_origen = self._get_partner_ubigeo(origin)
        ubigeo_destino = self._get_partner_ubigeo(dest)

        _logger.warning("[DETRACCION][LINE] origen=%s destino=%s", ubigeo_origen, ubigeo_destino)

        if not ubigeo_origen or not ubigeo_destino:
            raise UserError(_("Origen/Destino sin ubigeo."))

        vals["cac:Delivery"] = [
            {
                "cac:Despatch": {
                    "cbc:Instructions": {"_text": "Flete Primario"},
                    "cac:DespatchAddress": {
                        "cbc:ID": {"_text": ubigeo_origen},
                        "cac:AddressLine": {"cbc:Line": {"_text": origin.street or origin.name or "-"}},
                    },
                }
            },
            {
                "cac:DeliveryLocation": {
                    "cac:Address": {
                        "cbc:ID": {"_text": ubigeo_destino},
                        "cac:AddressLine": {"cbc:Line": {"_text": dest.street or dest.name or "-"}},
                    }
                }
            },
        ]
        return vals
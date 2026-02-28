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
        """
        SOLO usa ZIP, pero lo deja apto para OSE:
        - toma solo dígitos del zip
        - devuelve hasta 6 dígitos (ubigeo)
        """
        if not partner or not partner.zip:
            return ""
        digits = "".join(ch for ch in str(partner.zip) if ch.isdigit())
        return digits[:6]  # ubigeo en Perú

    def _get_partner_address_line(self, partner):
        # simple y compatible con template
        if not partner:
            return "-"
        parts = [partner.street or "", partner.street2 or "", partner.city or ""]
        s = " ".join(p.strip() for p in parts if p and p.strip())
        return s or (partner.name or "-")

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

        _logger.info("[DETRACCION][LINE] origen=%s destino=%s", ubigeo_origen, ubigeo_destino)

        if not ubigeo_origen:
            raise UserError(_("Dirección Origen sin ubigeo en ZIP (debe contener dígitos)."))
        if not ubigeo_destino:
            raise UserError(_("Dirección Destino sin ubigeo en ZIP (debe contener dígitos)."))

        # IMPORTANTE: en InvoiceLine el template acepta Delivery con DeliveryLocation.
        # Para asegurar compatibilidad en Odoo 19, evita inventar nodos fuera del template.
        # (Si tu instancia permite Despatch en línea, lo dejamos. Si no, lo quitamos abajo.)
        vals["cac:Delivery"] = [
            {
                "cac:Despatch": {
                    "cbc:Instructions": {"_text": "Flete Primario"},
                    "cac:DespatchAddress": {
                        "cbc:ID": {"_text": ubigeo_origen},
                        "cac:AddressLine": {"cbc:Line": {"_text": self._get_partner_address_line(origin)}},
                    },
                }
            },
            {
                "cac:DeliveryLocation": {
                    "cac:Address": {
                        "cbc:ID": {"_text": ubigeo_destino},
                        "cac:AddressLine": {"cbc:Line": {"_text": self._get_partner_address_line(dest)}},
                    }
                }
            },
        ]

        return vals
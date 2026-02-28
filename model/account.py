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
        if not partner:
            return ""
        return partner.zip or ""

    def _get_partner_address_line_simple(self, partner):
        parts = [partner.street or "", partner.street2 or "", partner.city or ""]
        s = " ".join(p.strip() for p in parts if p and p.strip())
        return s or (partner.name or "-")

    def _get_invoice_node(self, vals):
        # 1) que Odoo arme TODO primero
        document_node = super()._get_invoice_node(vals)
        invoice = vals["invoice"]

        op_type = str(getattr(invoice, "l10n_pe_edi_operation_type", "") or "")
        if op_type != "1004":
            return document_node

        origin = invoice.direccion_origen
        dest = invoice.direccion_destino
        if not origin or not dest:
            raise UserError(_("Falta Dirección Origen/Destino para detracción 1004."))

        ubigeo_origen = self._get_partner_ubigeo(origin)
        ubigeo_destino = self._get_partner_ubigeo(dest)

        _logger.info("[DETRACCION][FINAL] ubigeo_origen=%s ubigeo_destino=%s", ubigeo_origen, ubigeo_destino)

        if not ubigeo_origen or not ubigeo_destino:
            raise UserError(_("Origen/Destino sin ubigeo."))

        # 2) REEMPLAZA al final para que quede sí o sí en el XML final
        document_node["cac:Delivery"] = [
            # ORIGEN
            {
                "cac:DeliveryLocation": {
                    "cac:Address": {
                        "cbc:ID": {"_text": ubigeo_origen},
                        "cac:AddressLine": {"cbc:Line": {"_text": self._get_partner_address_line_simple(origin)}},
                        "cac:Country": {"cbc:IdentificationCode": {"_text": "PE"}},
                    }
                },
                "cac:DeliveryTerms": {
                    "cbc:ID": {"_text": "01"},   # origen
                    "cbc:Amount": {"_text": self.format_float(invoice.amount_total, 2), "currencyID": invoice.currency_id.name},
                },
            },
            # DESTINO
            {
                "cac:DeliveryLocation": {
                    "cac:Address": {
                        "cbc:ID": {"_text": ubigeo_destino},
                        "cac:AddressLine": {"cbc:Line": {"_text": self._get_partner_address_line_simple(dest)}},
                        "cac:Country": {"cbc:IdentificationCode": {"_text": "PE"}},
                    }
                },
                "cac:DeliveryTerms": {
                    "cbc:ID": {"_text": "02"},   # destino
                    "cbc:Amount": {"_text": self.format_float(invoice.amount_total, 2), "currencyID": invoice.currency_id.name},
                },
            },
        ]        
        _logger.info("[DETRACCION][FINAL] Delivery set OK")
        return document_node
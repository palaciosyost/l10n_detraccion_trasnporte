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
    _description = "PE UBL 2.1 con Detracción Transporte"

    def _add_invoice_header_nodes(self, document_node, vals):
        super()._add_invoice_header_nodes(document_node, vals)
        invoice = vals["invoice"]

        op_type = str(getattr(invoice, "l10n_pe_edi_operation_type", "") or "")
        _logger.warning("[DETRACCION] %s op_type=%s", invoice.name, op_type)

        if op_type != "1004":
            return

        origin = invoice.direccion_origen
        dest = invoice.direccion_destino
        if not origin or not dest:
            raise UserError(_("Falta Dirección Origen/Destino para detracción (1004)."))

        ubigeo_origen = self._pe_get_partner_ubigeo(origin)
        ubigeo_destino = self._pe_get_partner_ubigeo(dest)

        if not ubigeo_origen:
            raise UserError(_("La Dirección Origen no tiene UBIGEO configurado (distrito)."))
        if not ubigeo_destino:
            raise UserError(_("La Dirección Destino no tiene UBIGEO configurado (distrito)."))

        deliveries = [
            {
                "cac:Despatch": {
                    "cbc:Instructions": {"_text": "Punto de Origen"},
                    "cac:DespatchAddress": {
                        "cbc:ID": {"_text": ubigeo_origen},
                        "cac:AddressLine": {"cbc:Line": {"_text": self._pe_get_partner_address_line(origin)}},
                        "cac:Country": {"cbc:IdentificationCode": {"_text": "PE"}},
                    },
                }
            },
            {
                "cac:DeliveryLocation": {
                    "cac:Address": {
                        "cbc:ID": {"_text": ubigeo_destino},
                        "cac:AddressLine": {"cbc:Line": {"_text": self._pe_get_partner_address_line(dest)}},
                        "cac:Country": {"cbc:IdentificationCode": {"_text": "PE"}},
                    }
                }
            },
        ]

        # Igual que en tu retención: aseguras lista y lo metes en header
        document_node.setdefault("cac:Delivery", [])
        if not isinstance(document_node["cac:Delivery"], list):
            document_node["cac:Delivery"] = [document_node["cac:Delivery"]]

        # OJO: para evitar que el OSE lea primero un Delivery viejo, puedes reemplazar:
        document_node["cac:Delivery"] = deliveries
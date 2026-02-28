import logging
from odoo import models, fields, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    direccion_origen = fields.Many2one("res.partner", string="Dirección Origen")
    direccion_destino = fields.Many2one("res.partner", string="Dirección Destino")


class AccountEdiXmlUblPe(models.AbstractModel):
    _inherit = "account.edi.xml.ubl_pe"

    def _get_invoice_vals(self, move):
        vals = super()._get_invoice_vals(move)

        operation_type = str(getattr(move, "l10n_pe_edi_operation_type", "") or "")
        _logger.warning("[DETRACCION][HEAD] move=%s op_type=%s", move.name, operation_type)

        # Solo para Transporte de carga sujeto a detracción (Cat. 51 = 1004)
        if operation_type != "1004":
            return vals

        origin_partner = move.direccion_origen
        dest_partner = move.direccion_destino

        if not origin_partner or not dest_partner:
            raise UserError(_("Falta Dirección Origen o Dirección Destino para detracción (Transporte de carga)."))

        ubigeo_origen = self._pe_get_partner_ubigeo(origin_partner)
        ubigeo_destino = self._pe_get_partner_ubigeo(dest_partner)

        _logger.warning("[DETRACCION][HEAD] ubigeo_origen=%s ubigeo_destino=%s", ubigeo_origen, ubigeo_destino)

        if not ubigeo_origen:
            raise UserError(_("Falta UBIGEO de la Dirección Origen (detracción transporte de carga)."))
        if not ubigeo_destino:
            raise UserError(_("Falta UBIGEO de la Dirección Destino (detracción transporte de carga)."))

        deliveries = [
            # ORIGEN (DespatchAddress)
            {
                "cac:Despatch": {
                    "cbc:Instructions": {"_text": "Punto de Origen"},
                    "cac:DespatchAddress": {
                        "cbc:ID": {"_text": ubigeo_origen},
                        "cac:AddressLine": {
                            "cbc:Line": {"_text": self._pe_get_partner_address_line(origin_partner)}
                        },
                        "cac:Country": {"cbc:IdentificationCode": {"_text": "PE"}},
                    },
                }
            },
            # DESTINO (DeliveryLocation/Address)
            {
                "cac:DeliveryLocation": {
                    "cac:Address": {
                        "cbc:ID": {"_text": ubigeo_destino},
                        "cac:AddressLine": {
                            "cbc:Line": {"_text": self._pe_get_partner_address_line(dest_partner)}
                        },
                        "cac:Country": {"cbc:IdentificationCode": {"_text": "PE"}},
                    }
                }
            },
        ]

        # CLAVE: va en CABECERA, no en líneas
        # Si ya existía, lo reemplazamos para evitar que el OSE lea otro "Delivery" primero.
        vals["cac:Delivery"] = deliveries
        _logger.warning("[DETRACCION][HEAD] Set cac:Delivery=%s", deliveries)

        return vals
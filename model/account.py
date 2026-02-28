import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    direccion_origen = fields.Many2one("res.partner", string="Dirección Origen")
    direccion_destino = fields.Many2one("res.partner", string="Dirección Destino")


class AccountEdiXmlUblPe(models.AbstractModel):
    _inherit = "account.edi.xml.ubl_pe"

    def _get_invoice_line_vals(self, line):
        vals = super()._get_invoice_line_vals(line)
        move = line.move_id

        operation_type = str(getattr(move, "l10n_pe_edi_operation_type", "") or "")
        _logger.warning("[DETRACCION] line=%s move=%s op_type=%s", line.id, move.name, operation_type)

        if operation_type != "1004":
            return vals

        origin_partner = move.direccion_origen
        dest_partner = move.direccion_destino

        ubigeo_origen = self._pe_get_partner_ubigeo(origin_partner)
        ubigeo_destino = self._pe_get_partner_ubigeo(dest_partner)

        _logger.warning("[DETRACCION] ubigeo_origen=%s ubigeo_destino=%s", ubigeo_origen, ubigeo_destino)

        # IMPORTANTE: si el OSE exige origen, no dejes que quede vacío
        # Si quieres forzar error cuando falte:
        # if not ubigeo_origen:
        #     raise UserError("Falta Ubigeo Origen para detracción/transporte.")

        deliveries = []

        # ORIGEN (DespatchAddress)
        if ubigeo_origen:
            deliveries.append({
                "cac:Despatch": {
                    "cbc:Instructions": {"_text": "Punto de Origen"},
                    "cac:DespatchAddress": {
                        "cbc:ID": {"_text": ubigeo_origen},
                        "cac:AddressLine": {"cbc:Line": {"_text": self._pe_get_partner_address_line(origin_partner)}},
                        "cac:Country": {"cbc:IdentificationCode": {"_text": "PE"}},
                    }
                }
            })

        # DESTINO (DeliveryLocation/Address)
        if ubigeo_destino:
            deliveries.append({
                "cac:DeliveryLocation": {
                    "cac:Address": {
                        "cbc:ID": {"_text": ubigeo_destino},
                        "cac:AddressLine": {"cbc:Line": {"_text": self._pe_get_partner_address_line(dest_partner)}},
                        "cac:Country": {"cbc:IdentificationCode": {"_text": "PE"}},
                    }
                }
            })

        if deliveries:
            # CLAVE: en el dict del line vals debe ir con prefijo
            vals["cac:Delivery"] = deliveries
            _logger.warning("[DETRACCION] Agregando cac:Delivery=%s", deliveries)

        return vals
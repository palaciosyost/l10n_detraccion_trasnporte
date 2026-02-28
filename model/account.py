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
    _description = "PE UBL 2.1 - Detracción Transporte"

    def _get_partner_ubigeo(self, partner):
        """Retorna cualquier valor de ubigeo disponible (string) o ''."""
        if not partner:
            return ""

        district = getattr(partner, "l10n_pe_district_id", False)
        if district:
            # Devuelve lo primero que exista (sin validar longitud)
            for attr in ("code", "l10n_pe_code", "ubigeo", "name"):
                val = getattr(district, attr, "")
                if val:
                    return str(val).strip()

        for attr in ("l10n_pe_ubigeo", "ubigeo", "zip"):
            val = getattr(partner, attr, "")
            if val:
                return str(val).strip()

        return ""

    def _get_partner_address_line_simple(self, partner):
        parts = []
        if partner.street:
            parts.append(partner.street)
        if partner.street2:
            parts.append(partner.street2)
        if partner.city:
            parts.append(partner.city)
        return " ".join(p.strip() for p in parts if p and p.strip()) or (partner.name or "-")

    def _add_invoice_header_nodes(self, document_node, vals):
        super()._add_invoice_header_nodes(document_node, vals)
        invoice = vals["invoice"]

        op_type = str(getattr(invoice, "l10n_pe_edi_operation_type", "") or "")
        _logger.warning("[DETRACCION] move=%s op_type=%s", invoice.name, op_type)

        if op_type != "1004":
            return

        origin = invoice.direccion_origen
        dest = invoice.direccion_destino
        if not origin or not dest:
            raise UserError(_("Falta Dirección Origen/Destino en la pestaña Detracción."))

        ubigeo_origen = self._get_partner_ubigeo(origin)
        ubigeo_destino = self._get_partner_ubigeo(dest)

        _logger.warning("[DETRACCION] ubigeo_origen=%s ubigeo_destino=%s", ubigeo_origen, ubigeo_destino)

        # SOLO validar existencia (no formato)
        if not ubigeo_origen:
            raise UserError(_("La Dirección Origen no tiene UBIGEO configurado."))
        if not ubigeo_destino:
            raise UserError(_("La Dirección Destino no tiene UBIGEO configurado."))

        document_node["cac:Delivery"] = [
            {
                "cac:Despatch": {
                    "cbc:Instructions": {"_text": "Punto de Origen"},
                    "cac:DespatchAddress": {
                        "cbc:ID": {"_text": ubigeo_origen},
                        "cac:AddressLine": {"cbc:Line": {"_text": self._get_partner_address_line_simple(origin)}},
                        "cac:Country": {"cbc:IdentificationCode": {"_text": "PE"}},
                    },
                }
            },
            {
                "cac:DeliveryLocation": {
                    "cac:Address": {
                        "cbc:ID": {"_text": ubigeo_destino},
                        "cac:AddressLine": {"cbc:Line": {"_text": self._get_partner_address_line_simple(dest)}},
                        "cac:Country": {"cbc:IdentificationCode": {"_text": "PE"}},
                    }
                }
            },
        ]
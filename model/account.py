import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    direccion_origen = fields.Many2one("res.partner", string="Dirección Origen")
    direccion_destino = fields.Many2one("res.partner", string="Dirección Destino")


class AccountEdiXmlUblPe(models.AbstractModel):
    _inherit = "account.edi.xml.ubl_pe"

    # ---- helpers ----
    def _pe_get_partner_ubigeo(self, partner):
        """Devuelve ubigeo 6 dígitos desde partner (ajusta según tu modelo)."""
        _logger.info("[UBL_PE] _pe_get_partner_ubigeo() partner=%s (%s)",
                     partner.id if partner else None,
                     partner.display_name if partner else None)

        if not partner:
            _logger.info("[UBL_PE] partner vacío -> ubigeo=False")
            return False

        district = getattr(partner, "l10n_pe_district_id", False)
        _logger.info("[UBL_PE] partner.l10n_pe_district_id=%s",
                     district.id if district else None)

        if district and getattr(district, "code", False):
            _logger.info("[UBL_PE] ubigeo desde district.code=%s", district.code)
            return district.code

        if getattr(partner, "l10n_pe_ubigeo", False):
            _logger.info("[UBL_PE] ubigeo desde partner.l10n_pe_ubigeo=%s", partner.l10n_pe_ubigeo)
            return partner.l10n_pe_ubigeo

        if getattr(partner, "zip", False):
            _logger.info("[UBL_PE] partner.zip=%s", partner.zip)
            if str(partner.zip).isdigit() and len(str(partner.zip)) == 6:
                _logger.info("[UBL_PE] ubigeo desde zip=%s", str(partner.zip))
                return str(partner.zip)

        _logger.info("[UBL_PE] no se encontró ubigeo -> False")
        return False

    def _pe_get_partner_address_line(self, partner):
        """Texto de dirección para AddressLine/Line."""
        _logger.info("[UBL_PE] _pe_get_partner_address_line() partner=%s (%s)",
                     partner.id if partner else None,
                     partner.display_name if partner else None)

        if not partner:
            _logger.info("[UBL_PE] partner vacío -> address_line=''")
            return ""

        address_line = partner.street or partner.contact_address or partner.name or ""
        _logger.info("[UBL_PE] address_line='%s'", address_line)
        return address_line

    # ---- override ----
    def _get_invoice_line_vals(self, line):
        _logger.info("[UBL_PE] _get_invoice_line_vals() line_id=%s move_id=%s",
                     line.id if line else None,
                     line.move_id.id if line and line.move_id else None)

        vals = super()._get_invoice_line_vals(line)
        move = line.move_id

        operation_type = str(getattr(move, "l10n_pe_edi_operation_type", "") or "")
        _logger.info("[UBL_PE] move=%s operation_type=%s", move.name, operation_type)

        # SOLO cuando sea operación 1004 (detracción)
        if operation_type != "1004":
            _logger.info("[UBL_PE] operation_type != 1004 -> no se agrega Delivery")
            return vals

        origin_partner = move.direccion_origen
        dest_partner = move.direccion_destino

        _logger.info("[UBL_PE] origen partner=%s (%s) | destino partner=%s (%s)",
                     origin_partner.id if origin_partner else None,
                     origin_partner.display_name if origin_partner else None,
                     dest_partner.id if dest_partner else None,
                     dest_partner.display_name if dest_partner else None)

        ubigeo_origen = self._pe_get_partner_ubigeo(origin_partner)
        ubigeo_destino = self._pe_get_partner_ubigeo(dest_partner)

        _logger.info("[UBL_PE] ubigeo_origen=%s ubigeo_destino=%s", ubigeo_origen, ubigeo_destino)

        # Si no hay ubigeos, no generes nada (evita XML inválido)
        if not ubigeo_origen and not ubigeo_destino:
            _logger.info("[UBL_PE] no hay ubigeos -> no se agrega Delivery")
            return vals

        deliveries = []

        # ORIGEN
        if ubigeo_origen:
            origin_line = self._pe_get_partner_address_line(origin_partner)
            deliveries.append({
                "Despatch": {
                    "DespatchAddress": {
                        "ID": ubigeo_origen,
                        "AddressLine": {"Line": origin_line},
                        "Country": {"IdentificationCode": "PE"},
                    }
                }
            })
            _logger.info("[UBL_PE] Delivery ORIGEN agregado: ubigeo=%s addr='%s'", ubigeo_origen, origin_line)
        else:
            _logger.info("[UBL_PE] ORIGEN sin ubigeo -> no se agrega DespatchAddress")

        # DESTINO
        if ubigeo_destino:
            dest_line = self._pe_get_partner_address_line(dest_partner)
            deliveries.append({
                "DeliveryLocation": {
                    "Address": {
                        "ID": ubigeo_destino,
                        "AddressLine": {"Line": dest_line},
                        "Country": {"IdentificationCode": "PE"},
                    }
                }
            })
            _logger.info("[UBL_PE] Delivery DESTINO agregado: ubigeo=%s addr='%s'", ubigeo_destino, dest_line)
        else:
            _logger.info("[UBL_PE] DESTINO sin ubigeo -> no se agrega DeliveryLocation")

        vals["Delivery"] = deliveries
        _logger.info("[UBL_PE] vals['Delivery'] final=%s", deliveries)

        return vals
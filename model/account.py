from odoo import models, fields


class AccountMove(models.Model):
    _inherit = "account.move"

    direccion_origen = fields.Many2one("res.partner", string="Dirección Origen")
    direccion_destino = fields.Many2one("res.partner", string="Dirección Destino")


class AccountEdiXmlUblPe(models.AbstractModel):
    _inherit = "account.edi.xml.ubl_pe"

    # ---- helpers ----
    def _pe_get_partner_ubigeo(self, partner):
        """Devuelve ubigeo 6 dígitos desde partner (ajusta según tu modelo)."""
        if not partner:
            return False

        # Caso común: distrito con code
        district = getattr(partner, "l10n_pe_district_id", False)
        if district and getattr(district, "code", False):
            return district.code

        # Alternativas comunes en algunos módulos
        if getattr(partner, "l10n_pe_ubigeo", False):
            return partner.l10n_pe_ubigeo
        if getattr(partner, "zip", False) and str(partner.zip).isdigit() and len(str(partner.zip)) == 6:
            return str(partner.zip)

        return False

    def _pe_get_partner_address_line(self, partner):
        """Texto de dirección para AddressLine/Line."""
        if not partner:
            return ""
        # contact_address ya viene formateado; si prefieres solo street, usa partner.street
        return partner.street or partner.contact_address or partner.name or ""

    # ---- override ----
    def _get_invoice_line_vals(self, line):
        vals = super()._get_invoice_line_vals(line)
        move = line.move_id

        # SOLO cuando sea operación 1004 (detracción)
        if str(getattr(move, "l10n_pe_edi_operation_type", "")) != "1004":
            return vals

        origin_partner = move.direccion_origen
        dest_partner = move.direccion_destino

        ubigeo_origen = self._pe_get_partner_ubigeo(origin_partner)
        ubigeo_destino = self._pe_get_partner_ubigeo(dest_partner)

        # Si no hay ubigeos, no generes nada (evita XML inválido)
        if not ubigeo_origen and not ubigeo_destino:
            return vals

        deliveries = []

        # ORIGEN
        if ubigeo_origen:
            deliveries.append({
                "Despatch": {
                    "DespatchAddress": {
                        "ID": ubigeo_origen,  # cbc:ID
                        "AddressLine": {"Line": self._pe_get_partner_address_line(origin_partner)},
                        "Country": {"IdentificationCode": "PE"},
                    }
                }
            })

        # DESTINO
        if ubigeo_destino:
            deliveries.append({
                "DeliveryLocation": {
                    "Address": {
                        "ID": ubigeo_destino,  # cbc:ID
                        "AddressLine": {"Line": self._pe_get_partner_address_line(dest_partner)},
                        "Country": {"IdentificationCode": "PE"},
                    }
                }
            })

        # Inserta en la línea
        vals["Delivery"] = deliveries

        return vals
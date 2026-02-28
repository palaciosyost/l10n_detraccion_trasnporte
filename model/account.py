import logging
from lxml import etree

from odoo import models, fields, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    direccion_origen = fields.Many2one("res.partner", string="Dirección Origen")
    direccion_destino = fields.Many2one("res.partner", string="Dirección Destino")


class AccountEdiXmlUblPeDetraccion(models.AbstractModel):
    _inherit = "account.edi.xml.ubl_pe"

    # Getter puro: SOLO ZIP (UBIGEO)
    def _get_partner_ubigeo(self, partner):
        return (partner.zip or "").strip() if partner else ""

    def _get_partner_address_line_simple(self, partner):
        if not partner:
            return "-"
        return partner.street or partner.name or "-"

    def _export_invoice(self, invoice):
        xml_content, errors = super()._export_invoice(invoice)

        op_type = str(getattr(invoice, "l10n_pe_edi_operation_type", "") or "")
        if op_type != "1004":
            return xml_content, errors

        origin = invoice.direccion_origen
        dest = invoice.direccion_destino
        if not origin or not dest:
            raise UserError(_("Falta Dirección Origen/Destino para detracción 1004."))

        ubigeo_origen = self._get_partner_ubigeo(origin)
        ubigeo_destino = self._get_partner_ubigeo(dest)
        if not ubigeo_origen or not ubigeo_destino:
            raise UserError(_("Origen/Destino sin ubigeo (ZIP)."))

        _logger.info(
            "[DETRACCION][POSTXML] move=%s ubigeo_origen=%s ubigeo_destino=%s",
            invoice.name, ubigeo_origen, ubigeo_destino
        )

        # Normalizar a bytes
        if isinstance(xml_content, str):
            xml_bytes = xml_content.encode("utf-8")
            return_str = True
        else:
            xml_bytes = xml_content
            return_str = False

        root = etree.fromstring(xml_bytes)

        ns = {
            "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
            "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
            "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
        }

        def make_delivery_origin():
            delivery_el = etree.Element(f"{{{ns['cac']}}}Delivery")
            despatch_el = etree.SubElement(delivery_el, f"{{{ns['cac']}}}Despatch")

            instr_el = etree.SubElement(despatch_el, f"{{{ns['cbc']}}}Instructions")
            instr_el.text = "Flete Primario"

            despatch_addr_el = etree.SubElement(despatch_el, f"{{{ns['cac']}}}DespatchAddress")

            ub_el = etree.SubElement(despatch_addr_el, f"{{{ns['cbc']}}}ID")
            ub_el.text = ubigeo_origen

            addr_line_el = etree.SubElement(despatch_addr_el, f"{{{ns['cac']}}}AddressLine")
            line_el = etree.SubElement(addr_line_el, f"{{{ns['cbc']}}}Line")
            line_el.text = self._get_partner_address_line_simple(origin)

            return delivery_el

        def make_delivery_dest():
            delivery_el = etree.Element(f"{{{ns['cac']}}}Delivery")
            dl_el = etree.SubElement(delivery_el, f"{{{ns['cac']}}}DeliveryLocation")
            addr_el = etree.SubElement(dl_el, f"{{{ns['cac']}}}Address")

            ub_el = etree.SubElement(addr_el, f"{{{ns['cbc']}}}ID")
            ub_el.text = ubigeo_destino

            addr_line_el = etree.SubElement(addr_el, f"{{{ns['cac']}}}AddressLine")
            line_el = etree.SubElement(addr_line_el, f"{{{ns['cbc']}}}Line")
            line_el.text = self._get_partner_address_line_simple(dest)

            return delivery_el

        def make_delivery_terms(code, amount, currency):
            delivery_el = etree.Element(f"{{{ns['cac']}}}Delivery")
            dt_el = etree.SubElement(delivery_el, f"{{{ns['cac']}}}DeliveryTerms")

            id_el = etree.SubElement(dt_el, f"{{{ns['cbc']}}}ID")
            id_el.text = str(code)

            amt_el = etree.SubElement(dt_el, f"{{{ns['cbc']}}}Amount")
            amt_el.text = f"{amount:.2f}"
            amt_el.set("currencyID", currency)

            return delivery_el

        inv_lines = root.findall("cac:InvoiceLine", namespaces=ns)
        if not inv_lines:
            new_xml_bytes = etree.tostring(root, encoding="UTF-8", xml_declaration=False)
            return (new_xml_bytes.decode("utf-8"), errors) if return_str else (new_xml_bytes, errors)

        # Limpieza: quitar Deliveries anteriores para evitar duplicados
        for line_el in inv_lines:
            for d in line_el.findall("cac:Delivery", namespaces=ns):
                line_el.remove(d)

        for idx, line_el in enumerate(inv_lines):
            tax_total = line_el.find("cac:TaxTotal", namespaces=ns)
            pos = line_el.index(tax_total) if tax_total is not None else len(line_el)

            # ORIGEN + DESTINO (si tu OSE lo quiere por línea, se mantiene)
            line_el.insert(pos, make_delivery_origin())
            line_el.insert(pos + 1, make_delivery_dest())

            # Valores referenciales SOLO en la primera línea (para cumplir "uno y solo uno")
            if idx == 0:
                total = invoice.amount_total
                curr = invoice.currency_id.name

                # 01: Servicio de Transporte
                line_el.insert(pos + 2, make_delivery_terms("01", total, curr))
                # 02: Carga Efectiva
                line_el.insert(pos + 3, make_delivery_terms("02", total, curr))
                # 03: Carga Útil Nominal  ✅ (lo que te pide 3126)
                line_el.insert(pos + 4, make_delivery_terms("03", total, curr))

                _logger.info("[DETRACCION] DeliveryTerms 01/02/03 inserted once (line 1).")

        new_xml_bytes = etree.tostring(root, encoding="UTF-8", xml_declaration=False)
        return (new_xml_bytes.decode("utf-8"), errors) if return_str else (new_xml_bytes, errors)
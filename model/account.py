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
    """
    Odoo 19 (account_edi_ubl_cii / l10n_pe_edi) tiene templates UBL restrictivos.
    Para transporte con detracción (op_type=1004), el OSE exige:
      - Ubigeo punto de ORIGEN en Delivery/Despatch/DespatchAddress/ID
      - Ubigeo punto de DESTINO en Delivery/DeliveryLocation/Address/ID
      - Un (y solo uno) Valor Referencial del Servicio de Transporte (DeliveryTerms ID=01 con Amount)
    Como Odoo bloquea esos nodos por template, los inyectamos por post-proceso del XML final.
    """
    _inherit = "account.edi.xml.ubl_pe"

    # Getter puro: SOLO ZIP (como pediste)
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

        # Parse XML
        root = etree.fromstring(xml_bytes)

        ns = {
            "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
            "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
            "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
        }

        # ------------------------
        # Builders de nodos
        # ------------------------

        def make_delivery_origin():
            # <cac:Delivery><cac:Despatch><cac:DespatchAddress><cbc:ID>UBIGEO</cbc:ID>...
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

            # Country opcional
            country_el = etree.SubElement(despatch_addr_el, f"{{{ns['cac']}}}Country")
            cc_el = etree.SubElement(country_el, f"{{{ns['cbc']}}}IdentificationCode")
            cc_el.text = "PE"

            return delivery_el

        def make_delivery_dest():
            # <cac:Delivery><cac:DeliveryLocation><cac:Address><cbc:ID>UBIGEO</cbc:ID>...
            delivery_el = etree.Element(f"{{{ns['cac']}}}Delivery")
            dl_el = etree.SubElement(delivery_el, f"{{{ns['cac']}}}DeliveryLocation")
            addr_el = etree.SubElement(dl_el, f"{{{ns['cac']}}}Address")

            ub_el = etree.SubElement(addr_el, f"{{{ns['cbc']}}}ID")
            ub_el.text = ubigeo_destino

            addr_line_el = etree.SubElement(addr_el, f"{{{ns['cac']}}}AddressLine")
            line_el = etree.SubElement(addr_line_el, f"{{{ns['cbc']}}}Line")
            line_el.text = self._get_partner_address_line_simple(dest)

            # Country opcional
            country_el = etree.SubElement(addr_el, f"{{{ns['cac']}}}Country")
            cc_el = etree.SubElement(country_el, f"{{{ns['cbc']}}}IdentificationCode")
            cc_el.text = "PE"

            return delivery_el

        def make_delivery_terms_01():
            # Un (y solo uno) "Valor Referencial del Servicio de Transporte"
            # Lo expresamos como <cac:Delivery><cac:DeliveryTerms><cbc:ID>01</cbc:ID><cbc:Amount ...>
            delivery_el = etree.Element(f"{{{ns['cac']}}}Delivery")
            dt_el = etree.SubElement(delivery_el, f"{{{ns['cac']}}}DeliveryTerms")

            id_el = etree.SubElement(dt_el, f"{{{ns['cbc']}}}ID")
            id_el.text = "01"

            amt_el = etree.SubElement(dt_el, f"{{{ns['cbc']}}}Amount")
            # Por defecto usamos TOTAL factura. Si tu OSE pide base sin IGV, cambia a invoice.amount_untaxed
            amt_el.text = f"{invoice.amount_total:.2f}"
            amt_el.set("currencyID", invoice.currency_id.name)

            return delivery_el

        # ------------------------
        # Inserción en InvoiceLine (orden válido UBL)
        # ------------------------

        inv_lines = root.findall("cac:InvoiceLine", namespaces=ns)
        if not inv_lines:
            new_xml_bytes = etree.tostring(root, encoding="UTF-8", xml_declaration=False)
            return (new_xml_bytes.decode("utf-8"), errors) if return_str else (new_xml_bytes, errors)

        # 0) Remover cualquier DeliveryTerms existente para evitar duplicados
        for line_el in inv_lines:
            for d in line_el.findall("cac:Delivery", namespaces=ns):
                # eliminar solo DeliveryTerms dentro de Delivery (si existiera)
                for dt in d.findall("cac:DeliveryTerms", namespaces=ns):
                    d.remove(dt)

        for idx, line_el in enumerate(inv_lines):
            # 1) Remove deliveries previos (para que quede limpio y no multiplique)
            for d in line_el.findall("cac:Delivery", namespaces=ns):
                line_el.remove(d)

            # 2) Posición segura por orden UBL: antes de cac:TaxTotal
            tax_total = line_el.find("cac:TaxTotal", namespaces=ns)
            pos = line_el.index(tax_total) if tax_total is not None else len(line_el)

            # 3) Insertar ORIGEN y DESTINO
            line_el.insert(pos, make_delivery_origin())
            line_el.insert(pos + 1, make_delivery_dest())

            # 4) Insertar SOLO UNA VEZ el Valor Referencial (ID=01)
            if idx == 0:
                line_el.insert(pos + 2, make_delivery_terms_01())

        # Serializar
        new_xml_bytes = etree.tostring(root, encoding="UTF-8", xml_declaration=False)
        return (new_xml_bytes.decode("utf-8"), errors) if return_str else (new_xml_bytes, errors)
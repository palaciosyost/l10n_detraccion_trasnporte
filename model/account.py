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
    Odoo 19: el template UBL bloquea agregar cac:Despatch/DespatchAddress con dict_to_xml.
    Por eso, aquí post-procesamos el XML ya generado y le inyectamos el bloque requerido
    por el OSE para detracción de transporte (1004) ANTES de la firma.
    """
    _inherit = "account.edi.xml.ubl_pe"

    # Getter puro: SOLO ZIP
    def _get_partner_ubigeo(self, partner):
        return (partner.zip or "").strip() if partner else ""

    def _get_partner_address_line_simple(self, partner):
        if not partner:
            return "-"
        return partner.street or partner.name or "-"

    def _export_invoice(self, invoice):
        """
        Devuelve (xml_content, errors). Aquí:
        1) Llamamos al export original
        2) Si op_type=1004, inyectamos:
           Invoice/cac:Delivery/cac:Despatch/cac:DespatchAddress/cbc:ID = ubigeo_origen
        """
        xml_content, errors = super()._export_invoice(invoice)

        try:
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

            # --- parse XML ---
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

            # --- construir Delivery/Despatch/DespatchAddress ---
            delivery_el = etree.Element(f"{{{ns['cac']}}}Delivery")

            despatch_el = etree.SubElement(delivery_el, f"{{{ns['cac']}}}Despatch")

            instr_el = etree.SubElement(despatch_el, f"{{{ns['cbc']}}}Instructions")
            instr_el.text = "Punto de Origen"

            despatch_addr_el = etree.SubElement(despatch_el, f"{{{ns['cac']}}}DespatchAddress")

            ub_el = etree.SubElement(despatch_addr_el, f"{{{ns['cbc']}}}ID")
            ub_el.text = ubigeo_origen

            addr_line_el = etree.SubElement(despatch_addr_el, f"{{{ns['cac']}}}AddressLine")
            line_el = etree.SubElement(addr_line_el, f"{{{ns['cbc']}}}Line")
            line_el.text = self._get_partner_address_line_simple(origin)

            # País (muchos OSE lo toleran opcional; lo ponemos)
            country_el = etree.SubElement(despatch_addr_el, f"{{{ns['cac']}}}Country")
            cc_el = etree.SubElement(country_el, f"{{{ns['cbc']}}}IdentificationCode")
            cc_el.text = "PE"

            # --- insertar el bloque en CABECERA ---
            # Lo insertamos justo después de AccountingCustomerParty si existe; si no, lo agregamos al inicio.
            customer_node = root.find("cac:AccountingCustomerParty", namespaces=ns)
            if customer_node is not None:
                idx = root.index(customer_node)
                root.insert(idx + 1, delivery_el)
            else:
                root.insert(0, delivery_el)

            # --- serializar ---
            new_xml_bytes = etree.tostring(root, encoding="UTF-8", xml_declaration=False)

            if return_str:
                return new_xml_bytes.decode("utf-8"), errors
            return new_xml_bytes, errors

        except UserError:
            # UserError debe propagarse
            raise
        except Exception as e:
            # No rompas la facturación por un post-proceso: log y devuelve original
            _logger.exception("[DETRACCION][POSTXML] Error in post-processing XML: %s", e)
            return xml_content, errors
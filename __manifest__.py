{
    'name': 'Operacion sujeta a detraccion / trasnporte de carga',
    'version': '1.0',
    'description': 'Operaciones sujetas a deraccion en Perú y pagos de retención y detracción',
    'author': 'Kauza Digital',
    'website': 'https://www.kauzadigital.com',
    'license': 'LGPL-3',
    'category': 'accounting',
    'depends': [
        'base', 'l10n_pe_edi', 'account', 'l10n_pe'
    ],
    'data': [
        "view/view_form_account_move.xml",
    ],
    'auto_install': False,
    'application': False,
}
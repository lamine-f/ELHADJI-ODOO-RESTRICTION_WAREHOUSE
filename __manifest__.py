{
    'name': 'Restriction Entrepot',
    'version': '1.8',
    'description': "Module de restriction d'entrepôt",
    'author': 'TOFTAL',
    'category': 'Inventory',
    'depends': ['base', 'stock'],
    'data': [
        'security/stock_restrict_destination_view_security.xml',
        'security/ir.model.access.csv',
        'views/res_users_view.xml',
    'views/stock_restrict_destination_view.xml',
        'views/stock_location_view.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
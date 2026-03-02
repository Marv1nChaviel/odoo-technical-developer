# -*- coding: utf-8 -*-
{
    'name': 'Predictive Maintenance Pro',
    'version': '18.0.1.0.0',
    'category': 'Maintenance',
    'summary': 'Mantenimiento predictivo para flotas basado en km/horas/dias',
    'description': """
        Modulo para la gestion de mantenimiento predictivo para flotas de vehiculos y maquinaria pesada.
        ==========================
        Módulo para la gestión de mantenimiento preventivo y predictivo de flotas de vehiculos y maquinaria pesada.
        Permite:

        - Crear planes de mantenimiento con umbrales dinámicos (km, horas, dias)
        - Generar órdenes de mantenimiento automáticamente al superar umbrales
        - Controlar el consumo de repuestos y materiales por orden
        - Comparar costos planificados vs reales
        - Mantener un historial completo de reemplazos y servicios
        - Gestionar roles: Coordinador, Técnico y Compras
    """,
    'author': 'Marv1nChaviel',
    'website': 'https://github.com/Marv1nChaviel/tecnical_test',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'fleet',
        'maintenance',
        'stock',
        'purchase',
        'mail',
        'product',
    ],
    'data': [
        # Security
        'security/res_groups.xml',
        'security/ir.model.access.csv',
        'security/ir_rules.xml',
        # Data
        'data/sequence_data.xml',
        'data/cron.xml',
        # Views
        'views/maintenance_plan_views.xml',
        'views/maintenance_order_views.xml',
        'views/maintenance_history_views.xml',
        'views/fleet_vehicle_views.xml',
        'views/pmp_dashboard_views.xml',
        # Wizards
        'wizards/generate_orders_wizard_views.xml',
        'wizards/parts_shortage_wizard_views.xml',
        # Reports
        'reports/maintenance_order_report.xml',
        # Menus (always last — all actions must exist first)
        'views/menus.xml',
    ],
    'demo': [
        'demo/demo_data.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}

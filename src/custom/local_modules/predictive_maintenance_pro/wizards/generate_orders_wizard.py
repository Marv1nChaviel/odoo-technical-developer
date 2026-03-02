# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class GenerateOrdersWizard(models.TransientModel):
    """
    Wizard para la generación masiva de órdenes de mantenimiento.

    Permite al coordinador seleccionar un conjunto de vehículos y ejecutar
    manualmente la verificación de umbrales, generando todas las órdenes
    pendientes en una sola operación.
    """

    _name = 'pmp.generate.orders.wizard'
    _description = 'Generar Órdenes de Mantenimiento'

    # -------------------------------------------------------------------------
    # Campos de filtrado
    # -------------------------------------------------------------------------
    vehicle_ids = fields.Many2many(
        comodel_name='fleet.vehicle',
        relation='pmp_wizard_vehicle_rel',
        column1='wizard_id',
        column2='vehicle_id',
        string='Vehículos',
        help='Dejar vacío para procesar TODOS los vehículos activos.',
    )
    only_overdue = fields.Boolean(
        string='Solo Vehículos con Umbral Superado',
        default=True,
        help='Si está activo, solo genera órdenes para vehículos cuyo umbral haya sido superado.',
    )

    # Resultados (readonly, post-ejecución)
    orders_created_count = fields.Integer(
        string='Órdenes Creadas',
        readonly=True,
        default=0,
    )
    result_message = fields.Char(
        string='Resultado',
        readonly=True,
    )

    # -------------------------------------------------------------------------
    # Acción principal
    # -------------------------------------------------------------------------
    def action_generate_orders(self):
        """
        Ejecuta la verificación de umbrales y genera las órdenes correspondientes.

        Returns:
            dict: Acción para mostrar el resultado o las órdenes creadas.
        """
        self.ensure_one()

        vehicles = self.vehicle_ids or self.env['fleet.vehicle'].search(
            [('active', '=', True)]
        )

        created_orders = vehicles._check_maintenance_alerts()
        count = len(created_orders)

        self.write({
            'orders_created_count': count,
            'result_message': _(
                'Se generaron %d órdenes de mantenimiento.'
            ) % count,
        })

        _logger.info(
            'PMP Wizard: %d órdenes generadas para %d vehículos.',
            count,
            len(vehicles),
        )

        if count > 0:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Órdenes Generadas'),
                'res_model': 'pmp.maintenance.order',
                'view_mode': 'list,kanban,form',
                'domain': [('id', 'in', created_orders.ids)],
            }

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sin Órdenes Generadas'),
                'message': _('No se encontraron umbrales superados para los vehículos seleccionados.'),
                'type': 'warning',
                'sticky': False,
            },
        }

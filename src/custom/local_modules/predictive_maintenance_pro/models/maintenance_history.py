# -*- coding: utf-8 -*-
from odoo import fields, models


class MaintenanceHistory(models.Model):
    """
    Registro histórico de mantenimientos realizados a un vehículo.

    Se crea automáticamente al completar una orden. Sirve como trazabilidad
    completa de todos los servicios, intervenciones y reemplazos.
    """

    _name = 'pmp.maintenance.history'
    _description = 'Historial de Mantenimiento'
    _order = 'date desc, id desc'
    _rec_name = 'description'

    # -------------------------------------------------------------------------
    # Relaciones
    # -------------------------------------------------------------------------
    vehicle_id = fields.Many2one(
        comodel_name='fleet.vehicle',
        string='Vehículo',
        required=True,
        ondelete='cascade',
        index=True,
    )
    order_id = fields.Many2one(
        comodel_name='pmp.maintenance.order',
        string='Orden de Mantenimiento',
        ondelete='set null',
        readonly=True,
    )
    technician_id = fields.Many2one(
        comodel_name='res.users',
        string='Técnico',
        ondelete='set null',
    )

    # -------------------------------------------------------------------------
    # Datos del servicio
    # -------------------------------------------------------------------------
    date = fields.Date(
        string='Fecha del Servicio',
        required=True,
        default=fields.Date.today,
        index=True,
    )
    description = fields.Text(
        string='Descripción del Servicio',
        required=True,
    )
    odometer_at_service = fields.Float(
        string='Odómetro al Servicio (km)',
        digits=(10, 2),
        help='Valor del odómetro registrado en el momento del servicio.',
    )
    hours_at_service = fields.Float(
        string='Horas al Servicio',
        digits=(10, 2),
        help='Horas de uso del equipo al momento del servicio.',
    )
    line_ids = fields.One2many(
        comodel_name='pmp.maintenance.history.line',
        inverse_name='history_id',
        string='Repuestos Reemplazados',
        readonly=True,
    )

    # -------------------------------------------------------------------------
    # Campos derivados (sin redundar datos de la orden)
    # -------------------------------------------------------------------------
    real_cost = fields.Float(
        string='Costo Real',
        related='order_id.real_cost',
        readonly=True,
        digits=(16, 2),
    )
    planned_cost = fields.Float(
        string='Costo Planificado',
        related='order_id.planned_cost',
        readonly=True,
        digits=(16, 2),
    )

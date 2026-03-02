# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MaintenanceHistoryLine(models.Model):
    """
    Línea de reemplazo de repuesto en el historial de mantenimiento.

    Registra para cada repuesto consumido:
    - Cuántos km/horas tenía el equipo cuando se instaló el repuesto anterior
    - Cuántos km/horas lleva desde el último cambio (vida útil real del repuesto)
    - Costo por km y costo por hora → eficiencia del repuesto
    """

    _name = 'pmp.maintenance.history.line'
    _description = 'Línea de Reemplazo de Repuesto'
    _order = 'history_id, id'

    # -------------------------------------------------------------------------
    # Relación padre
    # -------------------------------------------------------------------------
    history_id = fields.Many2one(
        comodel_name='pmp.maintenance.history',
        string='Historial',
        required=True,
        ondelete='cascade',
        index=True,
    )
    vehicle_id = fields.Many2one(
        comodel_name='fleet.vehicle',
        string='Vehículo',
        related='history_id.vehicle_id',
        store=True,
        readonly=True,
    )
    service_date = fields.Date(
        string='Fecha',
        related='history_id.date',
        store=True,
        readonly=True,
    )

    # -------------------------------------------------------------------------
    # Producto reemplazado
    # -------------------------------------------------------------------------
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Repuesto / Material',
        required=True,
        ondelete='restrict',
    )
    product_uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string='Unidad de Medida',
        related='product_id.uom_id',
        readonly=True,
    )
    qty_delivered = fields.Float(
        string='Cantidad Entregada',
        digits='Product Unit of Measure',
    )
    unit_cost = fields.Float(
        string='Costo Unitario',
        digits=(16, 4),
    )
    subtotal = fields.Float(
        string='Subtotal',
        digits=(16, 2),
    )

    # -------------------------------------------------------------------------
    # Métricas al momento del cambio actual
    # -------------------------------------------------------------------------
    odometer_at_change = fields.Float(
        string='Odómetro al Cambio (km)',
        digits=(10, 2),
        help='Lectura del odómetro cuando se realizó este reemplazo.',
    )
    hours_at_change = fields.Float(
        string='Horas al Cambio',
        digits=(10, 2),
        help='Horas de uso del equipo cuando se realizó este reemplazo.',
    )

    # -------------------------------------------------------------------------
    # Referencia al cambio anterior (para calcular vida útil del repuesto)
    # -------------------------------------------------------------------------
    last_change_date = fields.Date(
        string='Fecha Último Cambio',
        readonly=True,
        help='Fecha en que se instaló el repuesto que ahora se reemplaza.',
    )
    last_change_odometer = fields.Float(
        string='Odómetro en Último Cambio (km)',
        digits=(10, 2),
        readonly=True,
        help='Lectura del odómetro cuando se realizó el último cambio de este repuesto.',
    )
    last_change_hours = fields.Float(
        string='Horas en Último Cambio',
        digits=(10, 2),
        readonly=True,
        help='Horas del equipo cuando se realizó el último cambio de este repuesto.',
    )

    # -------------------------------------------------------------------------
    # Vida útil del repuesto (calculada)
    # -------------------------------------------------------------------------
    km_since_last_change = fields.Float(
        string='Km desde Último Cambio',
        compute='_compute_usage_metrics',
        store=True,
        digits=(10, 2),
        help='Kilómetros recorridos con este repuesto instalado.',
    )
    hours_since_last_change = fields.Float(
        string='Horas desde Último Cambio',
        compute='_compute_usage_metrics',
        store=True,
        digits=(10, 2),
        help='Horas de operación con este repuesto instalado.',
    )
    cost_per_km = fields.Float(
        string='Costo por Km',
        compute='_compute_usage_metrics',
        store=True,
        digits=(16, 4),
        help='Costo total del repuesto dividido entre km recorridos.',
    )
    cost_per_hour = fields.Float(
        string='Costo por Hora',
        compute='_compute_usage_metrics',
        store=True,
        digits=(16, 4),
        help='Costo total del repuesto dividido entre horas de uso.',
    )

    # -------------------------------------------------------------------------
    # Computes
    # -------------------------------------------------------------------------
    @api.depends('odometer_at_change', 'last_change_odometer',
                 'hours_at_change', 'last_change_hours', 'subtotal')
    def _compute_usage_metrics(self):
        for line in self:
            km_used = max(line.odometer_at_change - line.last_change_odometer, 0.0)
            hrs_used = max(line.hours_at_change - line.last_change_hours, 0.0)
            line.km_since_last_change = km_used
            line.hours_since_last_change = hrs_used
            line.cost_per_km = line.subtotal / km_used if km_used > 0 else 0.0
            line.cost_per_hour = line.subtotal / hrs_used if hrs_used > 0 else 0.0

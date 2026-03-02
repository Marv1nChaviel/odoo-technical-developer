# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MaintenancePlanLine(models.Model):
    """
    Línea de repuesto/material asociada a un plan de mantenimiento.
    Define el producto y la cantidad estimada necesaria para ejecutar el plan.
    Estas líneas se copian automáticamente como líneas de la orden al generarla.
    """

    _name = 'pmp.maintenance.plan.line'
    _description = 'Línea de Repuesto del Plan de Mantenimiento'
    _order = 'sequence, id'

    sequence = fields.Integer(string='Secuencia', default=10)

    plan_id = fields.Many2one(
        comodel_name='pmp.maintenance.plan',
        string='Plan de Mantenimiento',
        required=True,
        ondelete='cascade',
        index=True,
    )

    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Repuesto / Material',
        required=True,
        domain=[('type', 'in', ['product', 'consu'])],
        change_default=True,
    )

    product_uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string='Unidad de Medida',
        related='product_id.uom_id',
        readonly=True,
    )

    qty_planned = fields.Float(
        string='Cantidad Estimada',
        digits='Product Unit of Measure',
        default=1.0,
        help='Cantidad estimada de este repuesto necesaria para el mantenimiento.',
    )

    unit_cost = fields.Float(
        string='Costo Unitario',
        digits=(16, 2),
        compute='_compute_unit_cost',
        store=True,
        readonly=True,
        help='Costo unitario obtenido automáticamente de la ficha del producto (Precio de Costo).',
    )

    subtotal = fields.Float(
        string='Subtotal Estimado',
        digits=(16, 2),
        compute='_compute_subtotal',
        store=True,
    )

    # -------------------------------------------------------------------------
    # Computes
    # -------------------------------------------------------------------------
    @api.depends('product_id')
    def _compute_unit_cost(self):
        for line in self:
            line.unit_cost = line.product_id.standard_price if line.product_id else 0.0

    @api.depends('qty_planned', 'unit_cost')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.qty_planned * line.unit_cost

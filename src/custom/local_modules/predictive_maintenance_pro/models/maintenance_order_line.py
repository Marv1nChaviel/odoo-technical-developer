# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class MaintenanceOrderLine(models.Model):
    """
    Línea de consumo de repuesto/material dentro de una orden de mantenimiento.

    Registra la cantidad planificada, la entregada desde el picking de stock
    y la pendiente de entrega.
    """

    _name = 'pmp.maintenance.order.line'
    _description = 'Línea de Orden de Mantenimiento'
    _order = 'order_id, sequence, id'

    # -------------------------------------------------------------------------
    # Estructura
    # -------------------------------------------------------------------------
    sequence = fields.Integer(
        string='Secuencia',
        default=10,
    )
    order_id = fields.Many2one(
        comodel_name='pmp.maintenance.order',
        string='Orden',
        required=True,
        ondelete='cascade',
        index=True,
    )

    # -------------------------------------------------------------------------
    # Producto
    # -------------------------------------------------------------------------
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Repuesto / Material',
        required=True,
        domain=[('type', 'in', ['product', 'consu'])],
        ondelete='restrict',
    )
    product_uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string='Unidad de Medida',
        related='product_id.uom_id',
        readonly=True,
    )

    # -------------------------------------------------------------------------
    # Cantidades
    # -------------------------------------------------------------------------
    qty_planned = fields.Float(
        string='Cant. Planificada',
        digits='Product Unit of Measure',
        default=1.0,
    )
    qty_delivered = fields.Float(
        string='Cant. Entregada',
        digits='Product Unit of Measure',
        compute='_compute_qty_delivered',
        inverse='_inverse_qty_delivered',
        store=True,
        help='Cantidad entregada desde el picking de la orden. '
             'Se puede editar manualmente si no hay picking asociado.',
    )
    qty_pending = fields.Float(
        string='Cant. Pendiente',
        digits='Product Unit of Measure',
        compute='_compute_qty_delivered',
        store=True,
        help='Cantidad pendiente de entrega (planificada − entregada).',
    )

    # -------------------------------------------------------------------------
    # Costos
    # -------------------------------------------------------------------------
    unit_cost = fields.Float(
        string='Costo Unitario',
        digits=(16, 4),
        default=0.0,
    )
    subtotal = fields.Float(
        string='Subtotal',
        compute='_compute_subtotal',
        inverse='_inverse_subtotal',
        store=True,
        digits=(16, 2),
    )

    # -------------------------------------------------------------------------
    # Computes
    # -------------------------------------------------------------------------
    @api.depends('order_id.picking_id', 'order_id.picking_id.state',
                 'order_id.picking_id.move_line_ids.quantity', 'product_id', 'qty_planned')
    def _compute_qty_delivered(self):
        for line in self:
            picking = line.order_id.picking_id
            if picking:
                # Si hay picking real, tomamos la cantidad real del stock
                all_pickings = picking
                backorders = self.env['stock.picking'].search([
                    ('backorder_id', 'in', [picking.id])
                ])
                all_pickings |= backorders
                delivered = sum(
                    ml.quantity
                    for ml in all_pickings.move_line_ids
                    if ml.product_id == line.product_id
                )
                line.qty_delivered = delivered
                line.qty_pending = max(line.qty_planned - delivered, 0.0)
            # Si no hay picking, respetamos el valor manualmente asignado
            # (o sea, no sobreescribimos con 0 si ya hay un valor guardado)

    def _inverse_qty_delivered(self):
        """Permite escritura directa de qty_delivered (demo data / ajuste manual)."""
        for line in self:
            line.qty_pending = max(line.qty_planned - line.qty_delivered, 0.0)

    @api.depends('qty_delivered', 'unit_cost')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.qty_delivered * line.unit_cost

    def _inverse_subtotal(self):
        """Permite escritura directa de subtotal (demo data)."""
        pass  # subtotal se recalcula siempre desde compute; inverse solo habilita la escritura

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------
    def action_view_picking(self):
        """Abre todos los pickings (original + backorders) de la orden."""
        self.ensure_one()
        if not self.order_id.picking_id:
            raise UserError(_('No hay entrega de repuestos asociada.'))
        # Recopilar picking original + backorders
        all_pickings = self.order_id.picking_id
        backorders = self.env['stock.picking'].search([
            ('backorder_id', 'child_of', self.order_id.picking_id.id)
        ])
        all_pickings |= backorders
        all_ids = all_pickings.ids
        if len(all_ids) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Entrega de Repuestos'),
                'res_model': 'stock.picking',
                'view_mode': 'form',
                'res_id': all_ids[0],
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Entregas de Repuestos'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('id', 'in', all_ids)],
        }

    # -------------------------------------------------------------------------
    # Onchanges
    # -------------------------------------------------------------------------
    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Pre-rellena el costo unitario desde la ficha del producto."""
        if self.product_id:
            self.unit_cost = self.product_id.standard_price

    # -------------------------------------------------------------------------
    # Constraints
    # -------------------------------------------------------------------------
    @api.constrains('qty_planned')
    def _check_quantities(self):
        for line in self:
            if line.qty_planned < 0:
                raise ValidationError(
                    'La cantidad planificada no puede ser negativa.'
                )

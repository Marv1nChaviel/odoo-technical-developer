# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MaintenanceOrder(models.Model):
    """
    Orden de mantenimiento generada a partir de un plan predictivo.

    Gestiona el ciclo de vida completo: programación → ejecución →
    consumo de repuestos → cierre con costo real y generación de historial.
    """

    _name = 'pmp.maintenance.order'
    _description = 'Orden de Mantenimiento'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_scheduled desc, name desc'

    # -------------------------------------------------------------------------
    # Identificación
    # -------------------------------------------------------------------------
    name = fields.Char(
        string='Referencia',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('Nueva Orden'),
        index=True,
        tracking=True,
    )

    # -------------------------------------------------------------------------
    # Estado
    # -------------------------------------------------------------------------
    state = fields.Selection(
        selection=[
            ('draft', 'Borrador'),
            ('confirmed', 'Confirmada'),
            ('in_progress', 'En Ejecución'),
            ('done', 'Completada'),
            ('cancelled', 'Cancelada'),
        ],
        string='Estado',
        default='draft',
        required=True,
        tracking=True,
        copy=False,
        index=True,
    )

    # -------------------------------------------------------------------------
    # Relaciones principales
    # -------------------------------------------------------------------------
    plan_id = fields.Many2one(
        comodel_name='pmp.maintenance.plan',
        string='Plan de Mantenimiento',
        ondelete='restrict',
        tracking=True,
        index=True,
    )
    vehicle_id = fields.Many2one(
        comodel_name='fleet.vehicle',
        string='Vehículo',
        required=True,
        ondelete='restrict',
        tracking=True,
        index=True,
    )
    technician_id = fields.Many2one(
        comodel_name='res.users',
        string='Técnico Asignado',
        tracking=True,
        domain=[('share', '=', False)],
    )
    helper_ids = fields.Many2many(
        comodel_name='res.users',
        relation='pmp_maintenance_order_helper_rel',
        column1='order_id',
        column2='user_id',
        string='Ayudantes',
        domain=[('share', '=', False)],
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company,
    )

    # -------------------------------------------------------------------------
    # Fechas
    # -------------------------------------------------------------------------
    date_scheduled = fields.Date(
        string='Fecha Programada',
        required=True,
        default=fields.Date.today,
        tracking=True,
    )
    date_start = fields.Datetime(
        string='Inicio Real',
        copy=False,
        tracking=True,
    )
    date_done = fields.Datetime(
        string='Cierre Real',
        copy=False,
        tracking=True,
    )

    # -------------------------------------------------------------------------
    # Costos
    # -------------------------------------------------------------------------
    planned_cost = fields.Float(
        string='Costo Planificado',
        digits=(16, 2),
        tracking=True,
    )
    real_cost = fields.Float(
        string='Costo Real',
        compute='_compute_real_cost',
        store=False,
        digits=(16, 2),
        help='Suma de los subtotales de las líneas de repuestos consumidos.',
    )
    cost_variance = fields.Float(
        string='Variación de Costo',
        compute='_compute_cost_variance',
        store=False,
        digits=(16, 2),
        help='Diferencia entre costo real y planificado. Negativo = ahorro.',
    )

    # -------------------------------------------------------------------------
    # Líneas de repuestos
    # -------------------------------------------------------------------------
    line_ids = fields.One2many(
        comodel_name='pmp.maintenance.order.line',
        inverse_name='order_id',
        string='Repuestos / Materiales',
        copy=True,
    )

    # -------------------------------------------------------------------------
    # Campos de contexto
    # -------------------------------------------------------------------------
    odometer_at_service = fields.Float(
        string='Odómetro al Servicio (km)',
        digits=(10, 2),
        copy=False,
        help='Lectura del odómetro al momento del servicio. '
             'Se usará como Último Valor Disparado al completar la orden.',
    )
    hours_at_service = fields.Float(
        string='Horas al Servicio',
        digits=(10, 2),
        copy=False,
        help='Horas de uso del equipo al momento del servicio. '
             'Se usará como Último Valor Disparado al completar la orden.',
    )
    notes = fields.Html(
        string='Observaciones',
    )

    # -------------------------------------------------------------------------
    # Entrega de repuestos (stock.picking)
    # -------------------------------------------------------------------------
    picking_id = fields.Many2one(
        comodel_name='stock.picking',
        string='Entrega de Repuestos',
        readonly=True,
        copy=False,
        help='Transferencia interna creada al confirmar la orden para descargo de repuestos.',
    )
    picking_count = fields.Integer(
        string='Entregas',
        compute='_compute_picking_count',
    )
    picking_id_state = fields.Selection(
        related='picking_id.state',
        string='Estado de Entrega',
        readonly=True,
        store=False,
    )

    # -------------------------------------------------------------------------
    # Computes
    # -------------------------------------------------------------------------
    @api.depends('line_ids.subtotal')
    def _compute_real_cost(self):
        for order in self:
            order.real_cost = sum(order.line_ids.mapped('subtotal'))

    @api.depends('real_cost', 'planned_cost')
    def _compute_cost_variance(self):
        for order in self:
            order.cost_variance = order.real_cost - order.planned_cost

    @api.depends('picking_id')
    def _compute_picking_count(self):
        for order in self:
            if not order.picking_id:
                order.picking_count = 0
                continue
            backorders = self.env['stock.picking'].search([
                ('backorder_id', 'in', [order.picking_id.id])
            ])
            order.picking_count = 1 + len(backorders)

    # -------------------------------------------------------------------------
    # CRUD overrides
    # -------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence']
        for vals in vals_list:
            if vals.get('name', _('Nueva Orden')) == _('Nueva Orden'):
                vals['name'] = sequence.next_by_code('pmp.maintenance.order') or _('Nueva Orden')
        return super().create(vals_list)

    # -------------------------------------------------------------------------
    # Acciones de estado (máquina de estados)
    # -------------------------------------------------------------------------
    def action_confirm(self):
        """draft → confirmed + crea picking de entrega de repuestos."""
        for order in self:
            if order.state != 'draft':
                raise UserError(
                    _('Solo se pueden confirmar órdenes en estado Borrador.')
                )
            order.write({'state': 'confirmed'})
            if order.line_ids:
                order._create_parts_picking()

    def action_start(self):
        """confirmed → in_progress.
        Permite iniciar con entrega parcial (picking done + backorder activo).
        Solo bloquea si el picking existe pero NO ha sido procesado aún.
        """
        for order in self:
            if order.state != 'confirmed':
                raise UserError(
                    _('Solo se pueden iniciar órdenes confirmadas.')
                )
            picking = order.picking_id
            if picking and picking.state not in ('done', 'cancel'):
                # El picking todavía no se ha validado en absoluto
                # (ni parcialmente). Permitimos continuar pero avisamos.
                backorders = self.env['stock.picking'].search([
                    ('backorder_id', '=', picking.id)
                ])
                if not backorders:
                    raise UserError(
                        _(
                            'Debe entregar los repuestos antes de iniciar el trabajo.\n'
                            'Valide la transferencia "%s" (aunque sea parcialmente)\n'
                            'para registrar los repuestos entregados.'
                        ) % picking.name
                    )
        self.write({'state': 'in_progress', 'date_start': fields.Datetime.now()})

    def action_done(self):
        """in_progress → done + actualiza last_trigger_value del plan + crea historial.
        Técnicos no pueden completar si hay repuestos pendientes de entrega.
        Coordinadores pueden saltarse esa restricción.
        """
        is_coordinator = self.env.user.has_group(
            'predictive_maintenance_pro.group_pmp_coordinator'
        )
        for order in self:
            if order.state != 'in_progress':
                raise UserError(
                    _('Solo se pueden cerrar órdenes en ejecución.')
                )
            # Verificar pendientes solo si el usuario NO es coordinador
            if not is_coordinator:
                pending_lines = [
                    ln for ln in order.line_ids
                    if ln.qty_pending > 0
                ]
                if pending_lines:
                    items = ', '.join(
                        '%s (pendiente: %.2f)' % (ln.product_id.name, ln.qty_pending)
                        for ln in pending_lines
                    )
                    raise UserError(_(
                        'No se puede completar la orden: hay repuestos pendientes de entrega.\n'
                        '%s\n\n'
                        'Espere la entrega completa o solicite al coordinador que cierre la orden.'
                    ) % items)

            now = fields.Datetime.now()
            order.write({'state': 'done', 'date_done': now})

            # Actualizar last_trigger_value del plan en base al tipo de trigger
            plan = order.plan_id
            if plan:
                if plan.trigger_type == 'km':
                    trigger_value = order.odometer_at_service or order.vehicle_id.odometer
                    if trigger_value:
                        plan.write({'last_trigger_value': trigger_value})
                elif plan.trigger_type == 'hours':
                    trigger_value = order.hours_at_service or order.vehicle_id.current_hours
                    if trigger_value:
                        plan.write({'last_trigger_value': trigger_value})
                elif plan.trigger_type == 'days':
                    # Guardar la fecha actual como última ejecución
                    plan.write({'last_trigger_date': fields.Date.today()})
                # date: no se actualiza, es una fecha fija única

            order._create_history_entry()

    def action_cancel(self):
        """any → cancelled (excepto done)"""
        for order in self:
            if order.state == 'done':
                raise UserError(
                    _('No se puede cancelar una orden ya completada.')
                )
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        """cancelled → draft"""
        for order in self:
            if order.state != 'cancelled':
                raise UserError(
                    _('Solo se pueden restablecer órdenes canceladas.')
                )
        self.write({'state': 'draft'})

    # -------------------------------------------------------------------------
    # Business logic
    # -------------------------------------------------------------------------
    def _create_history_entry(self):
        """Crea registro en historial con desglose de repuestos y métricas de vida útil.

        Para cada repuesto consumido:
        - Busca el último reemplazo del mismo producto en este vehículo
        - Calcula km y horas de uso desde ese cambio anterior
        - Calcula costo por km y costo por hora
        """
        self.ensure_one()
        HistoryLine = self.env['pmp.maintenance.history.line']
        today = fields.Date.today()

        # 1) Qty delivered por producto desde el picking + backorders
        picking = self.picking_id
        delivered_by_product = {}
        if picking:
            backorders = self.env['stock.picking'].search([
                ('backorder_id', 'in', [picking.id])
            ])
            for ml in (picking | backorders).move_line_ids:
                pid = ml.product_id.id
                delivered_by_product[pid] = delivered_by_product.get(pid, 0.0) + ml.quantity

        # 2) Construir texto resumen y líneas de detalle
        parts_summary = []
        total_cost = 0.0
        history_lines = []

        for line in self.line_ids:
            delivered = delivered_by_product.get(line.product_id.id, 0.0)
            if not delivered:
                continue
            subtotal = delivered * line.unit_cost
            total_cost += subtotal

            # Buscar el último historial de este producto en este vehículo
            last_hist_line = HistoryLine.search([
                ('product_id', '=', line.product_id.id),
                ('history_id.vehicle_id', '=', self.vehicle_id.id),
            ], order='history_id DESC', limit=1)

            last_date = last_hist_line.history_id.date if last_hist_line else False
            last_odo = last_hist_line.odometer_at_change if last_hist_line else 0.0
            last_hrs = last_hist_line.hours_at_change if last_hist_line else 0.0

            km_used = max(self.odometer_at_service - last_odo, 0.0)
            hrs_used = max(self.hours_at_service - last_hrs, 0.0)

            history_lines.append({
                'product_id': line.product_id.id,
                'qty_delivered': delivered,
                'unit_cost': line.unit_cost,
                'subtotal': subtotal,
                'odometer_at_change': self.odometer_at_service,
                'hours_at_change': self.hours_at_service,
                'last_change_date': last_date,
                'last_change_odometer': last_odo,
                'last_change_hours': last_hrs,
            })

            # Texto resumen para la descripción
            km_info = '%.0f km' % km_used if km_used else '—'
            hrs_info = '%.0f h' % hrs_used if hrs_used else '—'
            cpm = subtotal / km_used if km_used > 0 else 0.0
            cph = subtotal / hrs_used if hrs_used > 0 else 0.0
            parts_summary.append(
                '  • %s: %.2f %s | Subtotal: %.2f | Vida: %s / %s | $/km: %.4f | $/h: %.4f' % (
                    line.product_id.name,
                    delivered,
                    line.product_uom_id.name,
                    subtotal,
                    km_info, hrs_info,
                    cpm, cph,
                )
            )

        if parts_summary:
            description = _(
                'Orden %s completada.\nRepuestos reemplazados:\n%s\nCosto real: %.2f'
            ) % (self.name, '\n'.join(parts_summary), total_cost)
        else:
            description = _(
                'Orden %s completada. Sin repuestos registrados. Costo real: %.2f'
            ) % (self.name, total_cost)

        history = self.env['pmp.maintenance.history'].create({
            'vehicle_id': self.vehicle_id.id,
            'order_id': self.id,
            'date': today,
            'description': description,
            'odometer_at_service': self.odometer_at_service,
            'hours_at_service': self.hours_at_service,
            'technician_id': self.technician_id.id if self.technician_id else False,
        })

        # 3) Crear las líneas de detalle de reemplazo
        for hl in history_lines:
            hl['history_id'] = history.id
            HistoryLine.create(hl)

    def _create_parts_picking(self):
        """
        Crea un stock.picking de tipo interno para descarga de repuestos:
        Fuente : ubicación de stock de la compañía
        Destino: Virtual Locations/Production (consumo)
        """
        self.ensure_one()

        # Ubicación origen: stock de la compañía
        location_src = self.env['stock.warehouse'].search(
            [('company_id', '=', self.company_id.id)], limit=1
        ).lot_stock_id
        if not location_src:
            location_src = self.env.ref('stock.stock_location_stock', raise_if_not_found=False)

        # Ubicación destino: producción / consumo virtual
        location_dest = self.env.ref(
            'stock.location_production', raise_if_not_found=False
        )
        if not location_dest:
            location_dest = self.env.ref('stock.stock_location_customers', raise_if_not_found=False)

        # Tipo de picking: transferencia interna
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('warehouse_id.company_id', '=', self.company_id.id),
        ], limit=1)
        if not picking_type:
            picking_type = self.env.ref('stock.picking_type_internal', raise_if_not_found=False)

        if not location_src or not location_dest or not picking_type:
            return  # No se puede crear sin ubicaciones configuradas

        moves = []
        for line in self.line_ids:
            product = line.product_id
            if not product or line.qty_planned <= 0:
                continue
            moves.append((0, 0, {
                'name': product.name + ' [PMP: %s]' % self.name,
                'product_id': product.id,
                'product_uom_qty': line.qty_planned,
                'product_uom': product.uom_id.id,
                'location_id': location_src.id,
                'location_dest_id': location_dest.id,
            }))

        if not moves:
            return

        picking = self.env['stock.picking'].create({
            'partner_id': False,
            'picking_type_id': picking_type.id,
            'location_id': location_src.id,
            'location_dest_id': location_dest.id,
            'origin': self.name,
            'note': _('Repuestos para orden de mantenimiento %s — %s') % (
                self.name, self.vehicle_id.name
            ),
            'move_ids': moves,
        })
        self.picking_id = picking

    def action_view_picking(self):
        """Abre todos los pickings (original + backorders) de la orden."""
        self.ensure_one()
        if not self.picking_id:
            raise UserError(_('No hay entrega de repuestos asociada.'))
        backorders = self.env['stock.picking'].search([
            ('backorder_id', 'in', [self.picking_id.id])
        ])
        all_ids = (self.picking_id | backorders).ids
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

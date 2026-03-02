# -*- coding: utf-8 -*-
from datetime import date
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models


class PmpDashboard(models.TransientModel):
    """
    Dashboard del coordinador con KPIs filtrados por rango de fechas.
    Los KPIs de flota son tiempo real; órdenes y costos se filtran por período.
    """
    _name = 'pmp.dashboard'
    _description = 'Dashboard de Mantenimiento Predictivo'
    _rec_name = 'name'

    # -------------------------------------------------------------------------
    # Nombre (evita que Odoo muestre "pmp.dashboard,N" como título)
    # -------------------------------------------------------------------------
    name = fields.Char(
        string='Nombre',
        default='Dashboard de Mantenimiento',
        readonly=True,
    )

    # -------------------------------------------------------------------------
    # Filtros de período
    # -------------------------------------------------------------------------
    date_from = fields.Date(
        string='Desde',
        required=True,
        default=lambda self: date.today().replace(day=1),
    )
    date_to = fields.Date(
        string='Hasta',
        required=True,
        default=fields.Date.today,
    )
    period_label = fields.Char(
        string='Período',
        compute='_compute_period_label',
    )

    # -------------------------------------------------------------------------
    # Flota (tiempo real, sin filtro de fechas)
    # -------------------------------------------------------------------------
    total_vehicles = fields.Integer(string='Total Vehículos', compute='_compute_fleet_kpis')
    vehicles_ok = fields.Integer(string='En Operación', compute='_compute_fleet_kpis')
    vehicles_upcoming = fields.Integer(string='Próximo Mantenimiento', compute='_compute_fleet_kpis')
    vehicles_in_maintenance = fields.Integer(string='En Mantenimiento', compute='_compute_fleet_kpis')
    pct_in_maintenance = fields.Float(string='% En Mantenimiento', compute='_compute_fleet_kpis', digits=(5, 1))

    # -------------------------------------------------------------------------
    # Órdenes (filtradas por período)
    # -------------------------------------------------------------------------
    orders_draft = fields.Integer(string='Borradores', compute='_compute_order_kpis')
    orders_confirmed = fields.Integer(string='Confirmadas', compute='_compute_order_kpis')
    orders_in_progress = fields.Integer(string='En Ejecución', compute='_compute_order_kpis')
    orders_done_period = fields.Integer(string='Completadas en Período', compute='_compute_order_kpis')
    orders_cancelled_period = fields.Integer(string='Canceladas en Período', compute='_compute_order_kpis')
    orders_open_total = fields.Integer(string='Órdenes Abiertas', compute='_compute_order_kpis')

    # -------------------------------------------------------------------------
    # Costos (filtrados por período)
    # -------------------------------------------------------------------------
    cost_period = fields.Float(string='Costo Real en Período', compute='_compute_cost_kpis', digits=(16, 2))
    cost_planned_open = fields.Float(string='Presupuesto (abiertas)', compute='_compute_cost_kpis', digits=(16, 2))
    cost_avg_per_order = fields.Float(string='Costo Promedio por Orden', compute='_compute_cost_kpis', digits=(16, 2))
    cost_variance_period = fields.Float(string='Variación vs Planificado', compute='_compute_cost_kpis', digits=(16, 2))

    # -------------------------------------------------------------------------
    # Inventario / Repuestos
    # -------------------------------------------------------------------------
    pickings_pending = fields.Integer(string='Entregas Pendientes', compute='_compute_inventory_kpis')
    backorders_open = fields.Integer(string='Backorders Abiertos', compute='_compute_inventory_kpis')
    most_used_part = fields.Char(string='Repuesto Más Usado', compute='_compute_inventory_kpis')
    parts_total_cost_period = fields.Float(
        string='Valor de Repuestos (período)', compute='_compute_inventory_kpis', digits=(16, 2))

    # =========================================================================
    # Computes
    # =========================================================================

    @api.depends('date_from', 'date_to')
    def _compute_period_label(self):
        for rec in self:
            if rec.date_from and rec.date_to:
                rec.period_label = '%s → %s' % (
                    rec.date_from.strftime('%d/%m/%Y'),
                    rec.date_to.strftime('%d/%m/%Y'),
                )
            else:
                rec.period_label = '—'

    @api.depends()
    def _compute_fleet_kpis(self):
        Vehicle = self.env['fleet.vehicle']
        total = Vehicle.search_count([])
        ok = Vehicle.search_count([('maintenance_status', '=', 'ok')])
        upcoming = Vehicle.search_count([('maintenance_status', '=', 'upcoming')])
        in_maint = Vehicle.search_count([('maintenance_status', '=', 'in_maintenance')])
        pct = (in_maint / total) if total else 0.0
        for rec in self:
            rec.total_vehicles = total
            rec.vehicles_ok = ok
            rec.vehicles_upcoming = upcoming
            rec.vehicles_in_maintenance = in_maint
            rec.pct_in_maintenance = pct

    @api.depends('date_from', 'date_to')
    def _compute_order_kpis(self):
        Order = self.env['pmp.maintenance.order']
        for rec in self:
            df = rec.date_from.strftime('%Y-%m-%d 00:00:00') if rec.date_from else False
            dt = rec.date_to.strftime('%Y-%m-%d 23:59:59') if rec.date_to else False

            done_domain = [('state', '=', 'done')]
            cancel_domain = [('state', '=', 'cancelled')]
            if df:
                done_domain += [('date_done', '>=', df)]
                cancel_domain += [('date_done', '>=', df)]
            if dt:
                done_domain += [('date_done', '<=', dt)]
                cancel_domain += [('date_done', '<=', dt)]

            rec.orders_draft = Order.search_count([('state', '=', 'draft')])
            rec.orders_confirmed = Order.search_count([('state', '=', 'confirmed')])
            rec.orders_in_progress = Order.search_count([('state', '=', 'in_progress')])
            rec.orders_done_period = Order.search_count(done_domain)
            rec.orders_cancelled_period = Order.search_count(cancel_domain)
            rec.orders_open_total = Order.search_count([
                ('state', 'in', ['draft', 'confirmed', 'in_progress'])
            ])

    @api.depends('date_from', 'date_to')
    def _compute_cost_kpis(self):
        Order = self.env['pmp.maintenance.order']

        def _calc_cost(orders):
            total = 0.0
            for order in orders:
                picking = order.picking_id
                if not picking:
                    continue
                backorders = self.env['stock.picking'].search([
                    ('backorder_id', 'in', [picking.id])
                ])
                delivered = {}
                for ml in (picking | backorders).move_line_ids:
                    pid = ml.product_id.id
                    delivered[pid] = delivered.get(pid, 0.0) + ml.quantity
                for line in order.line_ids:
                    total += delivered.get(line.product_id.id, 0.0) * line.unit_cost
            return total

        for rec in self:
            df = rec.date_from.strftime('%Y-%m-%d 00:00:00') if rec.date_from else False
            dt = rec.date_to.strftime('%Y-%m-%d 23:59:59') if rec.date_to else False

            done_domain = [('state', '=', 'done')]
            if df:
                done_domain.append(('date_done', '>=', df))
            if dt:
                done_domain.append(('date_done', '<=', dt))

            done_orders = Order.search(done_domain)
            open_orders = Order.search([('state', 'in', ['draft', 'confirmed', 'in_progress'])])

            real_cost = _calc_cost(done_orders)
            planned_open = sum(open_orders.mapped('planned_cost'))
            planned_done = sum(done_orders.mapped('planned_cost'))
            avg = real_cost / len(done_orders) if done_orders else 0.0

            rec.cost_period = real_cost
            rec.cost_planned_open = planned_open
            rec.cost_avg_per_order = avg
            rec.cost_variance_period = real_cost - planned_done

    @api.depends('date_from', 'date_to')
    def _compute_inventory_kpis(self):
        Picking = self.env['stock.picking']

        active_orders = self.env['pmp.maintenance.order'].search([
            ('state', 'in', ['confirmed', 'in_progress']),
            ('picking_id', '!=', False),
        ])
        picking_ids = active_orders.mapped('picking_id').ids
        pending = Picking.search_count([
            ('id', 'in', picking_ids),
            ('state', 'not in', ['done', 'cancel']),
        ])
        backorders = Picking.search_count([
            ('backorder_id', 'in', picking_ids),
            ('state', 'not in', ['done', 'cancel']),
        ])

        # Repuesto más usado en el período
        for rec in self:
            df = rec.date_from.strftime('%Y-%m-%d') if rec.date_from else '1900-01-01'
            dt = rec.date_to.strftime('%Y-%m-%d') if rec.date_to else '2099-12-31'
            self.env.cr.execute("""
                SELECT COALESCE(p.name->>'es_419', p.name->>'en_US', p.name::text) as pname,
                       SUM(hl.qty_delivered) AS total
                FROM pmp_maintenance_history_line hl
                JOIN pmp_maintenance_history h ON h.id = hl.history_id
                JOIN product_product pp ON pp.id = hl.product_id
                JOIN product_template p ON p.id = pp.product_tmpl_id
                WHERE h.date >= %s AND h.date <= %s
                GROUP BY pname
                ORDER BY total DESC
                LIMIT 1
            """, (df, dt))
            row = self.env.cr.fetchone()
            most_used = row[0] if row else '—'

            # Costo total de repuestos en período
            self.env.cr.execute("""
                SELECT COALESCE(SUM(hl.subtotal), 0)
                FROM pmp_maintenance_history_line hl
                JOIN pmp_maintenance_history h ON h.id = hl.history_id
                WHERE h.date >= %s AND h.date <= %s
            """, (df, dt))
            parts_cost = self.env.cr.fetchone()[0] or 0.0

            rec.pickings_pending = pending
            rec.backorders_open = backorders
            rec.most_used_part = most_used
            rec.parts_total_cost_period = parts_cost

    # -------------------------------------------------------------------------
    # Accesos rápidos con filtro de fecha
    # -------------------------------------------------------------------------
    def action_open_orders_draft(self):
        return {'type': 'ir.actions.act_window', 'name': 'Borradores',
                'res_model': 'pmp.maintenance.order', 'view_mode': 'list,form',
                'domain': [('state', '=', 'draft')]}

    def action_open_orders_in_progress(self):
        return {'type': 'ir.actions.act_window', 'name': 'En Ejecución',
                'res_model': 'pmp.maintenance.order', 'view_mode': 'list,form',
                'domain': [('state', '=', 'in_progress')]}

    def action_open_orders_done(self):
        domain = [('state', '=', 'done')]
        if self.date_from:
            domain.append(('date_done', '>=', fields.Datetime.to_string(self.date_from)))
        if self.date_to:
            domain.append(('date_done', '<=', self.date_to.strftime('%Y-%m-%d') + ' 23:59:59'))
        return {'type': 'ir.actions.act_window', 'name': 'Completadas',
                'res_model': 'pmp.maintenance.order', 'view_mode': 'list,form', 'domain': domain}

    def action_open_vehicles_in_maintenance(self):
        return {'type': 'ir.actions.act_window', 'name': 'En Mantenimiento',
                'res_model': 'fleet.vehicle', 'view_mode': 'list,form',
                'domain': [('maintenance_status', '=', 'in_maintenance')]}

    def action_open_pending_pickings(self):
        active_orders = self.env['pmp.maintenance.order'].search([
            ('state', 'in', ['confirmed', 'in_progress']), ('picking_id', '!=', False),
        ])
        picking_ids = active_orders.mapped('picking_id').ids
        backorder_ids = self.env['stock.picking'].search([
            ('backorder_id', 'in', picking_ids), ('state', 'not in', ['done', 'cancel']),
        ]).ids
        return {'type': 'ir.actions.act_window', 'name': 'Entregas Pendientes',
                'res_model': 'stock.picking', 'view_mode': 'list,form',
                'domain': [('id', 'in', picking_ids + backorder_ids),
                           ('state', 'not in', ['done', 'cancel'])]}

    def action_open_history(self):
        domain = []
        if self.date_from:
            domain.append(('date', '>=', self.date_from))
        if self.date_to:
            domain.append(('date', '<=', self.date_to))
        return {'type': 'ir.actions.act_window', 'name': 'Historial',
                'res_model': 'pmp.maintenance.history', 'view_mode': 'list,form',
                'domain': domain}

    def action_set_this_month(self):
        today = date.today()
        self.write({'date_from': today.replace(day=1), 'date_to': today})
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_set_last_month(self):
        today = date.today()
        first_this = today.replace(day=1)
        last_month_end = first_this - relativedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        self.write({'date_from': last_month_start, 'date_to': last_month_end})
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_set_this_year(self):
        today = date.today()
        self.write({'date_from': today.replace(month=1, day=1), 'date_to': today})
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    @api.model
    def action_open_dashboard(self):
        """Invocado por el server action del menú. Crea un registro transitorio
        con las fechas del mes actual y abre el formulario directamente."""
        today = date.today()
        record = self.create({
            'date_from': today.replace(day=1),
            'date_to': today,
        })
        view_id = self.env.ref(
            'predictive_maintenance_pro.view_pmp_dashboard_form'
        ).id
        return {
            'type': 'ir.actions.act_window',
            'name': 'Dashboard de Mantenimiento',
            'res_model': 'pmp.dashboard',
            'view_mode': 'form',
            'res_id': record.id,
            'views': [(view_id, 'form')],
            'target': 'inline',
            'flags': {
                'mode': 'readonly',
                'action_buttons': False,
                'has_breadcrumb': False,
                'withControlPanel': False,
            },
        }

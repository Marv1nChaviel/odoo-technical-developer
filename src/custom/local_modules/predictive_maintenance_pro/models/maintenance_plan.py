# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MaintenancePlan(models.Model):
    """
    Define un plan de mantenimiento preventivo/predictivo para un vehículo.

    El plan establece umbrales (km, horas, eventos o fechas) que al ser
    superados disparan la creación automática de órdenes de mantenimiento.
    """

    _name = 'pmp.maintenance.plan'
    _description = 'Plan de Mantenimiento Predictivo'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name asc'

    # -------------------------------------------------------------------------
    # Campos básicos
    # -------------------------------------------------------------------------
    name = fields.Char(
        string='Nombre del Plan',
        required=True,
        tracking=True,
        help='Nombre descriptivo del plan de mantenimiento.',
    )
    active = fields.Boolean(
        string='Activo',
        default=True,
        tracking=True,
    )
    notes = fields.Html(
        string='Notas',
        help='Observaciones adicionales o instrucciones del plan.',
    )

    # -------------------------------------------------------------------------
    # Relación con vehículo
    # -------------------------------------------------------------------------
    vehicle_id = fields.Many2one(
        comodel_name='fleet.vehicle',
        string='Vehículo',
        required=True,
        ondelete='cascade',
        tracking=True,
        index=True,
    )

    # -------------------------------------------------------------------------
    # Configuración de umbral / trigger
    # -------------------------------------------------------------------------
    trigger_type = fields.Selection(
        selection=[
            ('km', 'Kilometraje'),
            ('hours', 'Horas de Uso'),
            ('days', 'Días Calendario'),
            ('date', 'Fecha Fija'),
        ],
        string='Tipo de Umbral',
        required=True,
        default='km',
        tracking=True,
        help='Métrica que dispara la creación automática de una orden de mantenimiento.\n'
             '• Días Calendario: genera una orden cada N días desde el último servicio.',
    )
    threshold_value = fields.Float(
        string='Umbral de Disparo',
        digits=(10, 2),
        help='Valor acumulado al que se genera una nueva orden de mantenimiento.',
    )
    interval_value = fields.Float(
        string='Intervalo de Repetición',
        digits=(10, 2),
        help='Cada cuántas unidades se repite el mantenimiento luego del primer disparo.',
    )
    last_trigger_value = fields.Float(
        string='Último Valor Disparado',
        digits=(10, 2),
        readonly=True,
        copy=False,
        help='Valor de odómetro/horas en el que se generó la última orden.',
    )
    last_trigger_date = fields.Date(
        string='Última Ejecución (Días)',
        readonly=True,
        copy=False,
        help='Fecha en que se completó el último mantenimiento periódico por días.',
    )
    next_trigger_value = fields.Float(
        string='Próximo Disparo',
        compute='_compute_next_trigger_value',
        store=True,
        digits=(10, 2),
    )
    next_trigger_date = fields.Date(
        string='Próxima Fecha (Días)',
        compute='_compute_next_trigger_value',
        store=True,
        help='Fecha calculada para el próximo mantenimiento por días.',
    )
    trigger_date = fields.Date(
        string='Fecha de Vencimiento',
        help='Para trigger_type=date: fecha en que se genera la orden.',
    )

    # -------------------------------------------------------------------------
    # Repuestos relacionados
    # -------------------------------------------------------------------------
    part_ids = fields.One2many(
        comodel_name='pmp.maintenance.plan.line',
        inverse_name='plan_id',
        string='Repuestos Estimados',
        help='Lista de repuestos y cantidades estimadas para este plan.',
        copy=True,
    )

    # -------------------------------------------------------------------------
    # Órdenes generadas
    # -------------------------------------------------------------------------
    order_ids = fields.One2many(
        comodel_name='pmp.maintenance.order',
        inverse_name='plan_id',
        string='Órdenes de Mantenimiento',
    )
    order_count = fields.Integer(
        string='N° de Órdenes',
        compute='_compute_order_count',
    )

    # -------------------------------------------------------------------------
    # Computes
    # -------------------------------------------------------------------------
    @api.depends('last_trigger_value', 'interval_value', 'threshold_value',
                 'last_trigger_date', 'trigger_type')
    def _compute_next_trigger_value(self):
        for plan in self:
            if plan.trigger_type == 'days':
                # Próxima fecha = última ejecución + intervalo en días
                base = plan.last_trigger_date or fields.Date.today()
                interval = int(plan.interval_value or plan.threshold_value or 0)
                plan.next_trigger_date = base + timedelta(days=interval) if interval else False
                plan.next_trigger_value = 0.0
            else:
                plan.next_trigger_date = False
                if plan.last_trigger_value > 0 and plan.interval_value > 0:
                    plan.next_trigger_value = plan.last_trigger_value + plan.interval_value
                else:
                    plan.next_trigger_value = plan.threshold_value

    @api.depends('order_ids')
    def _compute_order_count(self):
        order_data = self.env['pmp.maintenance.order'].read_group(
            domain=[('plan_id', 'in', self.ids)],
            fields=['plan_id'],
            groupby=['plan_id'],
        )
        count_map = {row['plan_id'][0]: row['plan_id_count'] for row in order_data}
        for plan in self:
            plan.order_count = count_map.get(plan.id, 0)

    # -------------------------------------------------------------------------
    # Constraints
    # -------------------------------------------------------------------------
    @api.constrains('threshold_value', 'interval_value')
    def _check_positive_values(self):
        for plan in self:
            if plan.trigger_type not in ('date',):
                if plan.threshold_value <= 0:
                    raise ValidationError(
                        _('El umbral de disparo debe ser mayor a cero.')
                    )
                if plan.interval_value < 0:
                    raise ValidationError(
                        _('El intervalo de repetición no puede ser negativo.')
                    )

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------
    def _should_trigger(self, current_odometer=0.0, current_hours=0.0):
        """
        Evalúa si el plan debe disparar una nueva orden de mantenimiento.

        Args:
            current_odometer (float): Valor actual del odómetro en km.
            current_hours (float): Horas de uso actuales.

        Returns:
            bool: True si se debe generar una orden.
        """
        self.ensure_one()
        if not self.active:
            return False

        if self.trigger_type == 'km':
            next_trigger = self.next_trigger_value
            return current_odometer >= next_trigger and next_trigger > 0

        if self.trigger_type == 'hours':
            next_trigger = self.next_trigger_value
            return current_hours >= next_trigger and next_trigger > 0

        if self.trigger_type == 'days':
            # Disparar si hoy >= próxima fecha calculada
            if not self.next_trigger_date:
                return False
            return fields.Date.today() >= self.next_trigger_date

        if self.trigger_type == 'date':
            if not self.trigger_date:
                return False
            return fields.Date.today() >= self.trigger_date

        return False

    def _generate_maintenance_order(self, current_odometer=0.0):
        """
        Crea una orden de mantenimiento a partir de este plan.
        NO actualiza last_trigger_value aquí — ese valor se actualiza
        cuando la orden sea completada (action_done), para que una
        cancelación no desplace el ciclo de mantenimiento.

        Args:
            current_odometer (float): Valor actual del odómetro.

        Returns:
            pmp.maintenance.order: La orden de mantenimiento creada.
        """
        self.ensure_one()
        MaintenanceOrder = self.env['pmp.maintenance.order']

        # Construir líneas desde los repuestos del plan (con cantidades)
        lines = [
            (0, 0, {
                'product_id': line.product_id.id,
                'qty_planned': line.qty_planned,
                'unit_cost': line.unit_cost,
            })
            for line in self.part_ids
        ]

        order = MaintenanceOrder.create({
            'plan_id': self.id,
            'vehicle_id': self.vehicle_id.id,
            'date_scheduled': fields.Date.today(),
            'odometer_at_service': current_odometer,
            'hours_at_service': self.vehicle_id.current_hours,
            'line_ids': lines,
        })
        return order

    def action_view_orders(self):
        """Abre las órdenes de mantenimiento relacionadas a este plan."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Órdenes de Mantenimiento — %s') % self.name,
            'res_model': 'pmp.maintenance.order',
            'view_mode': 'list,kanban,form',
            'domain': [('plan_id', '=', self.id)],
            'context': {'default_plan_id': self.id, 'default_vehicle_id': self.vehicle_id.id},
        }

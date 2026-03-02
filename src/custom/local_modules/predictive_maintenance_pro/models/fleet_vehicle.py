# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

# Porcentaje del umbral a partir del cual se considera "Próximo"
# Ej: 0.85 = cuando el vehículo ha consumido el 85% del intervalo
UPCOMING_THRESHOLD_RATIO = 0.85


class FleetVehicle(models.Model):
    """
    Extensión del modelo fleet.vehicle para mantenimiento predictivo.

    Añade relaciones con planes y órdenes de mantenimiento, expone el
    valor actual del odómetro y provee la lógica de verificación de umbrales
    que es invocada por el cron diario.
    """

    _inherit = 'fleet.vehicle'

    # -------------------------------------------------------------------------
    # Campos de mantenimiento predictivo
    # -------------------------------------------------------------------------
    current_hours = fields.Float(
        string='Horas de Uso',
        digits=(10, 2),
        default=0.0,
        tracking=True,
        help='Horas de operación acumuladas. Actualizar manualmente o via integración.',
    )
    maintenance_plan_ids = fields.One2many(
        comodel_name='pmp.maintenance.plan',
        inverse_name='vehicle_id',
        string='Planes de Mantenimiento',
    )
    maintenance_plan_count = fields.Integer(
        string='N° Planes',
        compute='_compute_maintenance_plan_count',
    )
    maintenance_order_ids = fields.One2many(
        comodel_name='pmp.maintenance.order',
        inverse_name='vehicle_id',
        string='Órdenes de Mantenimiento',
    )
    maintenance_order_count = fields.Integer(
        string='N° Órdenes',
        compute='_compute_maintenance_order_count',
    )
    maintenance_history_ids = fields.One2many(
        comodel_name='pmp.maintenance.history',
        inverse_name='vehicle_id',
        string='Historial de Mantenimiento',
    )
    maintenance_history_count = fields.Integer(
        string='N° Servicios',
        compute='_compute_maintenance_history_count',
    )

    # -------------------------------------------------------------------------
    # Estado de mantenimiento predictivo (para el Kanban de Planificación)
    # -------------------------------------------------------------------------
    maintenance_status = fields.Selection(
        selection=[
            ('in_maintenance', 'En Mantenimiento'),
            ('upcoming', 'Próximo'),
            ('ok', 'Al Día'),
        ],
        string='Estado de Mantenimiento',
        compute='_compute_maintenance_status',
        store=True,
        default='ok',
        help=(
            'Al Día: el vehículo está dentro de los parámetros normales.\n'
            'Próximo: se ha consumido el 85%+ del intervalo — se acerca el servicio.\n'
            'En Mantenimiento: tiene una orden activa en ejecución.'
        ),
    )
    maintenance_remaining_value = fields.Float(
        string='Restante para Servicio',
        compute='_compute_maintenance_remaining',
        store=True,
        digits=(10, 0),
        help='Cantidad restante (km, horas o días) hasta el próximo servicio más cercano.',
    )
    maintenance_remaining_unit = fields.Char(
        string='Unidad Restante',
        compute='_compute_maintenance_remaining',
        store=True,
        help='Unidad de medida del campo restante (km, horas, días).',
    )

    # -------------------------------------------------------------------------
    # Computes de contadores (usando read_group para eficiencia)
    # -------------------------------------------------------------------------
    @api.depends('maintenance_plan_ids')
    def _compute_maintenance_plan_count(self):
        data = self.env['pmp.maintenance.plan'].read_group(
            domain=[('vehicle_id', 'in', self.ids), ('active', '=', True)],
            fields=['vehicle_id'],
            groupby=['vehicle_id'],
        )
        count_map = {r['vehicle_id'][0]: r['vehicle_id_count'] for r in data}
        for vehicle in self:
            vehicle.maintenance_plan_count = count_map.get(vehicle.id, 0)

    @api.depends('maintenance_order_ids')
    def _compute_maintenance_order_count(self):
        data = self.env['pmp.maintenance.order'].read_group(
            domain=[('vehicle_id', 'in', self.ids)],
            fields=['vehicle_id'],
            groupby=['vehicle_id'],
        )
        count_map = {r['vehicle_id'][0]: r['vehicle_id_count'] for r in data}
        for vehicle in self:
            vehicle.maintenance_order_count = count_map.get(vehicle.id, 0)

    @api.depends('maintenance_history_ids')
    def _compute_maintenance_history_count(self):
        data = self.env['pmp.maintenance.history'].read_group(
            domain=[('vehicle_id', 'in', self.ids)],
            fields=['vehicle_id'],
            groupby=['vehicle_id'],
        )
        count_map = {r['vehicle_id'][0]: r['vehicle_id_count'] for r in data}
        for vehicle in self:
            vehicle.maintenance_history_count = count_map.get(vehicle.id, 0)

    @api.depends(
        'maintenance_order_ids.state',
        'maintenance_plan_ids.next_trigger_value',
        'maintenance_plan_ids.last_trigger_value',
        'maintenance_plan_ids.interval_value',
        'odometer',
        'current_hours',
    )
    def _compute_maintenance_status(self):
        """
        Calcula el estado de mantenimiento del vehículo:
        - in_maintenance: tiene al menos una orden en ejecución (in_progress)
        - upcoming: ha consumido >= UPCOMING_THRESHOLD_RATIO del intervalo en algún plan
        - ok: todo normal
        """
        for vehicle in self:
            # Prioridad 1: En mantenimiento activo
            # → cualquier orden no finalizada (draft/confirmed/in_progress)
            ACTIVE_STATES = ('draft', 'confirmed', 'in_progress')
            has_active_order = any(
                o.state in ACTIVE_STATES
                for o in vehicle.maintenance_order_ids
            )
            if has_active_order:
                vehicle.maintenance_status = 'in_maintenance'
                continue

            # Prioridad 2: Próximo al umbral
            odometer = vehicle.odometer
            hours = vehicle.current_hours
            is_upcoming = False

            for plan in vehicle.maintenance_plan_ids.filtered('active'):
                next_trigger = plan.next_trigger_value

                if plan.trigger_type == 'km':
                    if next_trigger <= 0:
                        continue
                    progress = odometer / next_trigger if next_trigger else 0
                    if progress >= UPCOMING_THRESHOLD_RATIO:
                        is_upcoming = True
                        break

                elif plan.trigger_type == 'hours':
                    if next_trigger <= 0:
                        continue
                    progress = hours / next_trigger if next_trigger else 0
                    if progress >= UPCOMING_THRESHOLD_RATIO:
                        is_upcoming = True
                        break

                elif plan.trigger_type == 'days':
                    # Upcoming si faltan <= 20% de los dias del intervalo
                    if plan.next_trigger_date:
                        interval = int(plan.interval_value or plan.threshold_value or 0)
                        days_left = (plan.next_trigger_date - fields.Date.today()).days
                        upcoming_days = max(int(interval * (1 - UPCOMING_THRESHOLD_RATIO)), 1)
                        if 0 <= days_left <= upcoming_days:
                            is_upcoming = True
                            break

                elif plan.trigger_type == 'date':
                    if plan.trigger_date:
                        days_left = (plan.trigger_date - fields.Date.today()).days
                        if 0 <= days_left <= 7:
                            is_upcoming = True

            vehicle.maintenance_status = 'upcoming' if is_upcoming else 'ok'

    @api.depends(
        'maintenance_plan_ids.next_trigger_value',
        'maintenance_plan_ids.trigger_type',
        'maintenance_plan_ids.trigger_date',
        'maintenance_order_ids.state',
        'odometer',
        'current_hours',
    )
    def _compute_maintenance_remaining(self):
        """
        Calcula cuánto falta para el próximo servicio más cercano.
        Elige el plan activo con menor restante absoluto y devuelve
        el valor y la unidad correspondiente.
        """
        for vehicle in self:
            # Si está en mantenimiento activo
            if any(o.state == 'in_progress' for o in vehicle.maintenance_order_ids):
                vehicle.maintenance_remaining_value = 0.0
                vehicle.maintenance_remaining_unit = 'en servicio'
                continue

            odometer = vehicle.odometer
            hours = vehicle.current_hours
            best_remaining = None
            best_unit = ''

            for plan in vehicle.maintenance_plan_ids.filtered('active'):
                next_trigger = plan.next_trigger_value
                if next_trigger <= 0:
                    continue

                if plan.trigger_type == 'km':
                    remaining = next_trigger - odometer
                    unit = 'km'
                elif plan.trigger_type == 'hours':
                    remaining = next_trigger - hours
                    unit = 'horas'
                elif plan.trigger_type == 'date' and plan.trigger_date:
                    remaining = (plan.trigger_date - fields.Date.today()).days
                    unit = 'días'
                else:
                    continue

                if remaining < 0:
                    remaining = 0

                # Guardar el plan más urgente (menor restante)
                if best_remaining is None or remaining < best_remaining:
                    best_remaining = remaining
                    best_unit = unit

            vehicle.maintenance_remaining_value = best_remaining if best_remaining is not None else 0.0
            vehicle.maintenance_remaining_unit = best_unit


    # Lógica de negocio: verificación de umbrales
    # -------------------------------------------------------------------------
    def _get_current_odometer(self):
        """
        Retorna el valor actual del odómetro del vehículo en km.
        Usa el mecanismo nativo de fleet para obtener la última lectura.
        """
        self.ensure_one()
        return self.odometer

    def _check_maintenance_alerts(self):
        """
        Verifica si algún plan activo ha superado su umbral y genera las
        órdenes de mantenimiento correspondientes.

        Notifica al coordinador:
        - Cuando se genera una orden nueva (umbral superado → in_maintenance)
        - Cuando el vehículo entra en estado 'upcoming' (acercándose al umbral)
        """
        import logging
        _logger = logging.getLogger(__name__)
        MaintenanceOrder = self.env['pmp.maintenance.order']
        created_orders = MaintenanceOrder.browse()

        for vehicle in self:
            active_plans = vehicle.maintenance_plan_ids.filtered('active')
            if not active_plans:
                continue

            odometer = vehicle._get_current_odometer()
            hours = vehicle.current_hours
            vehicle_orders_created = MaintenanceOrder.browse()

            for plan in active_plans:
                if plan._should_trigger(odometer, hours):
                    order = plan._generate_maintenance_order(odometer)
                    vehicle_orders_created |= order
                    created_orders |= order

            # Notificar si se generaron órdenes nuevas
            if vehicle_orders_created:
                vehicle._notify_orders_generated(vehicle_orders_created)
                _logger.info(
                    'PMP: %d orden(es) generada(s) para vehículo %s',
                    len(vehicle_orders_created), vehicle.name,
                )
                continue  # ya pasó a in_maintenance, no evaluar upcoming

            # Si no se generaron órdenes, verificar si entró en 'upcoming'
            previous_status = vehicle.maintenance_status
            vehicle._compute_maintenance_status()
            if vehicle.maintenance_status == 'upcoming' and previous_status != 'upcoming':
                vehicle._notify_upcoming_maintenance()

        return created_orders

    def _notify_orders_generated(self, orders):
        """
        Crea actividad para el coordinador cuando se generan nuevas órdenes
        de mantenimiento (umbral superado → estado in_maintenance).
        """
        self.ensure_one()
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        coordinator_group = self.env.ref(
            'predictive_maintenance_pro.group_pmp_coordinator',
            raise_if_not_found=False,
        )
        if not activity_type or not coordinator_group:
            return

        order_links = ''.join(
            '<li><strong>%s</strong> — %s</li>' % (o.name, o.plan_id.name)
            for o in orders
        )
        note = _(
            '<p>El vehículo <strong>%s</strong> ha alcanzado su umbral de '
            'mantenimiento. Se han generado las siguientes órdenes de servicio:</p>'
            '<ul>%s</ul>'
            '<p>Revise y confirme las órdenes para iniciar el proceso.</p>'
        ) % (self.name, order_links)

        for user in coordinator_group.users:
            existing = self.activity_ids.filtered(
                lambda a: a.activity_type_id == activity_type
                and a.user_id == user
                and 'orden' in (a.summary or '').lower()
            )
            if existing:
                continue
            self.activity_schedule(
                activity_type_id=activity_type.id,
                summary=_('Orden de Mantenimiento Generada — %s') % self.name,
                note=note,
                user_id=user.id,
                date_deadline=fields.Date.today(),
            )

    def _notify_upcoming_maintenance(self):
        """
        Crea una actividad de alerta para los coordinadores de mantenimiento
        cuando un vehículo entra en estado 'Próximo' (se acerca al umbral).
        Además verifica el stock de repuestos y alerta a Compras si hay faltantes.
        """
        self.ensure_one()
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            return

        coordinator_group = self.env.ref(
            'predictive_maintenance_pro.group_pmp_coordinator',
            raise_if_not_found=False,
        )
        purchase_group = self.env.ref(
            'predictive_maintenance_pro.group_pmp_purchase',
            raise_if_not_found=False,
        )

        # --- Verificar stock de repuestos en planes activos ---
        shortage_lines = []
        for plan in self.maintenance_plan_ids.filtered('active'):
            for part_line in plan.part_ids:
                product = part_line.product_id
                if not product:
                    continue
                qty_available = product.qty_available
                qty_needed = part_line.qty_planned
                if qty_available < qty_needed:
                    shortage_lines.append({
                        'product': product.name,
                        'needed': qty_needed,
                        'available': qty_available,
                        'missing': qty_needed - qty_available,
                        'plan': plan.name,
                    })

        # Construir nota de faltantes para el cuerpo de la actividad
        shortage_note = ''
        if shortage_lines:
            rows = ''.join(
                '<li><strong>%s</strong> — Plan: %s | Necesario: %s | '
                'Disponible: %s | <span style="color:red">Faltante: %s</span></li>'
                % (s['product'], s['plan'], s['needed'], s['available'], s['missing'])
                for s in shortage_lines
            )
            shortage_note = _(
                '<br/><br/><strong>⚠️ REPUESTOS INSUFICIENTES:</strong><ul>%s</ul>'
                '<p>Accede a <em>Planificación → Verificar Repuestos</em> para '
                'generar las solicitudes de presupuesto.</p>'
            ) % rows

        # --- Notificar Coordinadores ---
        if coordinator_group:
            for user in coordinator_group.users:
                existing = self.activity_ids.filtered(
                    lambda a: a.activity_type_id == activity_type
                    and a.user_id == user
                    and 'próximo mantenimiento' in (a.summary or '').lower()
                )
                if existing:
                    continue
                self.activity_schedule(
                    activity_type_id=activity_type.id,
                    summary=_('Próximo Mantenimiento — %s') % self.name,
                    note=_(
                        '<p>El vehículo <strong>%s</strong> ha alcanzado el 85%% '
                        'de su intervalo de mantenimiento y requiere atención pronto.</p>'
                        '<p>Revise los planes activos y programe una orden de servicio.</p>'
                    ) % self.name + shortage_note,
                    user_id=user.id,
                    date_deadline=fields.Date.today(),
                )

        # --- Notificar Compras si hay faltantes de stock ---
        if shortage_lines and purchase_group:
            for user in purchase_group.users:
                existing = self.activity_ids.filtered(
                    lambda a: a.activity_type_id == activity_type
                    and a.user_id == user
                    and 'repuestos faltantes' in (a.summary or '').lower()
                )
                if existing:
                    continue
                self.activity_schedule(
                    activity_type_id=activity_type.id,
                    summary=_('Repuestos Faltantes — %s') % self.name,
                    note=_(
                        '<p>El vehículo <strong>%s</strong> está próximo a su '
                        'servicio de mantenimiento y no cuenta con suficiente stock '
                        'de los siguientes repuestos:</p>'
                    ) % self.name + shortage_note,
                    user_id=user.id,
                    date_deadline=fields.Date.today(),
                )
                _logger.warning(
                    'PMP: Alerta de stock insuficiente para vehículo %s → usuario compras %s. '
                    'Faltantes: %s',
                    self.name, user.name,
                    ', '.join('%s (%.0f uds)' % (s['product'], s['missing']) for s in shortage_lines),
                )


    # -------------------------------------------------------------------------
    # Smart buttons
    # -------------------------------------------------------------------------
    def action_view_maintenance_plans(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Planes de Mantenimiento — %s') % self.name,
            'res_model': 'pmp.maintenance.plan',
            'view_mode': 'list,form',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id},
        }

    def action_view_maintenance_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Órdenes de Mantenimiento — %s') % self.name,
            'res_model': 'pmp.maintenance.order',
            'view_mode': 'list,kanban,form',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id},
        }

    def action_view_maintenance_history(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Historial de Mantenimiento — %s') % self.name,
            'res_model': 'pmp.maintenance.history',
            'view_mode': 'list,form',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id},
        }

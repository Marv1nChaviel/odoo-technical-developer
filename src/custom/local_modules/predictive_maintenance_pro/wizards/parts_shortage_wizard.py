# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PartsShortageWizard(models.TransientModel):
    """
    Wizard para gestión de faltantes de repuestos en planes de mantenimiento próximos.

    Al abrir, calcula automáticamente qué repuestos faltan para los vehículos
    en estado 'upcoming' (próximos a mantenimiento). Permite generar solicitudes
    de presupuesto (RFQ) agrupadas por proveedor con un solo clic.
    """

    _name = 'pmp.parts.shortage.wizard'
    _description = 'Verificación de Repuestos Faltantes'
    _rec_name = 'create_date'

    line_ids = fields.One2many(
        comodel_name='pmp.parts.shortage.wizard.line',
        inverse_name='wizard_id',
        string='Repuestos Faltantes',
    )
    has_shortages = fields.Boolean(
        string='Hay Faltantes',
        compute='_compute_has_shortages',
    )

    @api.depends('line_ids')
    def _compute_has_shortages(self):
        for wizard in self:
            wizard.has_shortages = bool(wizard.line_ids)

    @api.model
    def default_get(self, fields_list):
        """Al abrir el wizard, calcula automáticamente los faltantes."""
        res = super().default_get(fields_list)
        lines = self._compute_shortage_lines()
        if 'line_ids' in fields_list:
            res['line_ids'] = lines
        return res

    @api.model
    def _compute_shortage_lines(self):
        """
        Calcula faltantes de repuestos considerando DOS fuentes:
        1. Órdenes abiertas (confirmed + in_progress): qty_planned - qty_delivered
        2. Planes de vehículos 'upcoming': qty_planned del plan

        Compara la necesidad total por producto contra el stock disponible.
        """
        shortage_map = {}  # key: product_id → acumula qty_needed y metadata

        # ── FUENTE 1: Órdenes de mantenimiento abiertas ──────────────────────
        open_orders = self.env['pmp.maintenance.order'].search([
            ('state', 'in', ['confirmed', 'in_progress']),
        ])
        for order in open_orders:
            vehicle = order.vehicle_id
            for line in order.line_ids:
                product = line.product_id
                if not product:
                    continue
                qty_needed = max(line.qty_planned - line.qty_delivered, 0.0)
                if qty_needed <= 0:
                    continue
                key = product.id
                note = '%s [%s]' % (vehicle.name if vehicle else '—', order.name)
                if key in shortage_map:
                    shortage_map[key]['qty_needed'] += qty_needed
                    shortage_map[key]['note'] += ', ' + note
                else:
                    supplier = product.seller_ids[:1]
                    shortage_map[key] = {
                        'product_id': product.id,
                        'qty_needed': qty_needed,
                        'qty_available': product.qty_available,
                        'supplier_id': supplier.partner_id.id if supplier else False,
                        'note': note,
                    }

        # ── FUENTE 2: Planes de vehículos próximos a mantenimiento ───────────
        upcoming_vehicles = self.env['fleet.vehicle'].search([
            ('maintenance_status', '=', 'upcoming'),
        ])
        for vehicle in upcoming_vehicles:
            for plan in vehicle.maintenance_plan_ids.filtered('active'):
                for part_line in plan.part_ids:
                    product = part_line.product_id
                    if not product:
                        continue
                    qty_needed = part_line.qty_planned
                    note = '%s (%s)' % (vehicle.name, plan.name)
                    key = product.id
                    if key in shortage_map:
                        shortage_map[key]['qty_needed'] += qty_needed
                        shortage_map[key]['note'] += ', ' + note
                    else:
                        supplier = product.seller_ids[:1]
                        shortage_map[key] = {
                            'product_id': product.id,
                            'qty_needed': qty_needed,
                            'qty_available': product.qty_available,
                            'supplier_id': supplier.partner_id.id if supplier else False,
                            'note': note,
                        }

        # ── Filtrar solo los que tienen faltante real ─────────────────────────
        lines = []
        for data in shortage_map.values():
            qty_missing = data['qty_needed'] - data['qty_available']
            if qty_missing <= 0:
                continue
            lines.append((0, 0, {
                'product_id': data['product_id'],
                'qty_needed': data['qty_needed'],
                'qty_available': data['qty_available'],
                'qty_missing': qty_missing,
                'supplier_id': data['supplier_id'],
                'note': data['note'],
            }))
        return lines

    def action_generate_rfq(self):
        """
        Genera Solicitudes de Presupuesto (RFQ) agrupadas por proveedor.
        Recomputa los faltantes directo del stock para evitar el problema
        de self.line_ids vacío en wizards transient de Odoo 18.
        Respeta los supplier_id que el usuario haya editado en el wizard.
        """
        self.ensure_one()
        import logging
        _logger = logging.getLogger(__name__)

        PurchaseOrder = self.env['purchase.order']
        created_orders = PurchaseOrder.browse()
        no_supplier = []
        errors = []

        # Obtener overrides de proveedor del wizard (si tiene líneas guardadas)
        supplier_overrides = {
            line.product_id.id: line.supplier_id
            for line in self.line_ids
            if line.product_id and line.supplier_id
        }

        # Recomputar faltantes directamente desde stock (más robusto)
        upcoming_vehicles = self.env['fleet.vehicle'].search([
            ('maintenance_status', '=', 'upcoming'),
        ])

        shortage_map = {}

        # ── FUENTE 1: Órdenes abiertas (confirmed + in_progress) ─────────────
        open_orders = self.env['pmp.maintenance.order'].search([
            ('state', 'in', ['confirmed', 'in_progress']),
        ])
        for order in open_orders:
            vehicle = order.vehicle_id
            for line in order.line_ids:
                product = line.product_id
                if not product:
                    continue
                qty_missing = max(line.qty_planned - line.qty_delivered - product.qty_available, 0.0)
                # Necesidad pendiente (no entregado aún)
                qty_still_needed = max(line.qty_planned - line.qty_delivered, 0.0)
                if qty_still_needed <= 0:
                    continue
                real_missing = qty_still_needed - product.qty_available
                if real_missing <= 0:
                    continue
                key = product.id
                if key in shortage_map:
                    shortage_map[key]['qty_missing'] += real_missing
                else:
                    partner = supplier_overrides.get(key)
                    if not partner:
                        seller = product.seller_ids[:1]
                        partner = seller.partner_id if seller else self.env['res.partner']
                    shortage_map[key] = {
                        'product': product,
                        'qty_missing': real_missing,
                        'partner': partner,
                    }

        # ── FUENTE 2: Planes de vehículos próximos a mantenimiento ───────────
        upcoming_vehicles = self.env['fleet.vehicle'].search([
            ('maintenance_status', '=', 'upcoming'),
        ])
        for vehicle in upcoming_vehicles:
            for plan in vehicle.maintenance_plan_ids.filtered('active'):
                for part_line in plan.part_ids:
                    product = part_line.product_id
                    if not product:
                        continue
                    qty_missing = part_line.qty_planned - product.qty_available
                    if qty_missing <= 0:
                        continue
                    key = product.id
                    if key in shortage_map:
                        shortage_map[key]['qty_missing'] += qty_missing
                    else:
                        partner = supplier_overrides.get(key)
                        if not partner:
                            seller = product.seller_ids[:1]
                            partner = seller.partner_id if seller else self.env['res.partner']
                        shortage_map[key] = {
                            'product': product,
                            'qty_missing': qty_missing,
                            'partner': partner,
                        }

        if not shortage_map:
            raise UserError(
                _('No hay repuestos faltantes para las órdenes abiertas ni vehículos próximos a mantenimiento.')
            )

        # Agrupar por proveedor y crear RFQs
        supplier_lines = {}
        for data in shortage_map.values():
            partner = data['partner']
            if not partner:
                no_supplier.append(data['product'].name)
                continue
            if partner.id not in supplier_lines:
                supplier_lines[partner.id] = (partner, [])
            supplier_lines[partner.id][1].append(data)

        updated_orders = PurchaseOrder.browse()
        skipped_confirmed = []   # POs ya confirmados, no se tocan

        for partner_id, (partner, items) in supplier_lines.items():
            try:
                # ── Buscar RFQs en borrador para este proveedor con productos PMP ──
                product_ids = [item['product'].id for item in items]
                existing_draft = PurchaseOrder.search([
                    ('partner_id', '=', partner_id),
                    ('state', '=', 'draft'),
                    ('order_line.product_id', 'in', product_ids),
                ], limit=1, order='id desc')

                # ── Buscar POs confirmados con entregas AÚN PENDIENTES ────────
                # No se puede comparar dos campos en domain de Odoo, filtramos en Python.
                confirmed_pos = PurchaseOrder.search([
                    ('partner_id', '=', partner_id),
                    ('state', '=', 'purchase'),
                    ('order_line.product_id', 'in', product_ids),
                ])
                confirmed_with_pending = confirmed_pos.filtered(
                    lambda po: any(
                        l.qty_received < l.product_qty
                        for l in po.order_line
                        if l.product_id.id in product_ids
                    )
                )[:1]

                if confirmed_with_pending and not existing_draft:
                    skipped_confirmed.append(
                        '%s (%s) — entrega pendiente' % (partner.name, confirmed_with_pending.name)
                    )
                    _logger.info('PMP: PO %s tiene entregas pendientes para %s — omitido', confirmed_with_pending.name, partner.name)
                    continue

                if existing_draft:
                    # ── Actualizar líneas del borrador existente ──────────────────
                    rfq = existing_draft
                    for item in items:
                        product = item['product']
                        qty_new = item['qty_missing']
                        # Buscar línea existente del mismo producto en el RFQ
                        existing_line = rfq.order_line.filtered(
                            lambda l, p=product: l.product_id.id == p.id
                        )
                        if existing_line:
                            line = existing_line[0]
                            if qty_new > line.product_qty:
                                # Solo actualizar si la cantidad nueva es mayor
                                line.write({'product_qty': qty_new})
                                _logger.info(
                                    'PMP: Actualizada línea %s en RFQ %s: %s → %s',
                                    product.name, rfq.name, line.product_qty, qty_new,
                                )
                        else:
                            # Producto nuevo en el RFQ existente → agregar línea
                            rfq.write({'order_line': [(0, 0, {
                                'product_id': product.id,
                                'product_qty': qty_new,
                                'price_unit': product.standard_price,
                                'product_uom': product.uom_po_id.id or product.uom_id.id,
                                'name': product.name + ' [PMP]',
                                'date_planned': fields.Datetime.now(),
                            })]})
                    created_orders |= rfq
                    updated_orders |= rfq
                    _logger.info('PMP: RFQ %s actualizado para %s', rfq.name, partner.name)

                else:
                    # ── Crear RFQ nuevo ───────────────────────────────────────────
                    order_lines = [(0, 0, {
                        'product_id': item['product'].id,
                        'product_qty': item['qty_missing'],
                        'price_unit': item['product'].standard_price,
                        'product_uom': item['product'].uom_po_id.id or item['product'].uom_id.id,
                        'name': item['product'].name + ' [PMP]',
                        'date_planned': fields.Datetime.now(),
                    }) for item in items]

                    rfq = PurchaseOrder.create({
                        'partner_id': partner_id,
                        'order_line': order_lines,
                    })
                    created_orders |= rfq
                    _logger.info('PMP: RFQ %s creado para %s (%d líneas)', rfq.name, partner.name, len(order_lines))

            except Exception as exc:
                _logger.exception('PMP: Error al procesar RFQ para %s', partner.name)
                errors.append('• %s: %s' % (partner.name, str(exc)))

        if not created_orders and not skipped_confirmed:
            detail_parts = []
            if no_supplier:
                detail_parts.append(_('Sin proveedor:\n') + '\n'.join(no_supplier))
            if errors:
                detail_parts.append(_('Errores:\n') + '\n'.join(errors))
            msg = _('No se pudieron crear solicitudes de presupuesto.')
            if detail_parts:
                msg += '\n\n' + '\n\n'.join(detail_parts)
            raise UserError(msg)

        if not created_orders and skipped_confirmed:
            # Todo ya estaba confirmado, nada que crear ni actualizar
            msg = _(
                'Las compras para estos proveedores ya están confirmadas y no se pueden modificar:\n%s\n\n'
                'Si necesita más stock, cree una nueva orden de compra manualmente.'
            ) % '\n'.join(skipped_confirmed)
            raise UserError(msg)

        # Construir mensaje de resultado
        result_name = _('Solicitudes de Presupuesto')
        if updated_orders and (created_orders - updated_orders):
            result_name = _('Compras Creadas y Actualizadas [PMP]')
        elif updated_orders:
            result_name = _('Compras Actualizadas [PMP]')

        return {
            'type': 'ir.actions.act_window',
            'name': result_name,
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created_orders.ids)],
        }




class PartsShortageWizardLine(models.TransientModel):
    """Línea de repuesto faltante en el wizard de verificación de stock."""

    _name = 'pmp.parts.shortage.wizard.line'
    _description = 'Línea de Repuesto Faltante'

    wizard_id = fields.Many2one(
        comodel_name='pmp.parts.shortage.wizard',
        string='Wizard',
        ondelete='cascade',
    )
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Repuesto / Producto',
        readonly=True,
    )
    product_uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string='Unidad',
        related='product_id.uom_id',
        readonly=True,
    )
    qty_needed = fields.Float(string='Cantidad Necesaria', readonly=True, digits='Product Unit of Measure')
    qty_available = fields.Float(string='Disponible en Stock', readonly=True, digits='Product Unit of Measure')
    qty_missing = fields.Float(string='Cantidad Faltante', readonly=True, digits='Product Unit of Measure')
    supplier_id = fields.Many2one(
        comodel_name='res.partner',
        string='Proveedor Principal',
    )
    note = fields.Char(string='Vehículo / Plan', readonly=True)

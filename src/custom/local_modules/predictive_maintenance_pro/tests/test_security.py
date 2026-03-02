# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import AccessError


class TestSecurityRoles(TransactionCase):
    """
    Tests de seguridad y acceso por rol.

    Verifica que cada grupo (Coordinador, Técnico, Compras) tiene exactamente
    los permisos que se definieron en ir.model.access.csv e ir_rules.xml.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Modelos compartidos
        cls.model_brand = cls.env['fleet.vehicle.model.brand'].create({
            'name': 'Marca Seg Test',
        })
        cls.model_vehicle = cls.env['fleet.vehicle.model'].create({
            'name': 'Modelo Seg Test',
            'brand_id': cls.model_brand.id,
        })
        # Grupos del módulo
        cls.group_coordinator = cls.env.ref(
            'predictive_maintenance_pro.group_pmp_coordinator'
        )
        cls.group_technician = cls.env.ref(
            'predictive_maintenance_pro.group_pmp_technician'
        )
        cls.group_purchase = cls.env.ref(
            'predictive_maintenance_pro.group_pmp_purchase'
        )
        # Usuarios de prueba
        cls.coordinator = cls.env['res.users'].create({
            'name': 'Juan Coordinador',
            'login': 'juan_coord_test',
            'groups_id': [(6, 0, [cls.group_coordinator.id])],
        })
        cls.technician = cls.env['res.users'].create({
            'name': 'Carlos Técnico',
            'login': 'carlos_tech_test',
            'groups_id': [(6, 0, [cls.group_technician.id])],
        })
        cls.purchase = cls.env['res.users'].create({
            'name': 'Ana Compras',
            'login': 'ana_purchase_test',
            'groups_id': [(6, 0, [cls.group_purchase.id])],
        })
        # Vehículo base
        cls.vehicle = cls.env['fleet.vehicle'].create({
            'model_id': cls.model_vehicle.id,
            'license_plate': 'SEC-001',
        })

    # -------------------------------------------------------------------------
    # Coordinador
    # -------------------------------------------------------------------------
    def test_coordinator_can_create_plan(self):
        """El coordinador puede crear planes de mantenimiento."""
        plan = self.env['pmp.maintenance.plan'].with_user(self.coordinator).create({
            'name': 'Plan Coord Test',
            'vehicle_id': self.vehicle.id,
            'trigger_type': 'km',
            'threshold_value': 5000.0,
            'interval_value': 5000.0,
        })
        self.assertTrue(plan.id)

    def test_coordinator_can_create_order(self):
        """El coordinador puede crear órdenes de mantenimiento."""
        order = self.env['pmp.maintenance.order'].with_user(self.coordinator).create({
            'vehicle_id': self.vehicle.id,
            'date_scheduled': '2026-03-01',
        })
        self.assertTrue(order.id)

    # -------------------------------------------------------------------------
    # Técnico
    # -------------------------------------------------------------------------
    def test_technician_cannot_create_plan(self):
        """El técnico NO puede crear planes de mantenimiento."""
        with self.assertRaises(AccessError):
            self.env['pmp.maintenance.plan'].with_user(self.technician).create({
                'name': 'Plan Tecnico Test',
                'vehicle_id': self.vehicle.id,
                'trigger_type': 'km',
                'threshold_value': 5000.0,
                'interval_value': 5000.0,
            })

    def test_technician_can_read_plan(self):
        """El técnico puede leer planes de mantenimiento."""
        # Crear plan como admin primero
        plan = self.env['pmp.maintenance.plan'].create({
            'name': 'Plan Lectura Test',
            'vehicle_id': self.vehicle.id,
            'trigger_type': 'km',
            'threshold_value': 5000.0,
            'interval_value': 5000.0,
        })
        found = self.env['pmp.maintenance.plan'].with_user(
            self.technician
        ).search([('id', '=', plan.id)])
        self.assertTrue(found)

    def test_technician_can_update_assigned_order(self):
        """El técnico puede modificar órdenes que le están asignadas."""
        order = self.env['pmp.maintenance.order'].create({
            'vehicle_id': self.vehicle.id,
            'date_scheduled': '2026-03-01',
            'technician_id': self.technician.id,
        })
        # El técnico debe poder editar sus propias órdenes
        order.with_user(self.technician).write({'notes': '<p>Revisado</p>'})
        self.assertEqual(order.notes, '<p>Revisado</p>')

    # -------------------------------------------------------------------------
    # Compras
    # -------------------------------------------------------------------------
    def test_purchase_can_read_order(self):
        """El usuario de compras puede leer órdenes de mantenimiento."""
        order = self.env['pmp.maintenance.order'].create({
            'vehicle_id': self.vehicle.id,
            'date_scheduled': '2026-03-01',
        })
        found = self.env['pmp.maintenance.order'].with_user(
            self.purchase
        ).search([('id', '=', order.id)])
        self.assertTrue(found)

    def test_purchase_cannot_write_order(self):
        """El usuario de compras NO puede modificar órdenes."""
        order = self.env['pmp.maintenance.order'].create({
            'vehicle_id': self.vehicle.id,
            'date_scheduled': '2026-03-01',
        })
        with self.assertRaises(AccessError):
            order.with_user(self.purchase).write({'planned_cost': 9999.0})

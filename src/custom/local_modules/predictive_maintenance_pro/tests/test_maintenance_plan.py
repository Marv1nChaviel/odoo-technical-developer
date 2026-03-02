# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestMaintenancePlan(TransactionCase):
    """
    Tests unitarios para el modelo pmp.maintenance.plan.

    Verifica la creación, validaciones y computes del plan de mantenimiento.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Categoría de vehículo
        cls.category = cls.env['fleet.vehicle.model.category'].create({
            'name': 'Camión Test',
        })
        # Modelo de vehículo
        cls.model = cls.env['fleet.vehicle.model'].create({
            'name': 'Modelo Test',
            'brand_id': cls.env['fleet.vehicle.model.brand'].create({
                'name': 'Marca Test',
            }).id,
        })
        # Vehículo de prueba
        cls.vehicle = cls.env['fleet.vehicle'].create({
            'model_id': cls.model.id,
            'license_plate': 'TEST-001',
        })

    def _build_plan(self, **kwargs):
        """Helper para crear un plan con valores base."""
        defaults = {
            'name': 'Plan de Prueba',
            'vehicle_id': self.vehicle.id,
            'trigger_type': 'km',
            'threshold_value': 5000.0,
            'interval_value': 5000.0,
        }
        defaults.update(kwargs)
        return self.env['pmp.maintenance.plan'].create(defaults)

    def test_plan_creation_km(self):
        """Debe crear correctamente un plan de tipo km."""
        plan = self._build_plan()
        self.assertEqual(plan.name, 'Plan de Prueba')
        self.assertEqual(plan.trigger_type, 'km')
        self.assertEqual(plan.threshold_value, 5000.0)
        self.assertTrue(plan.active)

    def test_plan_creation_hours(self):
        """Debe crear un plan de tipo horas correctamente."""
        plan = self._build_plan(
            name='Plan Horas',
            trigger_type='hours',
            threshold_value=250.0,
            interval_value=250.0,
        )
        self.assertEqual(plan.trigger_type, 'hours')
        self.assertEqual(plan.threshold_value, 250.0)

    def test_plan_negative_threshold_raises(self):
        """Un umbral negativo o cero debe lanzar ValidationError."""
        with self.assertRaises(ValidationError):
            self._build_plan(threshold_value=0.0)

    def test_plan_negative_interval_raises(self):
        """Un intervalo negativo debe lanzar ValidationError."""
        with self.assertRaises(ValidationError):
            self._build_plan(interval_value=-100.0)

    def test_next_trigger_value_first_cycle(self):
        """En el primer ciclo, next_trigger_value debe ser igual a threshold_value."""
        plan = self._build_plan(threshold_value=10000.0)
        self.assertEqual(plan.next_trigger_value, plan.threshold_value)

    def test_next_trigger_value_after_trigger(self):
        """Tras un disparo, next_trigger_value debe ser last_trigger + interval."""
        plan = self._build_plan(threshold_value=5000.0, interval_value=5000.0)
        plan.write({'last_trigger_value': 5000.0})
        self.assertEqual(plan.next_trigger_value, 10000.0)

    def test_order_count_computed(self):
        """order_count debe reflejar el número de órdenes generadas."""
        plan = self._build_plan()
        self.assertEqual(plan.order_count, 0)
        self.env['pmp.maintenance.order'].create({
            'plan_id': plan.id,
            'vehicle_id': self.vehicle.id,
            'date_scheduled': '2026-03-01',
        })
        plan.invalidate_recordset(['order_count'])
        self.assertEqual(plan.order_count, 1)

    def test_vehicle_relationship(self):
        """El plan debe estar vinculado al vehículo correcto."""
        plan = self._build_plan()
        self.assertEqual(plan.vehicle_id, self.vehicle)

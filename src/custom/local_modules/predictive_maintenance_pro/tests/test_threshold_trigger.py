# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestThresholdTrigger(TransactionCase):
    """
    Tests de integración para la lógica de disparo automático de órdenes.

    Verifica que el cron y _check_maintenance_alerts() generen correctamente
    órdenes cuando los umbrales son superados.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = cls.env['fleet.vehicle.model'].create({
            'name': 'Modelo Trigger',
            'brand_id': cls.env['fleet.vehicle.model.brand'].create({
                'name': 'Marca Trigger',
            }).id,
        })
        cls.vehicle = cls.env['fleet.vehicle'].create({
            'model_id': cls.model.id,
            'license_plate': 'TRIG-001',
        })

    def _create_plan_km(self, threshold, interval=None, last_trigger=0.0):
        """Helper para crear plan por km."""
        return self.env['pmp.maintenance.plan'].create({
            'name': f'Plan KM {threshold}',
            'vehicle_id': self.vehicle.id,
            'trigger_type': 'km',
            'threshold_value': threshold,
            'interval_value': interval or threshold,
            'last_trigger_value': last_trigger,
        })

    def _create_plan_hours(self, threshold, interval=None, last_trigger=0.0):
        """Helper para crear plan por horas."""
        return self.env['pmp.maintenance.plan'].create({
            'name': f'Plan Horas {threshold}',
            'vehicle_id': self.vehicle.id,
            'trigger_type': 'hours',
            'threshold_value': threshold,
            'interval_value': interval or threshold,
            'last_trigger_value': last_trigger,
        })

    def test_should_trigger_km_below_threshold(self):
        """_should_trigger debe retornar False si el odómetro no supera el umbral."""
        plan = self._create_plan_km(threshold=10000)
        self.assertFalse(plan._should_trigger(current_odometer=5000.0))

    def test_should_trigger_km_at_threshold(self):
        """_should_trigger debe retornar True cuando el odómetro alcanza exactamente el umbral."""
        plan = self._create_plan_km(threshold=10000)
        self.assertTrue(plan._should_trigger(current_odometer=10000.0))

    def test_should_trigger_km_above_threshold(self):
        """_should_trigger debe retornar True cuando el odómetro supera el umbral."""
        plan = self._create_plan_km(threshold=10000)
        self.assertTrue(plan._should_trigger(current_odometer=12000.0))

    def test_should_trigger_hours_below_threshold(self):
        """_should_trigger no dispara si las horas son menores al umbral."""
        plan = self._create_plan_hours(threshold=500)
        self.assertFalse(plan._should_trigger(current_hours=300.0))

    def test_should_trigger_hours_above_threshold(self):
        """_should_trigger dispara cuando las horas superan el umbral."""
        plan = self._create_plan_hours(threshold=500)
        self.assertTrue(plan._should_trigger(current_hours=600.0))

    def test_inactive_plan_not_triggered(self):
        """Un plan inactivo no debe generar órdenes."""
        plan = self._create_plan_km(threshold=5000)
        plan.write({'active': False})
        self.assertFalse(plan._should_trigger(current_odometer=10000.0))

    def test_interval_respected_after_first_trigger(self):
        """Tras el primer disparo, solo debe volver a disparar en el siguiente intervalo."""
        plan = self._create_plan_km(threshold=5000, interval=5000, last_trigger=5000)
        # Odómetro en 7000 km: no alcanzó aún el próximo intervalo (10,000)
        self.assertFalse(plan._should_trigger(current_odometer=7000.0))
        # Odómetro en 10,000 km: alcanzó el próximo intervalo
        self.assertTrue(plan._should_trigger(current_odometer=10000.0))

    def test_generate_order_creates_record(self):
        """_generate_maintenance_order debe crear una orden de mantenimiento."""
        plan = self._create_plan_km(threshold=5000)
        orders_before = self.env['pmp.maintenance.order'].search_count(
            [('plan_id', '=', plan.id)]
        )
        plan._generate_maintenance_order(current_odometer=5000.0)
        orders_after = self.env['pmp.maintenance.order'].search_count(
            [('plan_id', '=', plan.id)]
        )
        self.assertEqual(orders_after, orders_before + 1)

    def test_generate_order_does_not_update_last_trigger_value(self):
        """_generate_maintenance_order NO debe actualizar last_trigger_value.
        Ese valor se actualiza al completar la orden (action_done),
        para que una cancelación no desplace el ciclo de mantenimiento."""
        plan = self._create_plan_km(threshold=5000)
        plan._generate_maintenance_order(current_odometer=5300.0)
        # last_trigger_value debe seguir en 0 — solo cambia en action_done
        self.assertAlmostEqual(plan.last_trigger_value, 0.0)

    def test_check_maintenance_alerts_end_to_end(self):
        """_check_maintenance_alerts debe generar orden para el vehículo con umbral superado."""
        plan = self._create_plan_km(threshold=1000)

        # Simular odómetro del vehículo via una lectura
        self.env['fleet.vehicle.odometer'].create({
            'vehicle_id': self.vehicle.id,
            'value': 2000.0,
            'date': '2026-03-01',
        })
        # Invalidar caché para que _get_current_odometer lea el nuevo valor
        self.vehicle.invalidate_recordset()

        orders_before = self.env['pmp.maintenance.order'].search_count(
            [('vehicle_id', '=', self.vehicle.id), ('plan_id', '=', plan.id)]
        )
        self.vehicle._check_maintenance_alerts()
        orders_after = self.env['pmp.maintenance.order'].search_count(
            [('vehicle_id', '=', self.vehicle.id), ('plan_id', '=', plan.id)]
        )
        self.assertEqual(orders_after, orders_before + 1)

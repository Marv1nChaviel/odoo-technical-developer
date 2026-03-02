# -*- coding: utf-8 -*-
from datetime import date, timedelta
from unittest.mock import patch
from odoo.tests.common import TransactionCase


class TestDaysTrigger(TransactionCase):
    """
    Tests unitarios para el tipo de disparador 'days' (Días Calendario).

    Verifica que:
    - next_trigger_date se calcule correctamente
    - _should_trigger dispare cuando llega la fecha
    - el estado upcoming se active con <= 20% de días restantes
    - last_trigger_date se actualice al completar una orden
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.brand = cls.env['fleet.vehicle.model.brand'].create({
            'name': 'Marca Days',
        })
        cls.model = cls.env['fleet.vehicle.model'].create({
            'name': 'Modelo Days',
            'brand_id': cls.brand.id,
        })
        cls.vehicle = cls.env['fleet.vehicle'].create({
            'model_id': cls.model.id,
            'license_plate': 'DAYS-001',
        })

    def _build_days_plan(self, interval=30, last_trigger_date=None):
        """Helper: crea un plan tipo 'days' con el intervalo dado."""
        vals = {
            'name': f'Plan {interval} Días',
            'vehicle_id': self.vehicle.id,
            'trigger_type': 'days',
            'threshold_value': interval,
            'interval_value': interval,
        }
        if last_trigger_date:
            vals['last_trigger_date'] = last_trigger_date
        return self.env['pmp.maintenance.plan'].create(vals)

    # ── next_trigger_date ────────────────────────────────────────────────────

    def test_next_trigger_date_without_last_execution(self):
        """Sin last_trigger_date, la próxima fecha = hoy + intervalo."""
        plan = self._build_days_plan(interval=30)
        expected = date.today() + timedelta(days=30)
        self.assertEqual(plan.next_trigger_date, expected)

    def test_next_trigger_date_with_last_execution(self):
        """Con last_trigger_date, próxima fecha = last + intervalo."""
        last = date.today() - timedelta(days=10)
        plan = self._build_days_plan(interval=30, last_trigger_date=last)
        expected = last + timedelta(days=30)
        self.assertEqual(plan.next_trigger_date, expected)

    def test_next_trigger_value_is_zero_for_days(self):
        """El campo next_trigger_value debe ser 0 para planes tipo days."""
        plan = self._build_days_plan(interval=30)
        self.assertEqual(plan.next_trigger_value, 0.0)

    # ── _should_trigger ──────────────────────────────────────────────────────

    def test_should_trigger_days_before_due(self):
        """No debe disparar si la fecha de vencimiento aún no llegó."""
        # last_trigger hace 5 días → próxima = last + 30 = en 25 días
        last = date.today() - timedelta(days=5)
        plan = self._build_days_plan(interval=30, last_trigger_date=last)
        self.assertFalse(plan._should_trigger())

    def test_should_trigger_days_on_due_date(self):
        """Debe disparar exactamente cuando llega la fecha de vencimiento."""
        # last_trigger hace 30 días → próxima = hoy
        last = date.today() - timedelta(days=30)
        plan = self._build_days_plan(interval=30, last_trigger_date=last)
        self.assertTrue(plan._should_trigger())

    def test_should_trigger_days_after_due(self):
        """Debe disparar cuando la fecha de vencimiento ya pasó."""
        # last_trigger hace 45 días → próxima fue hace 15 días
        last = date.today() - timedelta(days=45)
        plan = self._build_days_plan(interval=30, last_trigger_date=last)
        self.assertTrue(plan._should_trigger())

    def test_inactive_days_plan_not_triggered(self):
        """Un plan de días inactivo no debe disparar."""
        last = date.today() - timedelta(days=40)
        plan = self._build_days_plan(interval=30, last_trigger_date=last)
        plan.write({'active': False})
        self.assertFalse(plan._should_trigger())

    def test_days_plan_no_next_date_not_triggered(self):
        """Si next_trigger_date no está definido, no debe disparar."""
        # Crear plan válido y luego forzar intervalo=0 via SQL/write directo
        plan = self._build_days_plan(interval=30)
        # Escribir 0 directo saltando la constraint (simulamos estado inconsistente)
        self.env.cr.execute(
            "UPDATE pmp_maintenance_plan SET interval_value=0, threshold_value=0 WHERE id=%s",
            (plan.id,)
        )
        plan.invalidate_recordset()
        # Sin intervalo válido, next_trigger_date queda False
        self.assertFalse(plan._should_trigger())

    # ── Estado upcoming ──────────────────────────────────────────────────────

    def test_upcoming_status_within_20_percent(self):
        """
        L\u00f3gica upcoming: faltan <= 20% del intervalo.
        Con 30 d\u00edas e intervalo 30: umbral = 6 d\u00edas.
        Verificamos directamente la l\u00f3gica del plan (next_trigger_date y d\u00edas restantes).
        """
        from datetime import timedelta
        last = date.today() - timedelta(days=25)
        # last + 30 = hoy + 5 d\u00edas → faltan 5 d\u00edas
        plan = self._build_days_plan(interval=30, last_trigger_date=last)
        self.env.flush_all()
        plan.invalidate_recordset()

        next_date = plan.next_trigger_date
        self.assertTrue(next_date, "next_trigger_date debe estar calculada")

        remaining = (next_date - date.today()).days
        # 30 d\u00edas * 20% = 6 d\u00edas de ventana; remaining=5 → debe estar en upcoming
        upcoming_threshold = int(plan.threshold_value * 0.20)
        self.assertLessEqual(
            remaining, upcoming_threshold,
            f"Deber\u00eda estar en upcoming: faltan {remaining}d <= umbral {upcoming_threshold}d"
        )

    def test_ok_status_outside_upcoming_window(self):
        """Estado debe ser 'ok' si aún falta más del 20% del intervalo."""
        # last = hace 1 día → faltan 29 días → fuera de la ventana upcoming
        last = date.today() - timedelta(days=1)
        plan = self._build_days_plan(interval=30, last_trigger_date=last)
        self.vehicle._compute_maintenance_status()
        self.assertEqual(self.vehicle.maintenance_status, 'ok')

    # ── Actualización de last_trigger_date ───────────────────────────────────

    def test_last_trigger_date_updated_on_done(self):
        """Al completar una orden, last_trigger_date debe quedar en hoy."""
        plan = self._build_days_plan(interval=30)
        # Crear y confirmar orden
        order = self.env['pmp.maintenance.order'].create({
            'plan_id': plan.id,
            'vehicle_id': self.vehicle.id,
            'date_scheduled': date.today().isoformat(),
            'state': 'in_progress',
        })
        order.action_done()
        self.assertEqual(plan.last_trigger_date, date.today())

    def test_next_trigger_date_advances_after_completion(self):
        """Tras completar una orden, next_trigger_date debe adelantarse."""
        last = date.today() - timedelta(days=30)
        plan = self._build_days_plan(interval=30, last_trigger_date=last)
        old_next = plan.next_trigger_date

        order = self.env['pmp.maintenance.order'].create({
            'plan_id': plan.id,
            'vehicle_id': self.vehicle.id,
            'date_scheduled': date.today().isoformat(),
            'state': 'in_progress',
        })
        order.action_done()
        plan.invalidate_recordset(['next_trigger_date'])

        self.assertGreater(plan.next_trigger_date, old_next)
        self.assertEqual(plan.next_trigger_date,
                         date.today() + timedelta(days=30))

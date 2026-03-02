# Predictive Maintenance Pro — Odoo 18

Módulo desarrollado por **Ing. Marvin Chaviel** para **Mastercore**.

Gestión de **mantenimiento preventivo y predictivo** para flotas de vehículos y maquinaria pesada.

---

## 📋 Características Principales

| Funcionalidad | Descripción |
|---|---|
| **Planes Dinámicos** | Disparan órdenes por km, horas, **días calendario** o fecha fija |
| **Órdenes de Mantenimiento** | Ciclo completo: borrador → confirmada → en ejecución → completada / cancelada |
| **Control de Repuestos** | Qty planificada vs entregada con costo por línea; picking automático al confirmar |
| **Análisis de Costos** | Costo planificado vs real con variación calculada automáticamente |
| **Historial de Reemplazos** | Registro automático al cerrar cada orden con métricas de vida útil del repuesto |
| **Métricas por Repuesto** | km y horas desde el último cambio, costo/km y costo/hora por pieza |
| **Wizard de Faltantes** | Detecta stock insuficiente en órdenes abiertas + planes upcoming; genera RFQ por proveedor |
| **Alertas Proactivas** | Al entrar en estado "Próximo", notifica al coordinador y a Compras si hay faltantes de stock |
| **Dashboard Coordinador** | KPIs en tiempo real: órdenes, costos, variación vs presupuesto, estado de flota |
| **Filtros de Período** | Dashboard filtrable por Este Mes / Mes Anterior / Este Año o rango personalizado |
| **Roles Diferenciados** | Coordinador, Técnico y Compras con permisos específicos de acceso |
| **Cron Automático** | Verificación diaria de umbrales y generación automática de órdenes |
| **Reporte PDF** | Orden de trabajo imprimible con tabla de repuestos, costos y área de firmas |

---

## 🔧 Tipos de Disparador para Planes

| Tipo | Descripción | Campo clave |
|---|---|---|
| `km` | Genera orden cuando el odómetro supera el umbral | `next_trigger_value` en km |
| `hours` | Genera orden cuando las horas de uso superan el umbral | `next_trigger_value` en horas |
| `days` | Genera orden cada N días calendario desde el último servicio | `next_trigger_date` calculada automáticamente |
| `date` | Genera orden en una fecha fija (único disparo) | `trigger_date` |

El estado **Próximo (upcoming)** se activa:
- `km` / `hours`: cuando el vehículo ha consumido ≥ **85%** del intervalo
- `days`: cuando faltan ≤ **20%** de los días del intervalo
- `date`: cuando faltan ≤ **7 días** para la fecha

---

## 🔄 Flujo de una Orden de Mantenimiento

```
Plan activo → [CRON diario verifica umbral] → Orden generada automáticamente
                                                         │
                             BORRADOR ──────────────►    │
                               │                         │
                        [Coordinador confirma +          │
                         crea picking de repuestos]      │
                               │                         │
                         CONFIRMADA ─────────────────►   │
                               │                         │
                        [Técnico inicia trabajo]          │
                               │                         │
                         EN EJECUCIÓN ───────────────►   │
                               │
                   [Técnico completa + registra repuestos entregados]
                               │
                          COMPLETADA ──► [Historial creado + last_trigger actualizado]
```

---

## 👥 Roles y Permisos

| Rol | Planes | Órdenes | Historial | Dashboard | Wizard Faltantes | Reportes |
|---|---|---|---|---|---|---|
| **Coordinador** | CRUD | CRUD (puede forzar cierre) | CRUD | ✅ | ✅ | ✅ |
| **Técnico** | Lectura | Leer + modificar (propias) | Lectura | ❌ | ❌ | ❌ |
| **Compras** | Lectura | Lectura | Lectura | ❌ | ✅ | ✅ |

> El Técnico solo puede ver y modificar órdenes asignadas a él (record rule en `ir_rules.xml`).
> Los campos de costo son visibles solo para Coordinador y Compras.

---

## 📐 Modelos del Módulo

| Modelo | Descripción |
|---|---|
| `pmp.maintenance.plan` | Plan con tipo de umbral (km/hours/days/date), repuestos estimados y conteo de órdenes |
| `pmp.maintenance.order` | Orden de trabajo: estado, líneas de repuestos, costos real vs planificado, picking |
| `pmp.maintenance.order.line` | Líneas con qty planificada, entregada, costo unitario y subtotal |
| `pmp.maintenance.history` | Cabecera del historial por vehículo por cada servicio completado |
| `pmp.maintenance.history.line` | Detalle por repuesto: vida útil (km/h), costo/km, costo/hora; campos related `vehicle_id`, `service_date` |
| `pmp.dashboard` | Dashboard transient del coordinador con KPIs calculados por período |
| `pmp.parts.shortage.wizard` | Wizard que calcula faltantes de stock y crea RFQs por proveedor |
| `fleet.vehicle` *(ext.)* | Extendido con planes, órdenes, estado de mantenimiento y horas de uso |

---

## Reemplazos de Repuestos

Vista global de todas las piezas sustituidas en cada mantenimiento, accesible desde el menú **Historial → Reemplazos de Repuestos**.

**Columnas disponibles:**

| Columna | Descripción |
|---|---|
| Fecha | Fecha del servicio (ordenado descendente por defecto) |
| Vehículo | Vehículo al que pertenece el reemplazo |
| Historial | Orden de mantenimiento asociada |
| Repuesto | Producto reemplazado |
| Cantidad | Unidades entregadas |
| Costo Unit. / Subtotal | Visibles solo para Coordinador y Compras |
| Km desde último cambio | Vida útil del repuesto en km |
| Horas desde último cambio | Vida útil del repuesto en horas |
| Costo / km · Costo / hora | Eficiencia del repuesto |


## �🚀 Instalación

### Requisitos
- Odoo **18.0**
- Módulos dependientes: `fleet`, `maintenance`, `stock`, `purchase`, `mail`, `product`

### Pasos
1. Copiar la carpeta `predictive_maintenance_pro` en el directorio de addons
2. Actualizar la lista de módulos: *Configuración → Modo Desarrollador → Actualizar Apps*
3. Buscar **"Predictive Maintenance Pro"** e instalar

### Datos de demostración
Al instalar con demo data se crean automáticamente:
- Repuestos de ejemplo (filtros, aceite, correa de distribución)
- Planes de mantenimiento por km, horas y días
- Órdenes en distintos estados (completada, en ejecución, confirmada, borrador)

> ⚠️ Los datos demo **solo aparecen en entorno de desarrollo**, no en producción.

---

## 🧪 Tests

**6 archivos · 8 clases · ~45 casos de prueba**

| Archivo | Qué cubre |
|---|---|
| `test_maintenance_plan.py` | Creación km/hours, validaciones, `next_trigger_value` |
| `test_threshold_trigger.py` | `_should_trigger` km/hours, intervalos, cron end-to-end |
| `test_days_trigger.py` | `_should_trigger` days, `next_trigger_date`, estado upcoming 20%, `last_trigger_date` |
| `test_maintenance_order.py` | Ciclo draft→done, costos, historial al completar |
| `test_additional_coverage.py` | Picking al confirmar, métricas historial, wizard de faltantes |
| `test_security.py` | Permisos CRUD por grupo (coordinador / técnico / compras) |

### Ejecutar en Odoo.sh

```bash
# Todos los tests del módulo
python /home/odoo/src/odoo/odoo-bin -d <tu_base_de_datos> \
  --test-enable --stop-after-init -u predictive_maintenance_pro

# Una clase específica
python /home/odoo/src/odoo/odoo-bin -d <tu_base_de_datos> \
  --test-enable --stop-after-init \
  --test-tags predictive_maintenance_pro.TestPartsShortageWizard
```

---

## 🤝 Contribución

Desarrollado como prueba técnica para posición de Odoo Developer en Mastercore.
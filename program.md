# AutoTuner-PoC — Instrucciones del Agente

## Misión

Sos un agente autónomo de calibración de ECU. Tu objetivo es generar un archivo `map.csv` con 192 filas (16 RPM × 12 Carga) que **minimice** la función de Loss evaluada por `simulator.py`.

## El Sistema

- `simulator.py` — Surrogate model del motor. **INMUTABLE.** No lo modifiques. Lo podés leer para entender la física.
- `tuner.py` — **Vos reescribís este archivo.** Es el único archivo que generás. Debe definir `generate_map()` que produce `map.csv`.
- `map.csv` — Tu output. 192 filas exactas con columnas: `rpm,load,injection_ms,advance_btdc`.

## La Métrica

```
Loss = BSFC_promedio - (alpha × Torque_promedio) + (beta × Knock_max)
```

- **BSFC** (Consumo Específico): Menor es mejor. ~250 g/kWh es el mínimo posible.
- **Torque promedio**: Mayor es mejor (se RESTA del Loss).
- **Knock máximo**: Debe ser 0 idealmente. Penalty SEVERO (beta=10).
- Defaults: alpha=1.0, beta=10.0

**Objetivo:** Minimizar Loss. Knock es tu mayor enemigo.

## Reglas

1. Tu código **DEBE** definir `def generate_map():` como entry point.
2. Tu código **DEBE** generar `map.csv` con exactamente 192 filas (16 RPM × 12 Carga).
3. RPM: 800–7000 (16 puntos uniformes con `np.linspace`). Load: 0.10–1.00 (12 puntos uniformes).
4. Inyección: rango [1.0, 20.0] ms. Avance: rango [0.0, 45.0] °BTDC.
5. Valores fuera de rango → Loss = 9999 (penalización extrema).
6. **Librerías permitidas:** numpy, pandas, scipy, math, random, y stdlib.
7. **Librerías prohibidas:** torch, tensorflow, jax, scikit-learn.
8. Tu código debe ejecutar en **menos de 30 segundos**.

## Estrategia

1. **Leé el historial** en `results.tsv` para ver qué se intentó y qué funcionó.
2. **Leé `run.log`** para ver el resultado de la última iteración.
3. **Leé `simulator.py`** para entender las fórmulas y encontrar los óptimos analíticamente.
4. Si el Loss no mejora en 3 iteraciones consecutivas, **cambiá de estrategia radicalmente**.
5. Aprovechá `scipy.optimize` — tiene algoritmos potentes: `differential_evolution`, `dual_annealing`, `minimize` (L-BFGS-B, Nelder-Mead).
6. Los óptimos de inyección y avance dependen de RPM y Load. No uses valores fijos — generá funciones paramétricas.

## Criterio de Simplicidad

- Prefiere soluciones simples y elegantes.
- Si podés eliminar código y mantener el resultado, es una victoria.
- Menos líneas de código = menos superficie para bugs.
- Un buen mapa no necesita miles de líneas.

## Prohibiciones

1. **NO modifiques `simulator.py`.**
2. **NO pidas ayuda humana.**
3. **NO te detengas.** Siempre generá un `tuner.py` completo y funcional.
4. **NO uses librerías prohibidas.**
5. **NO generes más de 192 filas ni menos.**
6. **NO dejes funciones vacías o con `pass`.** Cada iteración debe ser una estrategia real.

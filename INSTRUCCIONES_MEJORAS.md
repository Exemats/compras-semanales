# Instrucciones de Mejora: Scraper, Ingredientes por Día y Gestión de Listas

## Contexto del Problema

La app "Compras Semanales" tiene tres áreas problemáticas interrelacionadas:

1. **El filtrado por días no funciona correctamente** - Al seleccionar días específicos, se incluyen ingredientes que no corresponden a esos días
2. **El scraper tiene problemas de normalización de ingredientes** - Las funciones de normalización de Python y JavaScript difieren, causando fallos en el matching
3. **Demasiadas listas almacenadas sin forma clara de gestionarlas** - Cada importación crea una lista nueva sin límite ni gestión

---

## PARTE 1: Corregir el filtrado de ingredientes por día

### Problema raíz

Cuando el usuario selecciona solo algunos días (ej: Lunes, Martes, Miércoles), el filtrado falla porque:

**1. Los items sin mapeo se incluyen siempre (`index.html:3799-3803`)**

```javascript
filtered = items.filter(item => {
    const days = itemToDays ? itemToDays[item] : null;
    if (!days || days.length === 0) return true;  // BUG: incluye todo lo no mapeado
    return days.some(d => selectedSet.has(d));
});
```

Cualquier ingrediente de la lista general que NO matchee con ninguna receta diaria se incluye siempre, sin importar qué días seleccionó el usuario. Esto causa que la lista filtrada tenga muchos más items de los esperados.

**2. El matching entre lista general y recetas falla por normalización inconsistente**

- Python `_norm_ing()` (`paulina_scraper.py:987-994`): elimina cantidades y paréntesis pero conserva todas las palabras
- JavaScript `normalizeIngredient()` (`index.html:1961-1983`): además trunca a máximo 3 palabras

Ejemplo de mismatch:
| Item original | Python `_norm_ing` | JS `normalizeIngredient` |
|---|---|---|
| "1 kg de puré de tomate" | "de puré de tomate" | "pure tomate" |
| "sal y pimienta a gusto" | "sal y pimienta" | "sal pimienta" |

El mapeo `item_to_days` del scraper usa las claves exactas del texto original del item de la lista general. Si el scraper genera `item_to_days` correctamente, funciona. Pero cuando falla y el cliente usa `buildItemToDays()` como fallback, la normalización JS trunca a 3 palabras, lo cual produce matches incorrectos o faltantes.

**3. El scraper solo busca recetas de lunes a viernes (`paulina_scraper.py:623`)**

```python
dias_buscar = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes']
```

Sábado y domingo no se extraen nunca. Si el menú tiene recetas para esos días, los ingredientes del fin de semana quedan sin mapear.

### Cambios necesarios

#### A. En el scraper (`paulina_scraper.py`)

1. **Agregar sábado y domingo** a `dias_buscar` en `_extraer_recetas_por_dia()` (línea 623):
   ```python
   dias_buscar = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
   ```

2. **Mejorar `_norm_ing()`** (línea 987) para que sea coherente con el JS:
   - Eliminar la preposición "de" al inicio después de quitar cantidades
   - Eliminar acentos para matching consistente
   - Limitar a 3 palabras significativas (como hace el JS)

   ```python
   def _norm_ing(text):
       import unicodedata
       n = text.lower().strip()
       # Eliminar cantidades y unidades
       n = re.sub(r'^[\d\s\/½¼¾,.x×]+\s*(?:g|gr|kg|ml|l|lt|lts|litros?|cdas?|cucharadas?|tazas?|unidad(?:es)?|paquetes?|latas?|sobres?)?\s*', '', n, flags=re.I)
       # Eliminar paréntesis
       n = re.sub(r'\([^)]*\)', '', n).strip()
       # Eliminar "c/n", "a gusto", etc.
       n = re.sub(r'\s*(c/n|a gusto|cantidad necesaria|opcional)\s*$', '', n, flags=re.I).strip()
       # Eliminar acentos
       n = unicodedata.normalize('NFD', n)
       n = re.sub(r'[\u0300-\u036f]', '', n)
       # Eliminar preposición "de" al inicio
       n = re.sub(r'^de\s+', '', n)
       # Solo caracteres alfanuméricos y espacios
       n = re.sub(r'[^a-z\s]', ' ', n)
       n = re.sub(r'\s+', ' ', n).strip()
       # Limitar a 3 palabras significativas (> 1 caracter)
       words = [w for w in n.split() if len(w) > 1]
       return ' '.join(words[:3])
   ```

3. **Validar formato de ingredientes extraídos** en `_extraer_recetas_por_dia()` (línea 671):
   ```python
   # Después de extraer el texto, validar que parece un ingrediente real
   if ing and len(ing) > 1 and len(ing) < 200:
       # Verificar que no sea un título, instrucción o HTML residual
       if not re.match(r'^(paso|step|instruc|prepar|cocin|herv|serv)', ing.lower()):
           ingredientes.append(ing)
   ```

#### B. En el cliente (`index.html`)

4. **Cambiar la lógica de filtrado** en `filterSourceList()` (línea 3799-3803). Los items sin mapeo NO deben incluirse cuando se seleccionan días parciales:

   ```javascript
   filtered = items.filter(item => {
       const days = itemToDays ? itemToDays[item] : null;
       if (!days || days.length === 0) {
           // Item no mapeado a ningún día: incluir solo si está en categorías
           // que son siempre necesarias (condimentos, básicos)
           const categoriasBase = ['Ya tenés en casa ✅', 'Comodín 👑'];
           return categoriasBase.includes(cat);
       }
       return days.some(d => selectedSet.has(d));
   });
   ```

   Alternativa más conservadora: mostrar al usuario los items no mapeados y dejarlo decidir:
   ```javascript
   // Agregar sección "Items sin día asignado" en el preview de importación
   // para que el usuario decida si incluirlos o no
   ```

5. **Unificar la función de normalización JS** (`normalizeIngredient`, línea 1961) con la del scraper. La función JS también debe:
   - Eliminar "de" al inicio después de quitar cantidades (para coherencia con Python)
   ```javascript
   // Después de eliminar cantidades (línea 1969), agregar:
   normalized = normalized.replace(/^de\s+/i, '');
   ```

6. **Agregar log de diagnóstico** en `buildItemToDays()` (línea 3643) para facilitar debugging:
   ```javascript
   // Al final de buildItemToDays, antes del return:
   const unmapped = [];
   for (const [cat, items] of Object.entries(sourceList)) {
       for (const item of items) {
           if (!itemToDays[item]) unmapped.push(item);
       }
   }
   if (unmapped.length > 0) {
       console.warn(`[buildItemToDays] ${unmapped.length} items sin mapear:`, unmapped);
   }
   ```

---

## PARTE 2: Mejorar la gestión y creación de listas

### Problema actual

- Cada importación crea una nueva `week` sin límite
- No hay forma fácil de ver cuántas listas hay ni gestionarlas en conjunto
- No hay auto-limpieza de listas viejas o completadas
- El dropdown de semanas se vuelve difícil de usar con muchas listas
- Al importar la misma semana varias veces (por cambiar días), se crean duplicados

### Cambios necesarios

#### A. Reemplazar en vez de duplicar (prioridad alta)

7. **Detectar y ofrecer reemplazar listas existentes** al importar. Actualmente `findSimilarWeeks()` (línea 4036) solo muestra un warning. Debe ofrecer reemplazar:

   ```javascript
   // En executeImport(), después de encontrar semanas similares:
   if (similarWeeks.length > 0) {
       const weekNames = similarWeeks.map(w => w.name).join(', ');
       const action = confirm(
           `Ya existe una lista similar: ${weekNames}\n\n` +
           `¿Querés reemplazarla? (Aceptar = reemplazar, Cancelar = crear nueva)`
       );
       if (action) {
           // Eliminar las semanas similares antes de crear la nueva
           for (const sw of similarWeeks) {
               await deleteWeekFromCloud(sw.id);
               delete weeks[sw.id];
           }
       }
   }
   ```

#### B. Límite y auto-limpieza de listas (prioridad alta)

8. **Implementar límite máximo de listas** (ej: 8 semanas). Al superar el límite, preguntar al usuario qué lista eliminar o auto-eliminar la más antigua completada:

   ```javascript
   const MAX_WEEKS = 8;

   async function enforceWeekLimit() {
       const weekIds = Object.keys(weeks);
       if (weekIds.length <= MAX_WEEKS) return;

       // Buscar semanas completamente compradas (100% tachado)
       const completedWeeks = weekIds
           .filter(id => {
               const items = weeks[id].items || {};
               const total = Object.keys(items).length;
               if (total === 0) return true; // vacía
               const bought = Object.values(items).filter(i => i.bought).length;
               return bought === total;
           })
           .sort((a, b) => (weeks[a].createdAt || 0) - (weeks[b].createdAt || 0));

       if (completedWeeks.length > 0) {
           // Auto-eliminar la más antigua completada
           const oldestCompleted = completedWeeks[0];
           const name = weeks[oldestCompleted].name;
           await deleteWeekFromCloud(oldestCompleted);
           delete weeks[oldestCompleted];
           showToast(`Lista completada "${name}" eliminada automáticamente`, 'info');
       }
   }
   ```

   Llamar a `enforceWeekLimit()` al final de `createWeekFromImport()`.

#### C. Mejorar la UI de gestión de listas (prioridad media)

9. **Agregar una vista de "Gestión de Listas"** accesible desde un botón en el header. Esta vista debe mostrar:
   - Todas las listas en cards (no solo un dropdown)
   - Para cada lista: nombre, fecha, progreso (X/Y comprados), estado
   - Botón de eliminar individual
   - Botón de "Limpiar completadas" (eliminar todas las listas 100% compradas)
   - Indicador visual del estado: activa, completada, vieja

   ```html
   <!-- Modal de gestión de listas -->
   <div id="weeksManagerModal" class="modal">
       <div class="modal-content">
           <h3>Mis Listas</h3>
           <div id="weeksManagerList">
               <!-- Cards dinámicas -->
           </div>
           <button onclick="deleteCompletedWeeks()">Limpiar completadas</button>
           <button onclick="closeWeeksManager()">Cerrar</button>
       </div>
   </div>
   ```

10. **Mejorar el dropdown existente** con indicadores de estado:
    ```javascript
    function renderWeeksDropdown() {
        // ...
        const itemCount = Object.keys(week.items || {}).length;
        const boughtCount = Object.values(week.items || {}).filter(i => i.bought).length;
        const progress = itemCount > 0 ? Math.round((boughtCount / itemCount) * 100) : 0;

        let statusIcon = '';
        if (progress === 100) statusIcon = ' ✅';
        else if (progress > 50) statusIcon = ' 🔄';

        displayName += ` [${boughtCount}/${itemCount}]${statusIcon}`;
        // ...
    }
    ```

#### D. Mejorar el flujo de importación (prioridad media)

11. **Preview antes de importar**: Mostrar un resumen final antes de confirmar la importación:
    ```
    ┌─────────────────────────────┐
    │ Resumen de importación      │
    │                             │
    │ Menú: Semana 5              │
    │ Días: Lu, Ma, Mi            │
    │ Items general: 23           │
    │ Items veggie: 19            │
    │ Lista existente: Semana 5   │
    │   → Se reemplazará          │
    │                             │
    │ [Cancelar]    [Importar]    │
    └─────────────────────────────┘
    ```

12. **No duplicar veggie = general**. Si no hay lista veggie separada, no crear una copia (`index.html:3890-3894`). En su lugar, mostrar un mensaje en la tab veggie indicando que no hay lista diferenciada:
    ```javascript
    // En vez de: importWrapper.veggie = importWrapper.general;
    // Simplemente no crear la lista veggie:
    // importWrapper.veggie queda undefined
    // Y en la UI, si no hay items veggie, mostrar:
    // "Esta semana no tiene lista veggie diferenciada"
    ```

---

## PARTE 3: Mejoras adicionales al scraper

### Calidad de extracción

13. **Mejorar la extracción de ingredientes** en `_extraer_recetas_por_dia()`:
    - Agregar estrategia 3: buscar listas (`<ul>/<ol>`) dentro de la sección del día
    - Filtrar textos que son claramente instrucciones y no ingredientes
    - Deduplicar ingredientes dentro de cada día

    ```python
    # Estrategia 3: buscar listas ul/ol si no hay labels ni li sueltos
    if not ingredientes:
        for ul in section.find_all(['ul', 'ol']):
            for li in ul.find_all('li', recursive=False):
                texto = li.get_text(strip=True)
                texto = re.sub(r'^[\[\]✓\s•·\-]+', '', texto).strip()
                if texto and len(texto) > 1 and len(texto) < 200:
                    ingredientes.append(texto)

    # Deduplicar ingredientes del día
    seen = set()
    ingredientes_unicos = []
    for ing in ingredientes:
        norm = _norm_ing(ing)
        if norm and norm not in seen:
            seen.add(norm)
            ingredientes_unicos.append(ing)
    ingredientes = ingredientes_unicos
    ```

14. **No silenciar errores** en el descubrimiento de menús (línea 297):
    ```python
    except Exception as e:
        logger.warning(f"Error verificando semana {semana}: {e}")
        continue
    ```

### Robustez del mapeo

15. **Matching fuzzy para `item_to_days`**: Si un ingrediente de receta no matchea exactamente con la lista general, intentar matching parcial:

    ```python
    def _fuzzy_match(norm_ing, norm_to_items):
        """Busca match parcial si no hay match exacto."""
        if norm_ing in norm_to_items:
            return norm_to_items[norm_ing]

        # Buscar si el ingrediente normalizado está contenido en alguna key
        for key, items in norm_to_items.items():
            if norm_ing in key or key in norm_ing:
                return items

        # Buscar por palabras compartidas (al menos 2)
        ing_words = set(norm_ing.split())
        for key, items in norm_to_items.items():
            key_words = set(key.split())
            common = ing_words & key_words
            if len(common) >= 2:
                return items

        return None
    ```

---

## Orden de implementación sugerido

| Paso | Cambio | Archivo | Impacto |
|------|--------|---------|---------|
| 1 | Unificar normalización Python/JS | ambos | Corrige matching roto |
| 2 | Agregar sábado/domingo al scraper | scraper | Completa los datos |
| 3 | Corregir filtrado items sin mapeo | index.html | Fix principal de días |
| 4 | Reemplazar en vez de duplicar listas | index.html | Reduce listas |
| 5 | Auto-limpieza de listas completadas | index.html | Reduce listas |
| 6 | Vista de gestión de listas | index.html | Mejor UX |
| 7 | Preview de importación | index.html | Menos errores |
| 8 | No duplicar veggie=general | index.html | Menos confusión |
| 9 | Matching fuzzy en scraper | scraper | Mejor cobertura |
| 10 | Mejoras extracción ingredientes | scraper | Mejor calidad |

---

## Testing

Para verificar los cambios:

1. **Test de normalización**: Verificar que `_norm_ing("1 kg de puré de tomate")` en Python da el mismo resultado que `normalizeIngredient("1 kg de puré de tomate")` en JS
2. **Test de filtrado por días**: Importar un menú, seleccionar solo Lunes. Verificar que solo se incluyan ingredientes del Lunes + items de categorías base
3. **Test de reemplazo**: Importar la misma semana dos veces. La segunda vez debe ofrecer reemplazar
4. **Test de límite**: Crear 9+ listas y verificar que se ofrece limpieza automática
5. **Test de fin de semana**: Verificar que recetas de sábado/domingo se extraen correctamente

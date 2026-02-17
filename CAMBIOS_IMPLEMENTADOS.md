# Cambios Implementados - Mejoras Planeadas

Este documento resume todos los cambios implementados según las instrucciones en `INSTRUCCIONES_MEJORAS.md`.

## ✅ Parte 1: Filtrado de ingredientes por día corregido

### 1.1 Agregar sábado y domingo al scraper
**Archivo:** `paulina_scraper.py` (línea 627)
```python
dias_buscar = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
```
- El scraper ahora extrae recetas de todos los días de la semana, incluyendo fin de semana
- Esto soluciona el problema de ingredientes del fin de semana quedando sin mapear

### 1.2 Unificar función de normalización
**Archivos:** `paulina_scraper.py` (línea 1016-1040) y `index.html` (línea 1960-1983)

Ambas funciones ahora:
- Eliminan cantidades y unidades
- Eliminan palabras comunes de cantidad ("un", "una", "medio", etc.)
- Eliminan paréntesis y contenido
- Eliminan "c/n", "a gusto", etc.
- Eliminan acentos (NFD + regex)
- Eliminan preposición "de" al inicio
- Mantienen solo caracteres alfanuméricos
- Limitan a 3 palabras significativas (> 1 carácter)

**Resultado:** "1 kg de puré de tomate" → "pure de tomate" (en ambos lenguajes)

### 1.3 Corregir lógica de filtrado
**Archivo:** `index.html` (línea 3882-3890)
```javascript
if (!days || days.length === 0) {
    // Item no mapeado: incluir solo si está en categorías base
    return BASE_CATEGORIES.includes(cat);
}
```
- Items sin mapeo ya NO se incluyen automáticamente
- Solo se incluyen si están en categorías base: "Ya tenés en casa ✅", "Comodín 👑"
- Esto soluciona el problema principal de listas filtradas con demasiados items

### 1.4 Validación de ingredientes extraídos
**Archivo:** `paulina_scraper.py` (línea 676-679, 686-688, 696-698)
- Validación de longitud (1-200 caracteres)
- Filtrado de títulos e instrucciones (regex: `^(paso|step|instruc|prepar|cocin|herv|serv)`)
- Mejora la calidad de los ingredientes extraídos

### 1.5 Log de diagnóstico
**Archivo:** `index.html` (línea 3685-3694)
```javascript
if (unmapped.length > 0) {
    console.warn(`[buildItemToDays] ${unmapped.length} items sin mapear:`, unmapped);
}
```
- Facilita debugging al mostrar qué items no matchearon con recetas

## ✅ Parte 2: Gestión de listas mejorada

### 2.1 Detectar y ofrecer reemplazar listas duplicadas
**Archivo:** `index.html` (línea 4047-4062)
```javascript
if (similarWeeks.length > 0) {
    const shouldReplace = confirm(
        `Ya existe una lista similar: ${weekNames}\n\n` +
        `¿Querés reemplazarla? (Aceptar = reemplazar, Cancelar = crear nueva)`
    );
    if (shouldReplace) {
        // Eliminar las semanas similares antes de crear la nueva
        for (const sw of similarWeeks) {
            await deleteWeekFromCloud(sw.id);
            delete weeks[sw.id];
        }
    }
}
```
- Al importar, detecta si ya existe una lista de la misma semana
- Ofrece al usuario reemplazarla o crear una nueva
- Evita acumulación de listas duplicadas

### 2.2 Límite máximo de listas con auto-limpieza
**Archivo:** `index.html` (línea 1892, 2834-2863)
```javascript
const MAX_WEEKS = 8; // Constante global

async function enforceWeekLimit() {
    // Busca listas completadas (100% compradas) y elimina la más antigua
    // Si no hay completadas, avisa al usuario
}
```
- Se llama automáticamente después de cada importación
- Mantiene máximo 8 listas
- Prioriza eliminar listas completadas más antiguas
- Si no hay completadas, solo avisa al usuario

### 2.3 Indicadores de progreso en dropdown
**Archivo:** `index.html` (línea 2921-2933)
```javascript
const progress = itemCount > 0 ? Math.round((boughtCount / itemCount) * 100) : 0;
let statusIcon = '';
if (itemCount === 0) statusIcon = ' [vacía]';
else if (progress === 100) statusIcon = ' ✅';
else if (progress > 50) statusIcon = ' 🔄';
displayName += ` [${boughtCount}/${itemCount}]${statusIcon}`;
```
- Muestra progreso: `Semana 5 [15/30] 🔄 (13-19 Feb)`
- Emojis: ✅ completada, 🔄 en progreso, [vacía]
- Facilita identificar el estado de cada lista

### 2.4 No duplicar lista veggie cuando es igual a general
**Archivo:** `index.html` (línea 3954-3958)
```javascript
if (hasSeparateVeggie) {
    importWrapper.veggie = filterSourceList(data.veggie, veggieItemToDays);
}
// Si no hay veggie diferenciada, no creamos una copia duplicada
```
- Ya no se crea una copia de la lista general como veggie
- Reduce confusión y duplicación de datos

### 2.5 Mensaje cuando no hay lista veggie diferenciada
**Archivo:** `index.html` (línea 2265-2278)
```javascript
if (currentList === 'veggie') {
    const hasAnyVeggie = Object.values(items).some(item => item.listType === 'veggie');
    if (!hasAnyVeggie) {
        html = '<div class="empty-message">Esta semana no tiene lista veggie diferenciada.<br>Usá la lista General 🍖</div>';
    }
}
```
- Muestra mensaje claro al usuario cuando no hay lista veggie
- Mejor experiencia de usuario

## ✅ Parte 3: Mejoras al scraper

### 3.1 Estrategia adicional de extracción (ul/ol)
**Archivo:** `paulina_scraper.py` (línea 690-698)
```python
# Estrategia 3: buscar listas ul/ol si no hay labels ni li sueltos
if not ingredientes:
    for ul in section.find_all(['ul', 'ol']):
        for li in ul.find_all('li', recursive=False):
            # Extraer y validar
```
- Añade un tercer método de extracción para casos donde no hay labels
- Mejora la cobertura de ingredientes extraídos

### 3.2 Deduplicación de ingredientes por día
**Archivo:** `paulina_scraper.py` (línea 700-708)
```python
# Deduplicar ingredientes del día
seen = set()
ingredientes_unicos = []
for ing in ingredientes:
    norm = ing.lower().strip()
    if norm and norm not in seen:
        seen.add(norm)
        ingredientes_unicos.append(ing)
```
- Elimina ingredientes duplicados dentro del mismo día
- Mejora la calidad de los datos extraídos

### 3.3 Matching fuzzy para item_to_days
**Archivo:** `paulina_scraper.py` (línea 1062-1082)
```python
def _fuzzy_match(norm_ing):
    """Busca match parcial si no hay match exacto."""
    # 1. Match exacto
    if norm_ing in norm_to_items:
        return norm_to_items[norm_ing]
    
    # 2. Matching de contención (substring)
    for key, items in norm_to_items.items():
        if norm_ing in key or key in norm_ing:
            return items
    
    # 3. Matching por palabras compartidas (al menos 2)
    ing_words = set(norm_ing.split())
    if len(ing_words) >= 2:
        for key, items in norm_to_items.items():
            key_words = set(key.split())
            common = ing_words & key_words
            if len(common) >= 2:
                return items
```
- Mejora significativamente el mapeo entre ingredientes de recetas y lista general
- Reduce items sin mapear
- Log de estadísticas: exactos, fuzzy, sin mapear

## 📊 Calidad de código

### Constantes extraídas

**paulina_scraper.py:**
```python
MAX_INGREDIENT_LENGTH = 200
INSTRUCTION_PATTERN = re.compile(r'^(paso|step|instruc|prepar|cocin|herv|serv)', re.I)
MAX_NORMALIZED_WORDS = 3
```

**index.html:**
```javascript
const MAX_WEEKS = 8;
const BASE_CATEGORIES = ['Ya tenés en casa ✅', 'Comodín 👑'];
```

### Beneficios:
- Elimina "magic numbers"
- Facilita mantenimiento
- Mejora legibilidad
- Evita duplicación

## 🔍 Testing sugerido

### Tests automatizados
1. **Normalización unificada:**
   - ✅ Verificado: Python y JS producen el mismo output
   - Casos de prueba: "1 kg de puré de tomate" → "pure de tomate"

### Tests manuales necesarios

1. **Filtrado por días:**
   - Importar un menú con recetas de varios días
   - Seleccionar solo Lunes y Martes
   - Verificar que solo se incluyen ingredientes de esos días + categorías base

2. **Extracción de fin de semana:**
   - Ejecutar scraper en un menú con recetas de sábado/domingo
   - Verificar que se extraen correctamente

3. **Reemplazo de listas duplicadas:**
   - Importar una semana (ej: Semana 5)
   - Importar la misma semana nuevamente
   - Verificar que ofrece reemplazar la existente

4. **Límite de listas:**
   - Crear 9 listas
   - Verificar que se ofrece auto-limpieza
   - Marcar una lista como completada (100% comprada)
   - Crear la décima lista
   - Verificar que se elimina automáticamente la completada

5. **Indicadores de progreso:**
   - Ver el dropdown de listas
   - Verificar que muestra [X/Y] y emojis correctos

6. **Lista veggie:**
   - Importar un menú sin lista veggie diferenciada
   - Cambiar a la vista Vegetariana
   - Verificar que muestra mensaje informativo

7. **Matching fuzzy:**
   - Revisar logs del scraper después de ejecutarlo
   - Verificar estadísticas de matching (exactos/fuzzy/sin mapear)

## 📝 Notas de implementación

### Items pendientes (prioridad media, no críticos)
- **Vista de gestión de listas (modal):** Sería útil pero no crítico. El dropdown con indicadores de progreso ya mejora mucho la UX.
- **Preview antes de importar:** Buena idea para el futuro, pero la funcionalidad actual ya evita duplicados con el prompt de reemplazo.

### Compatibilidad
- Todos los cambios son retrocompatibles
- No se requieren migraciones de datos
- Firebase estructura permanece igual

### Seguridad
- ✅ CodeQL: 0 alertas
- No se introducen nuevas vulnerabilidades
- No hay cambios en autenticación o permisos

## 🎯 Impacto

### Problemas solucionados:
1. ✅ Filtrado por días ahora funciona correctamente
2. ✅ Normalización consistente entre Python y JavaScript
3. ✅ Soporte para recetas de fin de semana
4. ✅ Gestión de listas mejorada (menos duplicados, auto-limpieza)
5. ✅ Mejor visibilidad del estado de las listas
6. ✅ Extracción de ingredientes más robusta
7. ✅ Mejor matching entre recetas y lista general

### Mejoras de UX:
- Listas filtradas más precisas
- Menos confusión con listas duplicadas
- Indicadores visuales de progreso
- Mensajes informativos claros
- Auto-limpieza transparente

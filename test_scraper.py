#!/usr/bin/env python3
"""
Tests para paulina_scraper.py

Cubre:
  - Normalización de ingredientes (_norm_ing)
  - Detección de categorías (_detectar_categoria)
  - Filtrado de URLs en MenuDiscoverer
  - Extracción de fechas (_extraer_fechas)
  - Extracción de recetas por día (_extraer_recetas_por_dia)
  - Extracción de listas de compras (_extraer_lista)
  - Construcción de item_to_days (generar_json)
  - Detección de semana actual (lógica de selección)

Los tests usan HTML mockeado para no depender de red.
"""

import re
import sys
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse, urljoin

# ---------------------------------------------------------------------------
# Helpers para instanciar el extractor sin red
# ---------------------------------------------------------------------------

def make_extractor(html: str, semana: int = 1):
    """Crea un PaulinaExtractor ya inicializado con HTML mockeado."""
    from paulina_scraper import PaulinaExtractor
    from bs4 import BeautifulSoup

    ext = PaulinaExtractor(semana=semana)
    ext.html_content = html
    ext.soup = BeautifulSoup(html, 'html.parser')
    ext.titulo = "Menú Semana Test"
    ext.fechas = ""
    ext._detectar_tipo_menu()
    return ext


# ---------------------------------------------------------------------------
# Función _norm_ing (definida inline dentro de generar_json)
# La extraemos aquí para poder testearla directamente.
# ---------------------------------------------------------------------------

import unicodedata

def _norm_ing(text: str, max_words: int = 3) -> str:
    """Normalización de ingrediente (replica exacta del código del scraper)."""
    n = text.lower().strip()
    n = re.sub(r'^[\d\s\/½¼¾,.x×]+\s*(?:g|gr|kg|ml|l|lt|lts|litros?|cdas?|cucharadas?|tazas?|unidad(?:es)?|paquetes?|latas?|sobres?)?\s*', '', n, flags=re.I)
    n = re.sub(r'^(un|una|uno|dos|tres|cuatro|cinco|medio|media|pizca|chorro|poco|mucho)\s+', '', n, flags=re.I)
    n = re.sub(r'\([^)]*\)', '', n).strip()
    n = re.sub(r'\s*(c/n|a gusto|cantidad necesaria|opcional)\s*$', '', n, flags=re.I).strip()
    n = unicodedata.normalize('NFD', n)
    n = re.sub(r'[\u0300-\u036f]', '', n)
    n = re.sub(r'^de\s+', '', n)
    n = re.sub(r'[^a-z\s]', ' ', n)
    n = re.sub(r'\s+', ' ', n).strip()
    words = [w for w in n.split() if len(w) > 1]
    return ' '.join(words[:max_words])


# ===========================================================================
# Test Suite: Normalización de ingredientes
# ===========================================================================

class TestNormIng(unittest.TestCase):

    def test_strip_quantity_grams(self):
        self.assertEqual(_norm_ing("200 g arroz"), "arroz")

    def test_strip_quantity_kg(self):
        self.assertEqual(_norm_ing("1 kg papa"), "papa")

    def test_strip_quantity_ml(self):
        self.assertEqual(_norm_ing("500 ml leche entera"), "leche entera")

    def test_strip_number_word(self):
        self.assertEqual(_norm_ing("dos huevos"), "huevos")

    def test_strip_accents(self):
        self.assertEqual(_norm_ing("ají picante"), "aji picante")

    def test_strip_parentheses(self):
        self.assertEqual(_norm_ing("cebolla (grande)"), "cebolla")

    def test_strip_a_gusto(self):
        self.assertEqual(_norm_ing("sal a gusto"), "sal")

    def test_strip_cn(self):
        self.assertEqual(_norm_ing("pimienta c/n"), "pimienta")

    def test_strip_opcional(self):
        self.assertEqual(_norm_ing("queso rallado opcional"), "queso rallado")

    def test_max_words(self):
        result = _norm_ing("aceite de oliva extra virgen")
        self.assertLessEqual(len(result.split()), 3)

    def test_empty_string(self):
        self.assertEqual(_norm_ing(""), "")

    def test_only_number(self):
        # "3" → stripped, nothing left
        self.assertEqual(_norm_ing("3"), "")

    def test_fraction_quantity(self):
        self.assertEqual(_norm_ing("½ taza harina"), "harina")

    def test_strip_de_prefix(self):
        # "de" at start should be removed
        result = _norm_ing("de tomate")
        self.assertNotIn("de", result.split())

    def test_mixed_case(self):
        self.assertEqual(_norm_ing("Tomate Fresco"), "tomate fresco")

    def test_cucharada(self):
        self.assertEqual(_norm_ing("2 cdas azúcar"), "azucar")


# ===========================================================================
# Test Suite: Detección de categorías
# ===========================================================================

class TestDetectarCategoria(unittest.TestCase):

    def setUp(self):
        from paulina_scraper import PaulinaExtractor
        self.ext = PaulinaExtractor(semana=1)

    def test_supermercado(self):
        nombre, orden = self.ext._detectar_categoria("Supermercado 🏪")
        self.assertEqual(nombre, "Supermercado 🏪")
        self.assertEqual(orden, 1)

    def test_carnes(self):
        nombre, orden = self.ext._detectar_categoria("Carnes 🥩")
        self.assertEqual(nombre, "Carnes 🥩")
        self.assertEqual(orden, 2)

    def test_verduleria_accent(self):
        nombre, orden = self.ext._detectar_categoria("Verdulería 🥬")
        self.assertEqual(nombre, "Verdulería 🥬")
        self.assertEqual(orden, 4)

    def test_verduleria_no_accent(self):
        nombre, orden = self.ext._detectar_categoria("verduleria")
        self.assertEqual(nombre, "Verdulería 🥬")

    def test_dietetica(self):
        nombre, orden = self.ext._detectar_categoria("dietética")
        self.assertEqual(nombre, "Dietética 🥗")

    def test_yapa(self):
        nombre, orden = self.ext._detectar_categoria("Yapa ⭐")
        self.assertEqual(nombre, "Yapa ⭐")

    def test_comodin(self):
        nombre, orden = self.ext._detectar_categoria("comodín")
        self.assertEqual(nombre, "Comodín 👑")

    def test_casa(self):
        nombre, orden = self.ext._detectar_categoria("Ya tenés en casa")
        self.assertEqual(nombre, "Ya tenés en casa ✅")

    def test_unknown(self):
        nombre, orden = self.ext._detectar_categoria("Ingrediente raro xyz")
        self.assertEqual(nombre, "Otros 📦")
        self.assertEqual(orden, 99)


# ===========================================================================
# Test Suite: Filtrado de URLs en MenuDiscoverer
# ===========================================================================

class TestMenuDiscovererURLFilter(unittest.TestCase):
    """
    Verifica que el filtro de URLs incluye menús válidos y excluye la landing page.
    """

    LANDING = "https://almacen.paulinacocina.net/menu-semanal/"

    def _should_match(self, href: str) -> bool:
        """Replica la lógica de filtrado de MenuDiscoverer.descubrir_menus."""
        return bool(
            re.search(r'/menu-semana-\d+', href, re.I) or
            re.search(r'/menu/[^/]', href, re.I) or
            re.search(r'/menu-especial', href, re.I) or
            re.search(r'/menu-[a-z]+-\d{4}', href, re.I)
        )

    def _is_landing(self, href: str) -> bool:
        """Verifica si la URL es la landing page (debe excluirse)."""
        full_url = urljoin(self.LANDING, href)
        parsed = urlparse(full_url)
        clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}/"
        landing_parsed = urlparse(self.LANDING)
        landing_clean = f"{landing_parsed.scheme}://{landing_parsed.netloc}{landing_parsed.path.rstrip('/')}/"
        return clean == landing_clean

    def test_weekly_menu_matched(self):
        self.assertTrue(self._should_match("/menu-semana-5/"))

    def test_weekly_menu_no_trailing_slash(self):
        self.assertTrue(self._should_match("/menu-semana-12"))

    def test_especial_menu_matched(self):
        self.assertTrue(self._should_match("/menu-especial-navidad/"))

    def test_menu_subdirectory_matched(self):
        self.assertTrue(self._should_match("/menu/semana-verano/"))

    def test_landing_page_NOT_matched_by_filter(self):
        # /menu-semanal/ should NOT match because it doesn't have -\d+ after semana
        self.assertFalse(self._should_match("/menu-semanal/"))

    def test_landing_page_full_url_excluded(self):
        # Even if somehow it passed the filter, the landing check should catch it
        self.assertTrue(self._is_landing(self.LANDING))
        self.assertTrue(self._is_landing("/menu-semanal/"))

    def test_weekly_menu_is_not_landing(self):
        self.assertFalse(self._is_landing("/menu-semana-5/"))

    def test_semana_number_extracted(self):
        href = "/menu-semana-7/"
        titulo = "Semana 7"
        combined = href + " " + titulo
        match = re.search(r'semana[- ]?(\d+)', combined, re.I)
        self.assertIsNotNone(match)
        self.assertEqual(int(match.group(1)), 7)

    def test_semana_number_from_title_when_not_in_url(self):
        href = "/menu-especial-verano/"
        titulo = "Menú especial semana 3"
        combined = href + " " + titulo
        match = re.search(r'semana[- ]?(\d+)', combined, re.I)
        self.assertIsNotNone(match)
        self.assertEqual(int(match.group(1)), 3)


# ===========================================================================
# Test Suite: Extracción de fechas
# ===========================================================================

class TestExtraerFechas(unittest.TestCase):

    def _make_extractor_from_heading(self, heading_text: str):
        html = f"<html><body><h2>{heading_text}</h2></body></html>"
        ext = make_extractor(html)
        ext._extraer_fechas()
        return ext

    def test_standard_format(self):
        ext = self._make_extractor_from_heading("Menú semana del 9 al 13 de febrero")
        self.assertIn("9", ext.fechas)
        self.assertIn("13", ext.fechas)
        self.assertIn("febrero", ext.fechas)

    def test_del_prefix(self):
        ext = self._make_extractor_from_heading("del 17 al 21 de marzo")
        self.assertIn("17", ext.fechas)
        self.assertIn("21", ext.fechas)
        self.assertIn("marzo", ext.fechas)

    def test_no_de_before_month(self):
        # "2 al 6 febrero" (sin "de")
        ext = self._make_extractor_from_heading("2 al 6 febrero")
        self.assertIn("2", ext.fechas)
        self.assertIn("6", ext.fechas)
        self.assertIn("febrero", ext.fechas)

    def test_no_date_in_heading(self):
        ext = self._make_extractor_from_heading("Bienvenidos al menú semanal")
        self.assertEqual(ext.fechas, "")

    def test_date_with_year(self):
        # "9 al 13 de febrero de 2026" — the scraper regex should capture "febrero" as month
        ext = self._make_extractor_from_heading("9 al 13 de febrero de 2026")
        # Should extract something meaningful
        self.assertIn("febrero", ext.fechas)

    def test_h1_heading(self):
        html = "<html><body><h1>Semana del 24 al 28 de abril</h1></body></html>"
        from paulina_scraper import PaulinaExtractor
        from bs4 import BeautifulSoup
        ext = PaulinaExtractor(semana=1)
        ext.soup = BeautifulSoup(html, 'html.parser')
        ext.fechas = ""
        ext._extraer_fechas()
        self.assertIn("24", ext.fechas)
        self.assertIn("28", ext.fechas)
        self.assertIn("abril", ext.fechas)


# ===========================================================================
# Test Suite: Extracción de listas de compras (_extraer_lista)
# ===========================================================================

SAMPLE_HTML_LISTA = """
<html><body>
  <div id="lista_compra_g">
    <div class="e-con-inner">
      <strong>Supermercado</strong>
      <label>arroz blanco</label>
      <label>fideos</label>
      <strong>Verdulería</strong>
      <label>tomate</label>
      <label>cebolla</label>
      <strong>Carnes</strong>
      <label>pollo entero</label>
    </div>
  </div>
  <div id="lista_compra_v">
    <div class="e-con-inner">
      <strong>Supermercado</strong>
      <label>arroz blanco</label>
      <label>lentejas</label>
      <strong>Verdulería</strong>
      <label>tomate</label>
    </div>
  </div>
</body></html>
"""


class TestExtraerLista(unittest.TestCase):

    def setUp(self):
        self.ext = make_extractor(SAMPLE_HTML_LISTA)

    def test_extraer_lista_general(self):
        resultado = self.ext._extraer_lista('lista_compra_g')
        self.assertIn('Supermercado 🏪', resultado)
        self.assertIn('arroz blanco', resultado['Supermercado 🏪']['items'])
        self.assertIn('fideos', resultado['Supermercado 🏪']['items'])

    def test_extraer_lista_general_carnes(self):
        resultado = self.ext._extraer_lista('lista_compra_g')
        self.assertIn('Carnes 🥩', resultado)
        self.assertIn('pollo entero', resultado['Carnes 🥩']['items'])

    def test_extraer_lista_general_verduleria(self):
        resultado = self.ext._extraer_lista('lista_compra_g')
        self.assertIn('Verdulería 🥬', resultado)
        self.assertIn('tomate', resultado['Verdulería 🥬']['items'])

    def test_extraer_lista_veggie(self):
        resultado = self.ext._extraer_lista('lista_compra_v')
        self.assertIn('Supermercado 🏪', resultado)
        self.assertIn('lentejas', resultado['Supermercado 🏪']['items'])

    def test_veggie_list_empty_when_container_missing(self):
        """_extraer_lista('lista_compra_v') debe retornar {} si el contenedor no existe.
        El código tiene un guard específico para 'lista_compra_v' que evita el fallback."""
        html_sin_veggie = """
        <html><body>
          <div id="lista_compra_g">
            <div class="e-con-inner">
              <strong>Supermercado</strong>
              <label>arroz</label>
            </div>
          </div>
        </body></html>
        """
        ext = make_extractor(html_sin_veggie)
        # 'lista_compra_v' no existe → debe retornar {}
        resultado = ext._extraer_lista('lista_compra_v')
        self.assertEqual(resultado, {})

    def test_no_duplicates_in_category(self):
        resultado = self.ext._extraer_lista('lista_compra_g')
        for cat, data in resultado.items():
            items = data['items']
            self.assertEqual(len(items), len(set(items)), f"Duplicados en {cat}")


# ===========================================================================
# Test Suite: Extracción de recetas por día
# ===========================================================================

SAMPLE_HTML_RECETAS = """
<html><body>
  <div>
    <h3>Lunes</h3>
    <div>
      <h4>Pollo al limón</h4>
      <label>pollo</label>
      <label>limón</label>
      <label>ajo</label>
    </div>
  </div>
  <div>
    <h3>Martes</h3>
    <div>
      <h4>Fideos con salsa</h4>
      <label>fideos</label>
      <label>tomate</label>
      <label>cebolla</label>
    </div>
  </div>
  <div>
    <h3>Miércoles</h3>
    <div>
      <h4>Lentejas</h4>
      <label>lentejas</label>
      <label>zanahoria</label>
    </div>
  </div>
</body></html>
"""


class TestExtraerRecetasPorDia(unittest.TestCase):

    def setUp(self):
        self.ext = make_extractor(SAMPLE_HTML_RECETAS)

    def test_lunes_found(self):
        recetas = self.ext._extraer_recetas_por_dia()
        self.assertIn('Lunes', recetas)

    def test_martes_found(self):
        recetas = self.ext._extraer_recetas_por_dia()
        self.assertIn('Martes', recetas)

    def test_miercoles_found(self):
        recetas = self.ext._extraer_recetas_por_dia()
        # Puede aparecer como 'Miércoles' o 'Miercoles'
        dias = list(recetas.keys())
        encontrado = any('miercoles' in d.lower() or 'miércoles' in d.lower() for d in dias)
        self.assertTrue(encontrado, f"Miércoles no encontrado. Días: {dias}")

    def test_lunes_ingredientes(self):
        recetas = self.ext._extraer_recetas_por_dia()
        ings = recetas['Lunes']['ingredientes']
        self.assertIn('pollo', ings)
        self.assertIn('ajo', ings)

    def test_martes_ingredientes(self):
        recetas = self.ext._extraer_recetas_por_dia()
        ings = recetas['Martes']['ingredientes']
        self.assertIn('fideos', ings)
        self.assertIn('tomate', ings)

    def test_nombre_receta_extracted(self):
        recetas = self.ext._extraer_recetas_por_dia()
        # El nombre de la receta del lunes debería ser "Pollo al limón"
        nombre = recetas['Lunes'].get('nombre', '')
        self.assertIn('Pollo', nombre)

    def test_no_duplicates_per_day(self):
        recetas = self.ext._extraer_recetas_por_dia()
        for dia, data in recetas.items():
            ings = data['ingredientes']
            self.assertEqual(len(ings), len(set(i.lower() for i in ings)),
                             f"Ingredientes duplicados en {dia}: {ings}")

    def test_days_not_in_ingredients(self):
        """El nombre del día no debe aparecer como ingrediente."""
        recetas = self.ext._extraer_recetas_por_dia()
        dias_lower = ['lunes', 'martes', 'miercoles', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
        for dia, data in recetas.items():
            for ing in data['ingredientes']:
                self.assertNotIn(ing.lower(), dias_lower,
                                 f"'{ing}' parece un día, no un ingrediente ({dia})")


# ===========================================================================
# Test Suite: Construcción de item_to_days en generar_json
# ===========================================================================

SAMPLE_HTML_FULL = """
<html><body>
  <div id="lista_compra_g">
    <div class="e-con-inner">
      <strong>Supermercado</strong>
      <label>arroz blanco</label>
      <label>fideos</label>
      <strong>Verdulería</strong>
      <label>tomate perita</label>
      <label>cebolla</label>
    </div>
  </div>
  <div>
    <h3>Lunes</h3>
    <div>
      <h4>Risotto de arroz</h4>
      <label>arroz blanco</label>
      <label>caldo</label>
    </div>
  </div>
  <div>
    <h3>Martes</h3>
    <div>
      <h4>Pasta al tomate</h4>
      <label>fideos</label>
      <label>tomate perita</label>
      <label>cebolla</label>
    </div>
  </div>
</body></html>
"""


class TestItemToDays(unittest.TestCase):

    def setUp(self):
        self.ext = make_extractor(SAMPLE_HTML_FULL)

    def test_item_to_days_built(self):
        self.ext.extraer()
        datos = self.ext.generar_json()
        self.assertIn('item_to_days', datos)

    def test_arroz_mapped_to_lunes(self):
        self.ext.extraer()
        datos = self.ext.generar_json()
        itd = datos.get('item_to_days', {})
        # "arroz blanco" debería estar en Lunes
        arroz_days = itd.get('arroz blanco', [])
        self.assertIn('Lunes', arroz_days)

    def test_fideos_mapped_to_martes(self):
        self.ext.extraer()
        datos = self.ext.generar_json()
        itd = datos.get('item_to_days', {})
        fideos_days = itd.get('fideos', [])
        self.assertIn('Martes', fideos_days)

    def test_recetas_in_json(self):
        self.ext.extraer()
        datos = self.ext.generar_json()
        self.assertIn('recetas', datos)

    def test_general_list_in_json(self):
        self.ext.extraer()
        datos = self.ext.generar_json()
        self.assertIn('general', datos)
        total = sum(len(items) for items in datos['general'].values())
        self.assertGreater(total, 0)


# ===========================================================================
# Test Suite: Detección de semana actual (lógica de selección)
# ===========================================================================

class TestDetectarSemanaActual(unittest.TestCase):

    @patch('paulina_scraper.MenuDiscoverer.descubrir_menus')
    def test_uses_discoverer_result(self, mock_discover):
        """Debe usar MenuDiscoverer y seleccionar la semana más alta."""
        mock_discover.return_value = [
            {'tipo': 'semanal', 'semana': 3, 'url': '...', 'titulo': 'Semana 3'},
            {'tipo': 'semanal', 'semana': 7, 'url': '...', 'titulo': 'Semana 7'},
            {'tipo': 'especial', 'semana': None, 'url': '...', 'titulo': 'Especial'},
        ]
        from paulina_scraper import PaulinaExtractor
        ext = PaulinaExtractor()
        semana = ext.detectar_semana_actual()
        self.assertEqual(semana, 7)

    @patch('paulina_scraper.MenuDiscoverer.descubrir_menus')
    @patch('paulina_scraper.PaulinaExtractor.listar_semanas_disponibles')
    def test_fallback_to_brute_force(self, mock_listar, mock_discover):
        """Si MenuDiscoverer falla, debe caer al método de fuerza bruta."""
        mock_discover.side_effect = Exception("timeout")
        mock_listar.return_value = [5, 4, 3]
        from paulina_scraper import PaulinaExtractor
        ext = PaulinaExtractor()
        semana = ext.detectar_semana_actual()
        self.assertEqual(semana, 5)

    @patch('paulina_scraper.MenuDiscoverer.descubrir_menus')
    @patch('paulina_scraper.PaulinaExtractor.listar_semanas_disponibles')
    def test_default_to_1_when_nothing_found(self, mock_listar, mock_discover):
        """Si ningún método encuentra semanas, retorna 1."""
        mock_discover.return_value = []
        mock_listar.return_value = []
        from paulina_scraper import PaulinaExtractor
        ext = PaulinaExtractor()
        semana = ext.detectar_semana_actual()
        self.assertEqual(semana, 1)

    @patch('paulina_scraper.MenuDiscoverer.descubrir_menus')
    def test_ignores_especial_menus(self, mock_discover):
        """No debe considerar menús especiales al detectar la semana actual."""
        mock_discover.return_value = [
            {'tipo': 'especial', 'semana': None, 'url': '...', 'titulo': 'Especial navidad'},
            {'tipo': 'semanal', 'semana': 2, 'url': '...', 'titulo': 'Semana 2'},
        ]
        from paulina_scraper import PaulinaExtractor
        ext = PaulinaExtractor()
        semana = ext.detectar_semana_actual()
        self.assertEqual(semana, 2)


# ===========================================================================
# Test Suite: logger está definido (no NameError)
# ===========================================================================

class TestLoggerDefined(unittest.TestCase):

    def test_logger_is_defined(self):
        """El módulo debe tener un logger definido para evitar NameError en generar_json."""
        import paulina_scraper
        self.assertTrue(hasattr(paulina_scraper, 'logger'))

    def test_logger_can_call_info(self):
        import paulina_scraper
        # No debe lanzar excepción
        try:
            paulina_scraper.logger.info("Test log message")
        except Exception as e:
            self.fail(f"logger.info() lanzó excepción: {e}")


# ===========================================================================
# Test Suite: generar_json estructura mínima
# ===========================================================================

class TestGenerarJsonEstructura(unittest.TestCase):

    def test_json_has_required_fields(self):
        ext = make_extractor(SAMPLE_HTML_FULL)
        ext.extraer()
        datos = ext.generar_json()
        self.assertIn('titulo', datos)
        self.assertIn('semana', datos)
        self.assertIn('generado', datos)

    def test_json_general_and_veggie(self):
        ext = make_extractor(SAMPLE_HTML_LISTA)
        ext.extraer()
        datos = ext.generar_json()
        self.assertIn('general', datos)
        self.assertIn('veggie', datos)

    def test_veggie_fallback_to_general(self):
        """Si no hay lista veggie separada, debe ser copia de la general."""
        html = """
        <html><body>
          <div id="lista_compra_g">
            <div class="e-con-inner">
              <strong>Supermercado</strong>
              <label>arroz</label>
            </div>
          </div>
        </body></html>
        """
        ext = make_extractor(html)
        ext.extraer()
        datos = ext.generar_json()
        # veggie debe tener contenido (copiado del general)
        total_veggie = sum(len(items) for items in datos.get('veggie', {}).values())
        self.assertGreater(total_veggie, 0)


# ===========================================================================
# Test Suite: MenuDiscoverer.descubrir_menus con HTML mockeado
# ===========================================================================

class TestMenuDiscovererDescubrirMenus(unittest.TestCase):

    def _run_discoverer_with_html(self, html: str) -> list:
        """Ejecuta MenuDiscoverer.descubrir_menus con HTML mockeado (sin red)."""
        from paulina_scraper import MenuDiscoverer
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()

        mock_session = MagicMock()
        mock_session.get.return_value = mock_response

        with patch('paulina_scraper.get_session', return_value=mock_session):
            return MenuDiscoverer.descubrir_menus()

    def test_finds_weekly_menus(self):
        html = """
        <html><body>
          <a href="/menu-semana-5/">Semana 5</a>
          <a href="/menu-semana-6/">Semana 6</a>
        </body></html>
        """
        menus = self._run_discoverer_with_html(html)
        semanas = [m['semana'] for m in menus if m['tipo'] == 'semanal']
        self.assertIn(5, semanas)
        self.assertIn(6, semanas)

    def test_excludes_landing_page(self):
        html = """
        <html><body>
          <a href="/menu-semanal/">Menú Semanal</a>
          <a href="/menu-semana-5/">Semana 5</a>
        </body></html>
        """
        menus = self._run_discoverer_with_html(html)
        urls = [m['url'] for m in menus]
        # La landing page no debe aparecer
        self.assertFalse(any('menu-semanal/' == u.split('paulinacocina.net')[-1].strip('/')
                              for u in urls),
                         f"Landing page encontrada en: {urls}")

    def test_finds_especial_menus(self):
        html = """
        <html><body>
          <a href="/menu-especial-navidad/">Menú Especial Navidad</a>
        </body></html>
        """
        menus = self._run_discoverer_with_html(html)
        especiales = [m for m in menus if m['tipo'] == 'especial']
        self.assertEqual(len(especiales), 1)

    def test_no_menus_returns_empty_list(self):
        html = "<html><body><p>Sin menús</p></body></html>"
        menus = self._run_discoverer_with_html(html)
        self.assertEqual(menus, [])

    def test_deduplicates_same_url(self):
        html = """
        <html><body>
          <a href="/menu-semana-5/">Semana 5</a>
          <a href="/menu-semana-5/">Ver Semana 5 otra vez</a>
        </body></html>
        """
        menus = self._run_discoverer_with_html(html)
        semana5 = [m for m in menus if m.get('semana') == 5]
        self.assertEqual(len(semana5), 1)

    def test_sorted_by_semana_descending(self):
        html = """
        <html><body>
          <a href="/menu-semana-3/">Semana 3</a>
          <a href="/menu-semana-7/">Semana 7</a>
          <a href="/menu-semana-5/">Semana 5</a>
        </body></html>
        """
        menus = self._run_discoverer_with_html(html)
        semanales = [m for m in menus if m['tipo'] == 'semanal']
        semanas = [m['semana'] for m in semanales]
        self.assertEqual(semanas, sorted(semanas, reverse=True))


if __name__ == '__main__':
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""
🍳 Paulina Cocina - Scraper de Lista de Compras
================================================
Descarga el menú semanal y lo sube a Firebase para sincronizar con la webapp.

Uso:
    python paulina_scraper.py                    # Descarga el menú actual
    python paulina_scraper.py --semana 5         # Descarga semana específica
    python paulina_scraper.py --local            # Solo guarda JSON local (no sube a Firebase)
    python paulina_scraper.py --menus            # Lista todos los menús activos
    python paulina_scraper.py --url URL          # Descarga menú desde URL específica
    python paulina_scraper.py --reset-db         # Borra menús de Firebase y re-descarga los activos

Nota: El scraper siempre descarga la lista de compras completa + recetas de cada día.
      El filtrado por días específicos se realiza en la interfaz web al importar.

Autenticación:
    El sitio requiere login. Configurar variables de entorno:
        PAULINA_USER=tu_email
        PAULINA_PASS=tu_contraseña
    O usar argumentos: --user EMAIL --password PASS

Configuración Firebase:
    Crear archivo 'firebase_credentials.json' con las credenciales de Firebase Admin SDK.
    Ver SETUP_FIREBASE.md para más detalles.
"""

import os
import re
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from urllib.parse import urljoin, urlparse

# Intentar importar dependencias
try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("📦 Instalando dependencias básicas...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "beautifulsoup4", "-q"])
    import requests
    from bs4 import BeautifulSoup


class PaulinaSession:
    """Maneja la sesión autenticada con el sitio de Paulina Cocina (WordPress/WooCommerce)."""

    LOGIN_URL = "https://almacen.paulinacocina.net/wp-login.php"
    BASE_URL = "https://almacen.paulinacocina.net"

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    }

    def __init__(self, user: str = None, password: str = None):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.authenticated = False

        # Obtener credenciales de args > env vars
        self.user = user or os.environ.get('PAULINA_USER', '')
        self.password = password or os.environ.get('PAULINA_PASS', '')

    def login(self) -> bool:
        """Inicia sesión en el sitio via wp-login.php."""
        if not self.user or not self.password:
            print("⚠️  No se configuraron credenciales de Paulina Cocina")
            print("   Configurá PAULINA_USER y PAULINA_PASS como variables de entorno")
            print("   O usá --user EMAIL --password PASS")
            return False

        print(f"🔐 Iniciando sesión como {self.user}...")

        try:
            # POST al login de WordPress
            login_data = {
                'log': self.user,
                'pwd': self.password,
                'wp-submit': 'Acceder',
                'redirect_to': self.BASE_URL + '/menu-semanal/',
                'testcookie': '1',
            }

            # Primero obtener cookies iniciales
            self.session.get(self.LOGIN_URL, timeout=15)

            # Enviar login
            response = self.session.post(
                self.LOGIN_URL,
                data=login_data,
                timeout=15,
                allow_redirects=True,
            )

            # Verificar si el login fue exitoso
            # WordPress redirige al redirect_to si el login es exitoso
            # Si falla, se queda en wp-login.php con error
            if 'wp-login.php' in response.url and 'redirect_to' not in response.url:
                # Verificar si hay mensaje de error en la respuesta
                if 'login_error' in response.text or 'ERROR' in response.text:
                    print("❌ Login fallido: credenciales incorrectas")
                    return False

            # Verificar que tengamos cookies de autenticación
            cookies = self.session.cookies.get_dict()
            has_auth = any(
                key.startswith('wordpress_logged_in') or key.startswith('wordpress_sec')
                for key in cookies
            )

            if has_auth:
                print("✅ Login exitoso")
                self.authenticated = True
                return True

            # Último intento: verificar accediendo a una página protegida
            test = self.session.get(self.BASE_URL + '/menu-semanal/', timeout=15)
            if test.status_code == 200 and 'menu' in test.text.lower():
                print("✅ Login exitoso (verificado por acceso)")
                self.authenticated = True
                return True

            print("⚠️  No se pudo verificar el login. Intentando continuar...")
            self.authenticated = True  # Intentar de todos modos
            return True

        except requests.RequestException as e:
            print(f"❌ Error en login: {e}")
            return False

    def get(self, url: str, **kwargs) -> requests.Response:
        """GET autenticado."""
        kwargs.setdefault('timeout', 30)
        return self.session.get(url, **kwargs)


# Sesión global (se inicializa una vez)
_global_session = None

def get_session(user: str = None, password: str = None) -> PaulinaSession:
    """Obtiene o crea la sesión autenticada global."""
    global _global_session
    if _global_session is None:
        _global_session = PaulinaSession(user, password)
        _global_session.login()
    return _global_session


class MenuDiscoverer:
    """Descubre todos los menús activos desde la página principal."""

    MENU_PAGE_URL = "https://almacen.paulinacocina.net/menu-semanal/"

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    }

    @classmethod
    def descubrir_menus(cls) -> list:
        """
        Descubre todos los menús activos desde la página principal.
        Retorna lista de dicts con: url, titulo, tipo ('semanal' o 'especial')
        """
        print("🔍 Buscando menús activos en la página principal...")

        try:
            session = get_session()
            response = session.get(cls.MENU_PAGE_URL)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            menus = []
            seen_urls = set()

            # Buscar links a menús
            for link in soup.find_all('a', href=True):
                href = link['href']

                # Filtrar URLs de menús
                if '/menu/' in href or '/menu-semana' in href:
                    # Normalizar URL
                    full_url = urljoin(cls.MENU_PAGE_URL, href)
                    # Remover parámetros de query
                    parsed = urlparse(full_url)
                    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

                    if clean_url in seen_urls:
                        continue
                    seen_urls.add(clean_url)

                    # Determinar tipo y título
                    titulo = link.get_text(strip=True) or "Menú"

                    # Limpiar título
                    if not titulo or len(titulo) < 3:
                        # Intentar extraer del URL
                        path = parsed.path.strip('/')
                        titulo = path.split('/')[-1].replace('-', ' ').title()

                    # Determinar tipo
                    if 'especial' in clean_url.lower() or 'especial' in titulo.lower():
                        tipo = 'especial'
                    else:
                        tipo = 'semanal'

                    # Extraer número de semana si existe
                    semana_match = re.search(r'semana[- ]?(\d+)', clean_url, re.I)
                    semana = int(semana_match.group(1)) if semana_match else None

                    menus.append({
                        'url': clean_url,
                        'titulo': titulo,
                        'tipo': tipo,
                        'semana': semana
                    })

            # Ordenar: primero especiales, luego por semana descendente
            menus.sort(key=lambda x: (x['tipo'] != 'especial', -(x['semana'] or 0)))

            print(f"✅ Encontrados {len(menus)} menús activos")
            return menus

        except requests.RequestException as e:
            print(f"❌ Error accediendo a página de menús: {e}")
            return []


class PaulinaExtractor:
    """Extrae la lista de compras del menú semanal de Paulina Cocina."""

    BASE_URL = "https://almacen.paulinacocina.net/menu-semana-{semana}"

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    }

    CATEGORIAS_MAP = {
        'supermercado': ('Supermercado 🏪', 1),
        'carnes': ('Carnes 🥩', 2),
        'dietética': ('Dietética 🥗', 3),
        'dietetica': ('Dietética 🥗', 3),
        'verdulería': ('Verdulería 🥬', 4),
        'verduleria': ('Verdulería 🥬', 4),
        'yapa': ('Yapa ⭐', 5),
        'comodín': ('Comodín 👑', 6),
        'comodin': ('Comodín 👑', 6),
        'seguro': ('Ya tenés en casa ✅', 7),
        'casa': ('Ya tenés en casa ✅', 7),
    }

    # Días de la semana para extraer recetas
    DIAS = ['lunes', 'martes', 'miércoles', 'miercoles', 'jueves', 'viernes', 'sábado', 'sabado', 'domingo']

    def __init__(self, semana: int = None, modo: str = 'general', url: str = None):
        self.semana = semana
        self.url = url  # URL directa (para menús especiales)
        self.modo = modo  # 'general', 'dias', 'platos', o nombre de día específico
        self.html_content = None
        self.soup = None
        self.titulo = ""
        self.fechas = ""
        self.lista_general = {}
        self.lista_veggie = {}
        self.recetas_por_dia = {}  # { 'lunes': {'nombre': '...', 'ingredientes': [...]} }
        self.platos = []  # Lista de platos para menús especiales (sin lista general)
        self.tiene_lista_general = True  # Se detecta automáticamente
        self.platos_seleccionados = None  # Lista de índices (1-5) de platos a incluir
        self.dias_seleccionados = None  # Lista de índices (1-7) de días a incluir

    def detectar_semana_actual(self) -> int:
        """Detecta qué semana está disponible (la más reciente)."""
        semanas = self.listar_semanas_disponibles()
        if semanas:
            print(f"📅 Detectada semana {semanas[0]} como la más reciente")
            return semanas[0]
        return 1

    @classmethod
    def listar_semanas_disponibles(cls) -> list:
        """Lista todas las semanas disponibles."""
        disponibles = []
        print("🔍 Buscando semanas disponibles...")
        session = get_session()
        for semana in range(20, 0, -1):
            url = cls.BASE_URL.format(semana=semana)
            try:
                response = session.get(url, timeout=10)
                if response.status_code == 200:
                    disponibles.append(semana)
            except:
                continue
        return disponibles

    def descargar(self) -> bool:
        """Descarga el HTML del menú."""
        # Determinar URL a usar
        if self.url:
            url = self.url
        elif self.semana is not None:
            url = self.BASE_URL.format(semana=self.semana)
        else:
            self.semana = self.detectar_semana_actual()
            url = self.BASE_URL.format(semana=self.semana)

        print(f"🌐 Descargando: {url}")

        try:
            session = get_session()
            response = session.get(url)
            response.raise_for_status()

            self.html_content = response.text
            self.soup = BeautifulSoup(self.html_content, 'html.parser')

            # Extraer título
            title_tag = self.soup.find('title')
            if title_tag:
                self.titulo = title_tag.text.split(' - ')[0].strip()

            # Si no tenemos número de semana, intentar extraerlo del URL o título
            if self.semana is None:
                semana_match = re.search(r'semana[- ]?(\d+)', url + self.titulo, re.I)
                if semana_match:
                    self.semana = int(semana_match.group(1))

            # Extraer fechas - buscar en el título o en la página
            self._extraer_fechas()

            # Detectar si tiene lista general o es menú de platos individuales
            self._detectar_tipo_menu()

            print(f"✅ Descargado: {self.titulo}")
            if self.fechas:
                print(f"   📅 {self.fechas}")
            if not self.tiene_lista_general:
                print(f"   ℹ️  Este menú tiene platos individuales (sin lista general)")
            return True

        except requests.RequestException as e:
            print(f"❌ Error descargando: {e}")
            return False

    def _detectar_tipo_menu(self):
        """Detecta si el menú tiene lista general o platos individuales."""
        # Buscar elementos típicos de lista general
        lista_general = self.soup.find(id='lista_compra_g')
        if lista_general:
            self.tiene_lista_general = True
            return

        # Buscar texto "lista de compras" o "lista general"
        texto_pagina = self.soup.get_text().lower()
        if 'lista de compras' in texto_pagina or 'lista general' in texto_pagina:
            # Verificar que haya items de lista
            labels = self.soup.find_all('label')
            if len(labels) > 10:
                self.tiene_lista_general = True
                return

        # Buscar estructura de platos individuales (recetas con ingredientes)
        recetas = self._buscar_platos_individuales()
        if len(recetas) >= 3:
            self.tiene_lista_general = False
            self.platos = recetas
            return

        # Default: asumir que tiene lista general
        self.tiene_lista_general = True

    def _buscar_platos_individuales(self) -> list:
        """
        Busca platos individuales en menús especiales.
        Retorna lista de dicts: {nombre, ingredientes: [], url_receta}
        """
        platos = []

        # Buscar secciones de recetas/platos
        # Estrategia 1: Buscar por estructura de días o numeración
        for pattern in [r'plato\s*(\d+)', r'día\s*(\d+)', r'receta\s*(\d+)']:
            for elem in self.soup.find_all(['h2', 'h3', 'h4', 'div']):
                texto = elem.get_text(strip=True)
                if re.search(pattern, texto, re.I):
                    plato_info = self._extraer_info_plato(elem)
                    if plato_info and plato_info not in platos:
                        platos.append(plato_info)

        # Estrategia 2: Buscar por clases CSS comunes de recetas
        for elem in self.soup.find_all(class_=re.compile(r'recipe|receta|plato|dish', re.I)):
            plato_info = self._extraer_info_plato(elem)
            if plato_info and plato_info not in platos:
                platos.append(plato_info)

        # Estrategia 3: Buscar links a recetas individuales
        for link in self.soup.find_all('a', href=True):
            href = link['href']
            if 'receta' in href.lower() or '/recipe/' in href.lower():
                titulo = link.get_text(strip=True)
                if titulo and len(titulo) > 5:
                    platos.append({
                        'nombre': titulo,
                        'ingredientes': [],
                        'url_receta': href
                    })

        return platos[:10]  # Limitar a 10 platos

    def _extraer_info_plato(self, elem) -> dict:
        """Extrae información de un plato desde un elemento HTML."""
        # Buscar en el elemento y sus padres
        parent = elem
        for _ in range(3):
            if parent.parent:
                parent = parent.parent

        # Buscar título del plato
        nombre = ""
        for h in parent.find_all(['h2', 'h3', 'h4', 'strong']):
            texto = h.get_text(strip=True)
            if len(texto) > 5 and len(texto) < 100:
                nombre = texto
                break

        if not nombre:
            nombre = elem.get_text(strip=True)[:50]

        # Buscar ingredientes
        ingredientes = []
        for label in parent.find_all('label'):
            ing = label.get_text(strip=True)
            ing = re.sub(r'^[\[\]✓\s]+', '', ing).strip()
            if ing and len(ing) > 1 and len(ing) < 100:
                ingredientes.append(ing)

        # También buscar en listas
        for li in parent.find_all('li'):
            texto = li.get_text(strip=True)
            if len(texto) > 2 and len(texto) < 100:
                # Filtrar items que parecen ingredientes
                if any(palabra in texto.lower() for palabra in
                       ['gr', 'kg', 'ml', 'litro', 'cucharada', 'taza', 'unidad']):
                    ingredientes.append(texto)

        if nombre:
            return {
                'nombre': nombre,
                'ingredientes': ingredientes,
                'url_receta': None
            }
        return None

    def _extraer_fechas(self):
        """Extrae las fechas del menú (ej: '02 al 06 de febrero')."""
        # Buscar en h1, h2, h3 que contengan fechas
        for heading in self.soup.find_all(['h1', 'h2', 'h3']):
            texto = heading.get_text(strip=True)
            # Buscar patrón de fechas: "del X al Y de mes" o "X al Y de mes"
            match = re.search(r'(?:del\s+)?(\d{1,2})\s*(?:al|a)\s*(\d{1,2})\s*(?:de\s+)?(\w+)', texto, re.IGNORECASE)
            if match:
                dia1, dia2, mes = match.groups()
                self.fechas = f"{dia1} al {dia2} de {mes.lower()}"
                return

        # Buscar en elementos con clase que contenga 'date' o 'fecha'
        for elem in self.soup.find_all(class_=re.compile(r'date|fecha', re.I)):
            texto = elem.get_text(strip=True)
            if re.search(r'\d{1,2}.*(?:al|a).*\d{1,2}', texto):
                self.fechas = texto
                return

        # Fallback: buscar en meta description
        meta_desc = self.soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            content = meta_desc['content']
            match = re.search(r'(?:del\s+)?(\d{1,2})\s*(?:al|a)\s*(\d{1,2})\s*(?:de\s+)?(\w+)', content, re.IGNORECASE)
            if match:
                dia1, dia2, mes = match.groups()
                self.fechas = f"{dia1} al {dia2} de {mes.lower()}"

    def _detectar_categoria(self, texto: str) -> tuple:
        """Detecta la categoría basándose en el texto."""
        texto_lower = texto.lower()
        for keyword, (nombre, orden) in self.CATEGORIAS_MAP.items():
            if keyword in texto_lower:
                return nombre, orden
        return 'Otros 📦', 99

    def _extraer_lista(self, container_id: str) -> dict:
        """Extrae items de un contenedor de lista."""
        categorias = {}

        container = self.soup.find(id=container_id)
        if not container:
            # Solo usar fallbacks para la lista general, no para la veggie
            # ya que los fallbacks buscan "lista de compras" / "lista general"
            # y terminarían devolviendo la lista general como si fuera veggie
            if container_id == 'lista_compra_v':
                return {}
            container = self.soup.find(attrs={'data-nombre': re.compile(r'Lista', re.I)})

        if not container:
            return self._extraer_lista_alternativo()

        parent = container
        for _ in range(5):
            parent_candidate = parent.find_parent('div', class_='e-con-inner')
            if parent_candidate:
                parent = parent_candidate
            else:
                break

        categoria_actual = 'Supermercado 🏪'
        orden_actual = 1

        for elem in parent.descendants:
            if elem.name == 'strong' or (elem.name and 'heading' in str(elem.get('class', []))):
                texto = elem.get_text(strip=True)
                if texto and len(texto) > 2:
                    cat_detectada, orden = self._detectar_categoria(texto)
                    if orden != 99:
                        categoria_actual = cat_detectada
                        orden_actual = orden

            elif elem.name == 'label':
                texto = elem.get_text(strip=True)
                texto = re.sub(r'^[\[\]✓\s]+', '', texto).strip()

                if texto and len(texto) > 1 and not texto.startswith('Lista'):
                    if categoria_actual not in categorias:
                        categorias[categoria_actual] = {'orden': orden_actual, 'items': []}

                    if texto not in categorias[categoria_actual]['items']:
                        categorias[categoria_actual]['items'].append(texto)

        return categorias

    def _extraer_lista_alternativo(self) -> dict:
        """Método alternativo de extracción - solo lista general, no recetas diarias."""
        categorias = {}

        # Buscar sección que contenga "Lista de compras" o similar
        lista_section = None
        for elem in self.soup.find_all(['div', 'section']):
            texto = elem.get_text()[:200].lower()
            if 'lista de compras' in texto or 'lista general' in texto:
                # Verificar que NO sea una receta diaria
                if not any(dia in texto for dia in self.DIAS):
                    lista_section = elem
                    break

        # Si no encontramos sección específica, buscar por clases comunes
        if not lista_section:
            for elem in self.soup.find_all(class_=re.compile(r'lista|shopping|compras', re.I)):
                if not any(dia in elem.get_text()[:100].lower() for dia in self.DIAS):
                    lista_section = elem
                    break

        # Extraer labels solo de la sección encontrada, o de toda la página filtrando
        if lista_section:
            labels = lista_section.find_all('label')
        else:
            # Fallback: usar todos los labels pero filtrar los de recetas diarias
            labels = []
            for label in self.soup.find_all('label'):
                # Verificar que el label no esté dentro de una sección de receta diaria
                parent_text = ''
                for parent in label.parents:
                    if parent.name in ['div', 'section']:
                        parent_text = parent.get_text()[:200].lower()
                        break

                # Excluir si está en sección de receta de un día
                es_receta_diaria = any(
                    f'{dia}' in parent_text and ('receta' in parent_text or 'ingredientes' in parent_text)
                    for dia in self.DIAS
                )

                if not es_receta_diaria:
                    labels.append(label)

        categoria_actual = 'Supermercado 🏪'
        items_vistos = set()  # Para evitar duplicados

        for label in labels:
            texto = label.get_text(strip=True)
            texto = re.sub(r'^[\[\]✓\s]+', '', texto).strip()

            if not texto or len(texto) < 2:
                continue

            # Normalizar para comparar duplicados
            texto_normalizado = texto.lower().strip()
            if texto_normalizado in items_vistos:
                continue

            cat_detectada, orden = self._detectar_categoria(texto)
            if orden != 99 and len(texto) < 30:
                categoria_actual = cat_detectada
                continue

            if categoria_actual not in categorias:
                categorias[categoria_actual] = {'orden': 1, 'items': []}

            categorias[categoria_actual]['items'].append(texto)
            items_vistos.add(texto_normalizado)

        return categorias

    def _extraer_recetas_por_dia(self) -> dict:
        """Extrae los ingredientes de cada receta diaria."""
        recetas = {}

        # Constantes de validación
        MAX_INGREDIENT_LENGTH = 200
        INSTRUCTION_PATTERN = re.compile(r'^(paso|step|instruc|prepar|cocin|herv|serv)', re.I)

        dias_buscar = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']

        for dia in dias_buscar:
            dia_sin_acento = dia.replace('é', 'e').replace('á', 'a')

            # Estrategia 1: buscar headings (h2/h3/h4/strong) que contengan el día.
            # Priorizar headings sobre divs para evitar matchear wrappers grandes.
            section = None
            for heading in self.soup.find_all(['h2', 'h3', 'h4', 'strong']):
                h_text = heading.get_text(strip=True).lower()
                if len(h_text) > 80:
                    continue
                if dia in h_text or dia_sin_acento in h_text:
                    # Subir hasta encontrar un contenedor con ingredientes
                    parent = heading
                    for _ in range(5):
                        if parent.parent and parent.parent.name not in ['body', '[document]']:
                            parent = parent.parent
                            if parent.find('label') or parent.find('li'):
                                section = parent
                                break
                    if not section:
                        section = heading.parent
                    break

            # Estrategia 2: buscar por ID o data-attribute con nombre del día
            if not section:
                for id_pat in [dia, dia_sin_acento, f'receta_{dia}', f'receta_{dia_sin_acento}']:
                    elem = self.soup.find(id=re.compile(rf'^{re.escape(id_pat)}', re.I))
                    if not elem:
                        elem = self.soup.find(attrs={'data-nombre': re.compile(rf'{re.escape(id_pat)}', re.I)})
                    if elem:
                        section = elem
                        break

            if not section:
                continue

            # Extraer nombre de receta (heading que NO sea el día)
            nombre_receta = ""
            for h in section.find_all(['h2', 'h3', 'h4']):
                h_texto = h.get_text(strip=True)
                h_lower = h_texto.lower()
                if len(h_texto) > 5 and dia not in h_lower and dia_sin_acento not in h_lower:
                    nombre_receta = h_texto
                    break

            # Extraer ingredientes: primero labels, luego li como fallback
            ingredientes = []
            for label in section.find_all('label'):
                ing = label.get_text(strip=True)
                ing = re.sub(r'^[\[\]✓\s]+', '', ing).strip()
                # Validar que parece un ingrediente real
                if ing and len(ing) > 1 and len(ing) < MAX_INGREDIENT_LENGTH:
                    # Verificar que no sea un título, instrucción o HTML residual
                    if not INSTRUCTION_PATTERN.match(ing.lower()):
                        ingredientes.append(ing)

            # Estrategia 2: buscar li sueltos si no hay labels
            if not ingredientes:
                for li in section.find_all('li'):
                    texto = li.get_text(strip=True)
                    texto = re.sub(r'^[\[\]✓\s•·\-]+', '', texto).strip()
                    if texto and len(texto) > 1 and len(texto) < MAX_INGREDIENT_LENGTH:
                        if not INSTRUCTION_PATTERN.match(texto.lower()):
                            ingredientes.append(texto)

            # Estrategia 3: buscar listas ul/ol si no hay labels ni li sueltos
            if not ingredientes:
                for ul in section.find_all(['ul', 'ol']):
                    for li in ul.find_all('li', recursive=False):
                        texto = li.get_text(strip=True)
                        texto = re.sub(r'^[\[\]✓\s•·\-]+', '', texto).strip()
                        if texto and len(texto) > 1 and len(texto) < MAX_INGREDIENT_LENGTH:
                            if not INSTRUCTION_PATTERN.match(texto.lower()):
                                ingredientes.append(texto)

            # Deduplicar ingredientes del día
            seen = set()
            ingredientes_unicos = []
            for ing in ingredientes:
                norm = ing.lower().strip()
                if norm and norm not in seen:
                    seen.add(norm)
                    ingredientes_unicos.append(ing)
            ingredientes = ingredientes_unicos

            if nombre_receta or ingredientes:
                recetas[dia.capitalize()] = {
                    'nombre': nombre_receta,
                    'ingredientes': ingredientes
                }

        return recetas

    def set_platos_seleccionados(self, platos: list):
        """
        Define qué platos incluir (índices 1-5 o 'todos').
        Ej: [1, 2, 3] para los primeros 3 platos.
        """
        self.platos_seleccionados = platos

    def set_dias_seleccionados(self, dias: list):
        """
        Define qué días incluir (índices 1-7).
        Ej: [1, 2, 3] para Lunes, Martes, Miércoles.
        """
        self.dias_seleccionados = dias

    def _combinar_ingredientes(self, platos_indices: list = None) -> dict:
        """
        Combina ingredientes de múltiples platos en una lista unificada.
        Agrupa por categoría y elimina duplicados.
        """
        # Primero extraer platos si no los tenemos
        if not self.platos:
            self.platos = self._extraer_platos_con_ingredientes()

        if not self.platos:
            print("   ⚠️  No se encontraron platos con ingredientes")
            return {}

        # Determinar qué platos incluir
        if platos_indices:
            platos_a_usar = [self.platos[i-1] for i in platos_indices if i-1 < len(self.platos)]
        else:
            platos_a_usar = self.platos

        print(f"   📋 Combinando ingredientes de {len(platos_a_usar)} platos:")
        for i, plato in enumerate(platos_a_usar, 1):
            print(f"      {i}. {plato['nombre']} ({len(plato['ingredientes'])} ingredientes)")

        # Combinar ingredientes
        todos_ingredientes = []
        for plato in platos_a_usar:
            todos_ingredientes.extend(plato['ingredientes'])

        # Agrupar y deduplicar
        return self._agrupar_ingredientes_por_categoria(todos_ingredientes)

    def _agrupar_ingredientes_por_categoria(self, ingredientes: list) -> dict:
        """Agrupa ingredientes por categoría y deduplica."""
        categorias = {}
        items_vistos = set()

        for ing in ingredientes:
            texto = ing.strip()
            if not texto or len(texto) < 2:
                continue

            # Normalizar para comparar duplicados
            texto_normalizado = texto.lower().strip()
            if texto_normalizado in items_vistos:
                continue
            items_vistos.add(texto_normalizado)

            # Detectar categoría
            cat_detectada, orden = self._detectar_categoria(texto)

            # Si el texto es solo un nombre de categoría, usarlo para cambiar
            if orden != 99 and len(texto) < 25:
                continue

            # Categoria por defecto
            if cat_detectada == 'Otros 📦':
                cat_detectada = 'Supermercado 🏪'
                orden = 1

            if cat_detectada not in categorias:
                categorias[cat_detectada] = {'orden': orden, 'items': []}

            categorias[cat_detectada]['items'].append(texto)

        return categorias

    def _extraer_platos_con_ingredientes(self) -> list:
        """
        Extrae todos los platos con sus ingredientes.
        Funciona para menús especiales con recetas individuales.
        """
        platos = []

        # Estrategia 1: Buscar toggles o acordeones de ingredientes
        for toggle in self.soup.find_all(class_=re.compile(r'toggle|accordion|collapse', re.I)):
            titulo_elem = toggle.find(['h2', 'h3', 'h4', 'strong', 'span'])
            if titulo_elem:
                titulo = titulo_elem.get_text(strip=True)

                # Buscar ingredientes dentro
                ingredientes = []
                for label in toggle.find_all('label'):
                    ing = label.get_text(strip=True)
                    ing = re.sub(r'^[\[\]✓\s]+', '', ing).strip()
                    if ing and len(ing) > 1:
                        ingredientes.append(ing)

                if titulo and ingredientes:
                    platos.append({
                        'nombre': titulo,
                        'ingredientes': ingredientes,
                        'url_receta': None
                    })

        # Estrategia 2: Buscar secciones por día de la semana
        if not platos:
            for dia in ['lunes', 'martes', 'miércoles', 'jueves', 'viernes']:
                for elem in self.soup.find_all(['div', 'section']):
                    texto_inicio = elem.get_text()[:100].lower()
                    if dia in texto_inicio or dia.replace('é', 'e') in texto_inicio:
                        # Encontrar nombre de receta
                        nombre = ""
                        for h in elem.find_all(['h2', 'h3', 'h4']):
                            h_texto = h.get_text(strip=True)
                            if len(h_texto) > 5 and dia not in h_texto.lower():
                                nombre = h_texto
                                break

                        if not nombre:
                            nombre = f"Receta del {dia.capitalize()}"

                        # Extraer ingredientes
                        ingredientes = []
                        for label in elem.find_all('label'):
                            ing = label.get_text(strip=True)
                            ing = re.sub(r'^[\[\]✓\s]+', '', ing).strip()
                            if ing and len(ing) > 1 and len(ing) < 100:
                                ingredientes.append(ing)

                        if ingredientes:
                            platos.append({
                                'nombre': nombre,
                                'ingredientes': ingredientes,
                                'url_receta': None
                            })
                        break

        # Estrategia 3: Buscar cualquier sección con lista de ingredientes
        if not platos:
            for section in self.soup.find_all(['div', 'section']):
                labels = section.find_all('label')
                if 5 <= len(labels) <= 30:  # Una receta típica tiene entre 5-30 ingredientes
                    # Buscar título
                    titulo = ""
                    for h in section.find_all(['h2', 'h3', 'h4']):
                        titulo = h.get_text(strip=True)
                        if titulo and len(titulo) > 3:
                            break

                    if not titulo:
                        continue

                    ingredientes = []
                    for label in labels:
                        ing = label.get_text(strip=True)
                        ing = re.sub(r'^[\[\]✓\s]+', '', ing).strip()
                        if ing and len(ing) > 1:
                            ingredientes.append(ing)

                    if ingredientes and titulo:
                        # Evitar duplicados
                        if not any(p['nombre'] == titulo for p in platos):
                            platos.append({
                                'nombre': titulo,
                                'ingredientes': ingredientes,
                                'url_receta': None
                            })

        return platos[:10]  # Máximo 10 platos

    def extraer(self) -> bool:
        """Extrae las listas de compras del HTML según el modo seleccionado."""
        if not self.soup:
            print("❌ Primero hay que descargar el HTML")
            return False

        print(f"🔍 Extrayendo listas de compras (modo: {self.modo})...")

        # Si es menú sin lista general, extraer platos
        if not self.tiene_lista_general or self.modo == 'platos':
            self.platos = self._extraer_platos_con_ingredientes()
            if self.platos:
                print(f"   📋 Encontrados {len(self.platos)} platos:")
                for i, plato in enumerate(self.platos, 1):
                    print(f"      {i}. {plato['nombre']} ({len(plato['ingredientes'])} ingredientes)")

                # Si hay platos seleccionados, combinar sus ingredientes
                if self.platos_seleccionados:
                    self.lista_general = self._combinar_ingredientes(self.platos_seleccionados)
                else:
                    # Por defecto combinar todos
                    self.lista_general = self._combinar_ingredientes()

                self.lista_veggie = self.lista_general.copy()
                total = sum(len(cat['items']) for cat in self.lista_general.values())
                print(f"   📋 Lista combinada: {total} items únicos")
                return total > 0

        if self.modo == 'dias':
            # Extraer recetas por día
            self.recetas_por_dia = self._extraer_recetas_por_dia()
            print(f"   📅 Recetas encontradas: {len(self.recetas_por_dia)} días")
            for dia, data in self.recetas_por_dia.items():
                print(f"      {dia}: {data['nombre']} ({len(data['ingredientes'])} ingredientes)")
            return len(self.recetas_por_dia) > 0

        elif self.modo in self.DIAS or self.modo.lower() in self.DIAS:
            # Extraer solo un día específico
            self.recetas_por_dia = self._extraer_recetas_por_dia()
            dia_buscado = self.modo.lower().replace('á', 'a').replace('é', 'e')
            for dia, data in self.recetas_por_dia.items():
                if dia.lower() == dia_buscado or dia.lower().replace('é', 'e') == dia_buscado:
                    self.recetas_por_dia = {dia: data}
                    print(f"   📅 {dia}: {data['nombre']} ({len(data['ingredientes'])} ingredientes)")
                    return True
            print(f"   ⚠️  No se encontró receta para {self.modo}")
            return False

        else:
            # Modo 'general' (por defecto) - solo la lista de compras semanal
            self.lista_general = self._extraer_lista('lista_compra_g')
            self.lista_veggie = self._extraer_lista('lista_compra_v')

            if not self.lista_general:
                self.lista_general = self._extraer_lista_alternativo()

            # Si la lista veggie está vacía pero la general existe,
            # copiar la general como fallback (muchos menús no tienen
            # un contenedor separado para veggie)
            if not self.lista_veggie and self.lista_general:
                self.lista_veggie = {k: {'orden': v['orden'], 'items': list(v['items'])} for k, v in self.lista_general.items()}

            # También extraer recetas por día para permitir selección de días
            self.recetas_por_dia = self._extraer_recetas_por_dia()
            if self.recetas_por_dia:
                print(f"   📅 Recetas por día: {len(self.recetas_por_dia)} días")
                for dia, data in self.recetas_por_dia.items():
                    print(f"      {dia}: {data['nombre']} ({len(data['ingredientes'])} ingredientes)")

            total_general = sum(len(cat['items']) for cat in self.lista_general.values())
            total_veggie = sum(len(cat['items']) for cat in self.lista_veggie.values())

            print(f"   📋 Lista general: {total_general} items en {len(self.lista_general)} categorías")
            print(f"   🥬 Lista veggie: {total_veggie} items en {len(self.lista_veggie)} categorías")

            return total_general > 0

    def generar_json(self) -> dict:
        """Genera el JSON de la lista."""
        def ordenar_categorias(cats):
            return dict(sorted(cats.items(), key=lambda x: x[1].get('orden', 99)))

        resultado = {
            'titulo': self.titulo,
            'fechas': self.fechas,
            'semana': self.semana,
            'modo': self.modo,
            'tiene_lista_general': self.tiene_lista_general,
            'generado': datetime.now().isoformat()
        }

        # Incluir platos si existen (menús especiales)
        if self.platos:
            resultado['platos'] = self.platos
            resultado['platos_seleccionados'] = self.platos_seleccionados

        if self.modo == 'general' or self.modo == 'platos' or (self.modo not in ['dias'] + self.DIAS):
            resultado['general'] = {cat: data['items'] for cat, data in ordenar_categorias(self.lista_general).items()}
            resultado['veggie'] = {cat: data['items'] for cat, data in ordenar_categorias(self.lista_veggie).items()}

        # Incluir recetas por día si están disponibles
        if self.recetas_por_dia:
            recetas = self.recetas_por_dia

            # Filtrar por días seleccionados si aplica
            if self.dias_seleccionados:
                dias_buscar = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
                dias_filtrados = {}
                for idx in self.dias_seleccionados:
                    if 1 <= idx <= len(dias_buscar):
                        dia_nombre = dias_buscar[idx - 1].capitalize()
                        for dia_key, dia_data in recetas.items():
                            dia_normalizado = dia_key.lower().replace('á', 'a').replace('é', 'e')
                            dia_buscado = dias_buscar[idx - 1].replace('á', 'a').replace('é', 'e')
                            if dia_normalizado == dia_buscado:
                                dias_filtrados[dia_key] = dia_data
                                break
                recetas = dias_filtrados

            # Función de normalización de ingredientes (unificada con JS)
            # Constante de normalización
            MAX_NORMALIZED_WORDS = 3
            
            def _norm_ing(text):
                import unicodedata
                n = text.lower().strip()
                # Eliminar cantidades y unidades
                n = re.sub(r'^[\d\s\/½¼¾,.x×]+\s*(?:g|gr|kg|ml|l|lt|lts|litros?|cdas?|cucharadas?|tazas?|unidad(?:es)?|paquetes?|latas?|sobres?)?\s*', '', n, flags=re.I)
                # Eliminar palabras comunes de cantidad al inicio
                n = re.sub(r'^(un|una|uno|dos|tres|cuatro|cinco|medio|media|pizca|chorro|poco|mucho)\s+', '', n, flags=re.I)
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
                # Limitar a palabras significativas (> 1 caracter)
                words = [w for w in n.split() if len(w) > 1]
                return ' '.join(words[:MAX_NORMALIZED_WORDS])

            # Categorizar ingredientes de cada día usando la lista general como referencia
            def _build_mappings(lista):
                """Construye índice categoría y mapeo reverso item→días para una lista."""
                if not lista:
                    return {}, {}

                # Índice: norm → categoría
                ing_a_cat = {}
                # Índice reverso: norm → [item texts originales de la lista general]
                norm_to_items = {}

                for cat_name, cat_data in lista.items():
                    for item in cat_data.get('items', []):
                        norm = _norm_ing(item)
                        if norm:
                            if norm not in ing_a_cat:
                                ing_a_cat[norm] = cat_name
                            if norm not in norm_to_items:
                                norm_to_items[norm] = []
                            norm_to_items[norm].append(item)

                # Función de matching fuzzy para ingredientes
                def _fuzzy_match(norm_ing):
                    """Busca match parcial si no hay match exacto."""
                    if norm_ing in norm_to_items:
                        return norm_to_items[norm_ing]
                    
                    # Buscar si el ingrediente normalizado está contenido en alguna key
                    for key, items in norm_to_items.items():
                        if norm_ing in key or key in norm_ing:
                            return items
                    
                    # Buscar por palabras compartidas (al menos 2)
                    ing_words = set(norm_ing.split())
                    if len(ing_words) >= 2:
                        for key, items in norm_to_items.items():
                            key_words = set(key.split())
                            common = ing_words & key_words
                            if len(common) >= 2:
                                return items
                    
                    return None

                # Categorizar ingredientes por día
                for dia_key in recetas:
                    ingredientes = recetas[dia_key].get('ingredientes', [])
                    por_categoria = {}
                    for ing in ingredientes:
                        norm = _norm_ing(ing)
                        cat = ing_a_cat.get(norm, 'Supermercado 🏪')
                        if cat not in por_categoria:
                            por_categoria[cat] = []
                        por_categoria[cat].append(ing)
                    recetas[dia_key]['ingredientes_por_categoria'] = por_categoria

                # Construir item_to_days: item texto original de lista → [días que lo usan]
                item_to_days = {}
                matched_count = 0
                fuzzy_matched_count = 0
                total_ingredients = 0
                
                for dia_key in recetas:
                    ingredientes = recetas[dia_key].get('ingredientes', [])
                    for ing in ingredientes:
                        total_ingredients += 1
                        norm = _norm_ing(ing)
                        
                        # Intentar match exacto primero
                        matched_items = norm_to_items.get(norm)
                        if matched_items:
                            matched_count += 1
                        else:
                            # Intentar fuzzy match
                            matched_items = _fuzzy_match(norm)
                            if matched_items:
                                fuzzy_matched_count += 1
                        
                        if matched_items:
                            for general_item in matched_items:
                                if general_item not in item_to_days:
                                    item_to_days[general_item] = []
                                if dia_key not in item_to_days[general_item]:
                                    item_to_days[general_item].append(dia_key)

                # Log de estadísticas de matching
                if total_ingredients > 0:
                    exact_pct = (matched_count / total_ingredients) * 100
                    fuzzy_pct = (fuzzy_matched_count / total_ingredients) * 100
                    unmapped_pct = ((total_ingredients - matched_count - fuzzy_matched_count) / total_ingredients) * 100
                    logger.info(f"Matching stats: {matched_count} exactos ({exact_pct:.1f}%), {fuzzy_matched_count} fuzzy ({fuzzy_pct:.1f}%), {total_ingredients - matched_count - fuzzy_matched_count} sin mapear ({unmapped_pct:.1f}%)")

                return ing_a_cat, item_to_days

            if self.lista_general:
                _, item_to_days = _build_mappings(self.lista_general)
                resultado['item_to_days'] = item_to_days

            if self.lista_veggie and self.lista_veggie != self.lista_general:
                _, item_to_days_veggie = _build_mappings(self.lista_veggie)
                resultado['item_to_days_veggie'] = item_to_days_veggie

            resultado['recetas'] = recetas

        return resultado


class FirebaseUploader:
    """Sube los datos a Firebase Firestore."""

    def __init__(self, credentials_path: str = 'firebase_credentials.json'):
        self.db = None
        self.credentials_path = credentials_path

        try:
            import firebase_admin
            from firebase_admin import credentials, firestore

            if not os.path.exists(credentials_path):
                print(f"⚠️  Archivo de credenciales no encontrado: {credentials_path}")
                print("   Descargalo desde Firebase Console > Project Settings > Service Accounts")
                return

            cred = credentials.Certificate(credentials_path)

            # Verificar si ya está inicializado
            try:
                firebase_admin.get_app()
            except ValueError:
                firebase_admin.initialize_app(cred)

            self.db = firestore.client()
            print("✅ Firebase Admin SDK inicializado")

        except ImportError:
            print("📦 Instalando firebase-admin...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "firebase-admin", "-q"])
            print("   Reiniciá el script para usar Firebase")

        except Exception as e:
            print(f"⚠️  Error inicializando Firebase: {e}")

    def upload(self, semana: int, data: dict) -> bool:
        """Sube los datos de una semana a Firestore."""
        if not self.db:
            print("❌ Firebase no está inicializado")
            return False

        try:
            doc_ref = self.db.collection('paulina_menus').document(f'semana_{semana}')
            doc_ref.set({
                **data,
                'uploadedAt': datetime.now().isoformat()
            })
            print(f"✅ Semana {semana} subida a Firebase")
            return True

        except Exception as e:
            print(f"❌ Error subiendo a Firebase: {e}")
            return False
 
    def upload_especial(self, slug: str, data: dict) -> bool:
        """Sube un menú especial a Firestore con ID basado en slug."""
        if not self.db:
            print("❌ Firebase no está inicializado")
            return False

        try:
            doc_id = f'especial_{slug}'
            doc_ref = self.db.collection('paulina_menus').document(doc_id)
            doc_ref.set({
                **data,
                'uploadedAt': datetime.now().isoformat()
            })
            print(f"✅ Menú especial '{slug}' subido a Firebase")
            return True

        except Exception as e:
            print(f"❌ Error subiendo menú especial a Firebase: {e}")
            return False

    def backup_menus(self, output_path: str = 'backup_menus.json') -> bool:
        """Hace backup de todos los menús existentes en Firebase antes de resetear."""
        if not self.db:
            print("❌ Firebase no está inicializado")
            return False

        try:
            snapshot = self.db.collection('paulina_menus').get()
            backup = {}
            for doc in snapshot:
                backup[doc.id] = doc.to_dict()

            if not backup:
                print("📭 No hay menús en Firebase para respaldar")
                return True

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(backup, f, ensure_ascii=False, indent=2, default=str)

            print(f"💾 Backup guardado: {output_path} ({len(backup)} menús)")
            return True

        except Exception as e:
            print(f"❌ Error haciendo backup: {e}")
            return False

    def delete_all_menus(self) -> bool:
        """Elimina todos los documentos de la colección paulina_menus."""
        if not self.db:
            print("❌ Firebase no está inicializado")
            return False

        try:
            snapshot = self.db.collection('paulina_menus').get()
            count = 0
            for doc in snapshot:
                doc.reference.delete()
                count += 1

            print(f"🗑️  {count} menús eliminados de Firebase")
            return True

        except Exception as e:
            print(f"❌ Error eliminando menús: {e}")
            return False

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='🍳 Descarga el menú semanal de Paulina Cocina',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Ejemplos básicos:
  python paulina_scraper.py                    # Descarga la semana más reciente
  python paulina_scraper.py --semana 4         # Descarga semana 4
  python paulina_scraper.py --listar           # Lista semanas disponibles
  python paulina_scraper.py --menus            # Lista TODOS los menús activos (incluye especiales)

Menús especiales:
  python paulina_scraper.py --url URL          # Descarga menú desde URL específica

Descarga masiva:
  python paulina_scraper.py --todas            # Todas las semanas disponibles
  python paulina_scraper.py --rango 3-5        # Semanas 3, 4 y 5

Reset de base de datos:
  python paulina_scraper.py --reset-db         # Backup + borrar + re-descargar todos

Nota: El scraper descarga TODOS los datos disponibles (lista completa + recetas de cada día).
      El filtrado por días se hace en la interfaz web al importar.

Autenticación:
  python paulina_scraper.py --user EMAIL --password PASS
  PAULINA_USER=email PAULINA_PASS=pass python paulina_scraper.py
'''
    )
    parser.add_argument('--semana', '-s', type=int, help='Número de semana específico')
    parser.add_argument('--url', '-u', type=str, help='URL directa del menú (para menús especiales)')
    parser.add_argument('--modo', '-m', default='general',
                       help='[LEGACY] Modo de extracción (siempre usa "general" - el filtrado se hace en la UI)')
    parser.add_argument('--platos', '-p', type=str,
                       help='[AVANZADO] Platos a incluir: "1,2,3" o "todos" (solo para desarrollo)')
    parser.add_argument('--dias', '-d', type=str,
                       help='[LEGACY] Días a incluir (deprecado - usar filtrado en la UI)')
    parser.add_argument('--listar', '-l', action='store_true', help='Listar semanas disponibles (patrón menu-semana-N)')
    parser.add_argument('--menus', action='store_true', help='Listar TODOS los menús activos (incluye especiales)')
    parser.add_argument('--todas', '-t', action='store_true', help='Descargar todas las semanas disponibles')
    parser.add_argument('--rango', '-r', type=str, help='Rango de semanas (ej: 3-5)')
    parser.add_argument('--output', '-o', default='./menu_semana.json', help='Archivo JSON de salida')
    parser.add_argument('--especiales', '-e', action='store_true', help='Descubrir y descargar todos los menús especiales activos')
    parser.add_argument('--local', action='store_true', help='Solo guardar localmente, no subir a Firebase')
    parser.add_argument('--credentials', '-c', default='firebase_credentials.json', help='Archivo de credenciales Firebase')
    parser.add_argument('--reset-db', action='store_true',
                       help='Resetear base de datos: backup + borrar menús + re-descargar todos los activos')
    parser.add_argument('--user', type=str, help='Email/usuario de almacen.paulinacocina.net (o env PAULINA_USER)')
    parser.add_argument('--password', type=str, help='Contraseña de almacen.paulinacocina.net (o env PAULINA_PASS)')

    args = parser.parse_args()

    print("🍳 Paulina Cocina - Scraper de Lista de Compras")
    print("=" * 50)

    # Inicializar sesión autenticada
    get_session(args.user, args.password)

    # Modo: listar todos los menús activos
    if args.menus:
        menus = MenuDiscoverer.descubrir_menus()
        if menus:
            print(f"\n📋 Menús activos encontrados ({len(menus)}):\n")
            for i, menu in enumerate(menus, 1):
                tipo_emoji = "🌟" if menu['tipo'] == 'especial' else "📅"
                semana_str = f" (Semana {menu['semana']})" if menu['semana'] else ""
                print(f"   {i}. {tipo_emoji} {menu['titulo']}{semana_str}")
                print(f"      {menu['url']}")
            print(f"\n💡 Usa --url <URL> para descargar un menú específico")
        else:
            print("\n❌ No se encontraron menús activos")
        return 0
    
    # Modo reset-db: backup + borrar + re-descargar todos
    if args.reset_db:
        print("\n🔄 RESET DE BASE DE DATOS")
        print("=" * 50)

        uploader = FirebaseUploader(args.credentials)
        if not uploader.db:
            print("❌ No se pudo conectar a Firebase. Abortando reset.")
            return 1

        # 1. Backup
        print("\n📦 Paso 1: Backup de datos existentes...")
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = f'backup_menus_{timestamp}.json'
        uploader.backup_menus(backup_path)

        # 2. Borrar todo
        print("\n🗑️  Paso 2: Borrando menús existentes...")
        uploader.delete_all_menus()

        # 3. Descubrir y re-descargar todos los menús activos
        print("\n🔍 Paso 3: Descubriendo menús activos...")
        menus = MenuDiscoverer.descubrir_menus()

        if not menus:
            print("⚠️  No se encontraron menús activos. La base queda vacía.")
            return 0

        menus_semanales = [m for m in menus if m['tipo'] == 'semanal' and m['semana']]
        menus_especiales = [m for m in menus if m['tipo'] == 'especial']

        print(f"\n📋 Encontrados:")
        print(f"   📅 {len(menus_semanales)} menús semanales")
        print(f"   🌟 {len(menus_especiales)} menús especiales")

        exitosas = 0

        # Procesar menús semanales
        for menu in menus_semanales:
            print(f"\n{'='*50}")
            print(f"📅 Semana {menu['semana']}: {menu['titulo']}")
            extractor = PaulinaExtractor(semana=menu['semana'], modo='general')

            if not extractor.descargar():
                print(f"⚠️  No se pudo descargar: {menu['titulo']}")
                continue

            if not extractor.extraer():
                print(f"⚠️  No se pudo extraer: {menu['titulo']}")
                continue

            datos = extractor.generar_json()
            uploader.upload(extractor.semana, datos)
            exitosas += 1

        # Procesar menús especiales
        for menu in menus_especiales:
            print(f"\n{'='*50}")
            print(f"🌟 {menu['titulo']}")
            extractor = PaulinaExtractor(url=menu['url'], modo='general')

            if not extractor.descargar():
                print(f"⚠️  No se pudo descargar: {menu['titulo']}")
                continue

            if not extractor.extraer():
                print(f"⚠️  No se pudo extraer: {menu['titulo']}")
                continue

            datos = extractor.generar_json()
            if extractor.semana:
                uploader.upload(extractor.semana, datos)
            else:
                slug = re.sub(r'[^\w]+', '_', extractor.titulo.lower()).strip('_')[:40]
                uploader.upload_especial(slug, datos)
            exitosas += 1

        total = len(menus_semanales) + len(menus_especiales)
        print(f"\n{'='*50}")
        print(f"✨ Reset completo: {exitosas}/{total} menús cargados")
        print(f"💾 Backup guardado en: {backup_path}")
        return 0 if exitosas > 0 else 1

    # Modo especiales: descargar todos los menús especiales activos
    if args.especiales:
        menus = MenuDiscoverer.descubrir_menus()
        especiales = [menu for menu in menus if menu['tipo'] == 'especial']
        
        if not especiales:
            print("\n❌ No se encontraron menús especiales activos")
            return 1
        
        print(f"\n🌟 Procesando {len(especiales)} menús especiales...")
        uploader = None
        if not args.local:
            uploader = FirebaseUploader(args.credentials)
 
        exitosas_esp = 0
        for menu in especiales:
            print(f"\n{'='*50}")
            print(f"🌟 {menu['titulo']}")
            extractor = PaulinaExtractor(url=menu['url'], modo='general')
 
            if not extractor.descargar():
                print(f"⚠️  No se pudo descargar: {menu['titulo']}")
                continue
 
            if not extractor.extraer():
                print(f"⚠️  No se pudo extraer: {menu['titulo']}")
                continue
 
            datos = extractor.generar_json()
 
            # Guardar JSON local
            titulo_safe = re.sub(r'[^\w\-]', '_', extractor.titulo[:30])
            output_path = args.output.replace('.json', f'_{titulo_safe}.json')
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
            print(f"📄 JSON guardado: {output_path}")
 
            # Subir a Firebase
            if uploader and uploader.db:
                if extractor.semana:
                    uploader.upload(extractor.semana, datos)
                else:
                    slug = re.sub(r'[^\w]+', '_', extractor.titulo.lower()).strip('_')[:40]
                    uploader.upload_especial(slug, datos)
 
            exitosas_esp += 1
 
        print(f"\n{'='*50}")
        print(f"✨ {exitosas_esp}/{len(especiales)} menús especiales procesados")
        return 0 if exitosas_esp > 0 else 1
 
    # Modo listar: solo mostrar semanas disponibles (patrón viejo)
    if args.listar:
        semanas = PaulinaExtractor.listar_semanas_disponibles()
        if semanas:
            print(f"\n✅ Semanas disponibles: {', '.join(map(str, semanas))}")
            print(f"   Total: {len(semanas)} semanas")
            print(f"\n💡 Usa --menus para ver también menús especiales")
        else:
            print("\n❌ No se encontraron semanas disponibles")
        return 0

    # Parsear platos seleccionados
    platos_seleccionados = None
    if args.platos:
        if args.platos.lower() == 'todos':
            platos_seleccionados = None  # None = todos
        else:
            try:
                platos_seleccionados = [int(x.strip()) for x in args.platos.split(',')]
                print(f"📋 Platos seleccionados: {platos_seleccionados}")
            except ValueError:
                print("❌ Formato de platos inválido. Usa: --platos 1,2,3 o --platos todos")
                return 1

    # Parsear días seleccionados
    dias_seleccionados = None
    if args.dias:
        if args.dias.lower() == 'todos':
            dias_seleccionados = None  # None = todos
        else:
            try:
                dias_seleccionados = [int(x.strip()) for x in args.dias.split(',')]
                print(f"📅 Días seleccionados: {dias_seleccionados}")
            except ValueError:
                print("❌ Formato de días inválido. Usa: --dias 1,2,3 o --dias todos")
                return 1

    # Modo URL directa
    if args.url:
        print(f"\n{'='*50}")
        modo = 'platos' if args.platos else args.modo
        extractor = PaulinaExtractor(url=args.url, modo=modo)

        if platos_seleccionados:
            extractor.set_platos_seleccionados(platos_seleccionados)
        if dias_seleccionados:
            extractor.set_dias_seleccionados(dias_seleccionados)

        if not extractor.descargar():
            print(f"⚠️  No se pudo descargar el menú")
            return 1

        if not extractor.extraer():
            print(f"⚠️  No se pudo extraer la lista del menú")
            return 1

        datos = extractor.generar_json()

        # Guardar JSON local
        titulo_safe = re.sub(r'[^\w\-]', '_', extractor.titulo[:30])
        output_path = args.output.replace('.json', f'_{titulo_safe}.json')
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
        print(f"📄 JSON guardado: {output_path}")

        # Subir a Firebase
        if not args.local:
            uploader = FirebaseUploader(args.credentials)
            if uploader and uploader.db:
                if extractor.semana:
                    uploader.upload(extractor.semana, datos)
                else:
                    # Menú especial sin número de semana: usar slug del título
                    slug = re.sub(r'[^\w]+', '_', extractor.titulo.lower()).strip('_')[:40]
                    uploader.upload_especial(slug, datos)

        print(f"\n✅ {datos['titulo']}")
        if datos.get('fechas'):
            print(f"   📅 {datos['fechas']}")
        if 'general' in datos:
            total = sum(len(items) for items in datos['general'].values())
            print(f"   📋 {total} items extraídos")
        if datos.get('platos'):
            print(f"   🍽️  {len(datos['platos'])} platos disponibles")

        return 0

    # Determinar qué semanas procesar
    semanas_a_procesar = []
    menus_a_procesar = []  # Para menús especiales y semanales descubiertos

    if args.todas:
        # Usar MenuDiscoverer para encontrar TODOS los menús disponibles en tiempo real
        print("\n🔍 Descubriendo todos los menús disponibles...")
        menus = MenuDiscoverer.descubrir_menus()
        
        if menus:
            # Separar menús semanales y especiales
            menus_semanales = [m for m in menus if m['tipo'] == 'semanal' and m['semana']]
            menus_especiales = [m for m in menus if m['tipo'] == 'especial']
            
            # Procesar menús semanales
            semanas_a_procesar = sorted(list(set([m['semana'] for m in menus_semanales])), reverse=True)
            
            # Guardar menús especiales para procesar después
            menus_a_procesar = menus_especiales
            
            print(f"\n📋 Encontrados:")
            print(f"   📅 {len(semanas_a_procesar)} menús semanales: {', '.join(map(str, semanas_a_procesar))}")
            print(f"   🌟 {len(menus_especiales)} menús especiales")
        else:
            print("\n⚠️  No se encontraron menús usando MenuDiscoverer, intentando método clásico...")
            # Fallback al método antiguo si MenuDiscoverer falla
            semanas_a_procesar = PaulinaExtractor.listar_semanas_disponibles()
            if semanas_a_procesar:
                print(f"\n📋 Procesando {len(semanas_a_procesar)} semanas: {', '.join(map(str, semanas_a_procesar))}")
    elif args.rango:
        try:
            inicio, fin = map(int, args.rango.split('-'))
            semanas_a_procesar = list(range(inicio, fin + 1))
            print(f"\n📋 Procesando rango de semanas: {inicio} a {fin}")
        except:
            print("❌ Formato de rango inválido. Usa: --rango 3-5")
            return 1
    elif args.semana:
        semanas_a_procesar = [args.semana]
    else:
        semanas_a_procesar = [None]  # None = detectar automáticamente

    # Procesar cada semana
    uploader = None
    if not args.local:
        uploader = FirebaseUploader(args.credentials)

    exitosas = 0
    exitosas_especiales = 0  # Para menús especiales cuando se usa --todas
    for semana in semanas_a_procesar:
        print(f"\n{'='*50}")
        extractor = PaulinaExtractor(semana, modo=args.modo)

        if dias_seleccionados:
            extractor.set_dias_seleccionados(dias_seleccionados)

        # Descargar
        if not extractor.descargar():
            print(f"⚠️  No se pudo descargar semana {semana}")
            continue

        # Extraer
        if not extractor.extraer():
            print(f"⚠️  No se pudo extraer la lista de semana {semana}")
            continue

        # Generar datos
        datos = extractor.generar_json()

        # Guardar JSON local
        suffix = f'_s{extractor.semana}' if extractor.semana else ''
        if args.modo != 'general':
            suffix += f'_{args.modo}'
        output_path = args.output.replace('.json', f'{suffix}.json')
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
        print(f"📄 JSON guardado: {output_path}")

        # Subir a Firebase (solo modo general)
        if uploader and uploader.db and args.modo == 'general' and extractor.semana:
            uploader.upload(extractor.semana, datos)

        exitosas += 1
        print(f"✅ Semana {extractor.semana}: {datos['titulo']}")
        if datos.get('fechas'):
            print(f"   📅 {datos['fechas']}")

        # Mostrar resumen según modo
        if 'general' in datos:
            total_general = sum(len(items) for items in datos['general'].values())
            total_veggie = sum(len(items) for items in datos.get('veggie', {}).values())
            print(f"   General: {total_general} items | Veggie: {total_veggie} items")
        elif 'recetas' in datos:
            for dia, receta in datos['recetas'].items():
                print(f"   {dia}: {receta['nombre']} ({len(receta['ingredientes'])} ingredientes)")

    # Procesar menús especiales si hay alguno (cuando se usa --todas)
    if menus_a_procesar:
        print(f"\n{'='*50}")
        print(f"🌟 Procesando {len(menus_a_procesar)} menús especiales...")
        
        for menu in menus_a_procesar:
            print(f"\n{'='*50}")
            print(f"🌟 {menu['titulo']}")
            
            extractor = PaulinaExtractor(url=menu['url'], modo=args.modo)
            
            if dias_seleccionados:
                extractor.set_dias_seleccionados(dias_seleccionados)

            if not extractor.descargar():
                print(f"⚠️  No se pudo descargar: {menu['titulo']}")
                continue
            
            if not extractor.extraer():
                print(f"⚠️  No se pudo extraer: {menu['titulo']}")
                continue
            
            datos = extractor.generar_json()
            
            # Guardar JSON local
            titulo_safe = re.sub(r'[^\w\-]', '_', extractor.titulo[:30])
            output_path = args.output.replace('.json', f'_{titulo_safe}.json')
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
            print(f"📄 JSON guardado: {output_path}")
            
            # Subir a Firebase
            if uploader and uploader.db:
                if extractor.semana:
                    uploader.upload(extractor.semana, datos)
                else:
                    # Menú especial sin número de semana: usar slug del título
                    slug = re.sub(r'[^\w]+', '_', extractor.titulo.lower()).strip('_')[:40]
                    uploader.upload_especial(slug, datos)
            
            exitosas_especiales += 1
            print(f"✅ {datos['titulo']}")
            if datos.get('fechas'):
                print(f"   📅 {datos['fechas']}")
            if 'general' in datos:
                total = sum(len(items) for items in datos['general'].values())
                print(f"   📋 {total} items extraídos")
            if datos.get('platos'):
                print(f"   🍽️  {len(datos['platos'])} platos disponibles")

    # Resumen final
    print(f"\n{'='*50}")
    total_procesados = exitosas + exitosas_especiales
    print(f"✨ ¡Listo! {exitosas}/{len(semanas_a_procesar)} semanas procesadas", end="")
    if menus_a_procesar:
        print(f" + {exitosas_especiales}/{len(menus_a_procesar)} menús especiales")
    else:
        print()

    if not args.local and (not uploader or not uploader.db):
        print("\n💡 Para subir a Firebase, creá el archivo de credenciales.")
        print("   Ver SETUP_FIREBASE.md para instrucciones.")

    return 0 if (exitosas > 0 or exitosas_especiales > 0) else 1


if __name__ == '__main__':
    sys.exit(main())

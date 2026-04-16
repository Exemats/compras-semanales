#!/usr/bin/env python3
"""
build_menus_db.py — Actualiza data/menus_database.json
=======================================================
Este script se ejecuta cada miércoles por GitHub Actions.

Flujo:
  1. Descarga el menú semanal vigente desde almacen.paulinacocina.net
     (autenticado con PAULINA_USER / PAULINA_PASS del entorno)
  2. Parsea el HTML para extraer recetas, ingredientes e instrucciones
  3. Merge inteligente: si la semana ya está en menus_database.json la reemplaza,
     si es nueva la agrega
  4. Escribe data/menus_database.json actualizado

Uso:
    python scripts/build_menus_db.py                   # descarga menú actual
    python scripts/build_menus_db.py --url URL         # URL específica
    python scripts/build_menus_db.py --rebuild-all     # re-parsea todos los HTMLs en data/html/
    python scripts/build_menus_db.py --dry-run         # imprime sin escribir
"""

import os
import re
import json
import sys
import logging
import argparse
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# ── Dependencias ──────────────────────────────────────────────────────────────
try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, '-m', 'pip', 'install',
                           'requests', 'beautifulsoup4', '-q'])
    import requests
    from bs4 import BeautifulSoup

# ── Rutas ─────────────────────────────────────────────────────────────────────
REPO_ROOT  = Path(__file__).parent.parent
DATA_DIR   = REPO_ROOT / 'data'
HTML_CACHE = DATA_DIR / 'html'
DB_FILE    = DATA_DIR / 'menus_database.json'

DATA_DIR.mkdir(exist_ok=True)
HTML_CACHE.mkdir(exist_ok=True)

# ── Constantes de parseo ──────────────────────────────────────────────────────
DAYS_ES = ['LUNES', 'MARTES', 'MIÉRCOLES', 'MIERCOLES', 'JUEVES', 'VIERNES']
DAYS_NORM = {
    'LUNES': 'Lunes', 'MARTES': 'Martes', 'MIÉRCOLES': 'Miércoles',
    'MIERCOLES': 'Miércoles', 'JUEVES': 'Jueves', 'VIERNES': 'Viernes',
}
PLATO_NUM_RE = re.compile(r'^PLATO\s*#\s*(\d+)$', re.IGNORECASE)
SKIP_KEYWORDS = ['almacén', 'paulina cocina', 'menú semanal', 'es el medio',
                 'la yapa', 'receta comodín', 'receta comodin', '¿más ganas']


# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize_day(text):
    t = text.strip().upper().replace('É', 'E').replace('Ó', 'O')
    for d in DAYS_ES:
        if t == d or t == d.replace('É', 'E'):
            return DAYS_NORM.get(d, d)
    m = PLATO_NUM_RE.match(text.strip().upper())
    if m:
        return f"Plato #{m.group(1)}"
    return None


def is_category(text):
    t = text.strip().upper()
    return any(k in t for k in ['PLATO', 'GUARNICIÓN', 'GUARNICION', 'PRINCIPAL'])


def clean_item(text):
    skip = {'seleccionar todo', 'descargar pdf', 'enviar whatsapp', 'seleccionar', 'pdf', 'whatsapp'}
    t = text.strip()
    return None if not t or t.lower() in skip else t


# ── Parseo del HTML ───────────────────────────────────────────────────────────

def extract_shopping(soup):
    """Extrae listas general y veggie del HTML."""
    result = {'general': {}, 'veggie': {}}
    for detail in soup.find_all('details', class_='e-n-accordion-item'):
        summary = detail.find('summary')
        if not summary:
            continue
        title = summary.get_text(strip=True).lower()
        if not ('lista' in title and ('general' in title or 'vegetarian' in title)):
            continue
        key = 'veggie' if 'vegetarian' in title else 'general'
        content = summary.find_next_sibling()
        if not content:
            continue
        cats, cur = {}, 'General'
        for el in content.descendants:
            if el.name == 'strong':
                c = el.get_text(strip=True)
                if c and len(c) > 2:
                    cur = c
                    cats.setdefault(cur, [])
            elif el.name == 'label':
                txt = ''.join(
                    ch.get_text(strip=True) if hasattr(ch, 'get_text') else str(ch)
                    for ch in el.children
                    if not (hasattr(ch, 'name') and ch.name == 'input')
                ).strip()
                item = clean_item(txt)
                if item:
                    cats.setdefault(cur, []).append(item)
        result[key] = cats
    return result


def extract_accordion(container):
    """Extrae ingredientes e instrucciones del bloque de acordeón de una receta."""
    ingredientes, instrucciones = [], ''
    for detail in container.find_all('details', class_='e-n-accordion-item'):
        summary = detail.find('summary')
        if not summary:
            continue
        title = summary.get_text(strip=True).lower()
        content = summary.find_next_sibling()
        if not content:
            continue
        if 'ingrediente' in title:
            for el in content.descendants:
                if el.name == 'label':
                    txt = ''.join(
                        ch.get_text(strip=True) if hasattr(ch, 'get_text') else str(ch)
                        for ch in el.children
                        if not (hasattr(ch, 'name') and ch.name == 'input')
                    ).strip()
                    item = clean_item(txt)
                    if item:
                        ingredientes.append(item)
        elif 'instruccion' in title or 'instrucción' in title:
            instrucciones = content.get_text(separator='\n', strip=True)
    return ingredientes, instrucciones


def find_recipe_container(h2):
    c = h2
    for _ in range(6):
        c = c.parent
        if c.find('details', class_='e-n-accordion-item'):
            return c
    return None


def parse_html(html_content, source_name=''):
    """Parsea el contenido HTML de un menú y retorna el dict del menú."""
    soup = BeautifulSoup(html_content, 'html.parser')

    # Metadata
    title_tag = soup.find('title')
    titulo = (title_tag.get_text(strip=True).split(' - ')[0].strip()
              if title_tag else source_name)
    sem_m = re.search(r'semana\s+(\d+)', titulo, re.IGNORECASE)
    semana = int(sem_m.group(1)) if sem_m else 0
    meta = soup.find('meta', {'name': 'description'})
    fechas = meta.get('content', '').strip() if meta else ''
    if not fechas:
        h2s = soup.find_all('h2')
        if len(h2s) > 1:
            fechas = h2s[1].get_text(strip=True)
    is_especial = 'especial' in titulo.lower() or 'vianda' in titulo.lower()

    # Listas de compras
    shopping = extract_shopping(soup)

    # Recetas por día
    dias = {}
    current_day = current_cat = None
    for h2 in soup.find_all('h2'):
        text = h2.get_text(strip=True)
        day = normalize_day(text)
        if day:
            current_day, current_cat = day, None
            dias.setdefault(current_day, [])
            continue
        if is_category(text) and current_day:
            current_cat = text
            continue
        if current_day and current_cat:
            if any(k.lower() in text.lower() for k in SKIP_KEYWORDS):
                continue
            container = find_recipe_container(h2)
            prep_time = porciones = ''
            if container:
                for h4 in container.find_all('h4'):
                    h4t = h4.get_text(strip=True).lower()
                    if 'preparaci' in h4t:
                        mm = re.search(r'(\d+)\s*min',
                                       h4.parent.get_text(separator=' ', strip=True), re.I)
                        if mm:
                            prep_time = f"{mm.group(1)} min."
                    elif 'porcion' in h4t:
                        mm = re.search(r'Porciones\s*(\d+)',
                                       h4.parent.get_text(strip=True), re.I)
                        if mm:
                            porciones = mm.group(1)
            ings, instrs = extract_accordion(container) if container else ([], '')
            cat_low = current_cat.lower()
            dias[current_day].append({
                'nombre': text,
                'categoria': current_cat,
                'es_vegetariano': 'vegetar' in cat_low,
                'es_guarnicion': 'guarnición' in cat_low or 'guarnicion' in cat_low,
                'preparacion_tiempo': prep_time,
                'porciones': porciones,
                'ingredientes': ings,
                'instrucciones': instrs,
            })

    # Recetas por día (formato para filtrado en la app)
    recetas = {}
    for day, rlist in dias.items():
        all_ings = [i for r in rlist for i in r['ingredientes']
                    if i and not i.endswith(':') and len(i) > 2]
        if all_ings:
            recetas[day] = {
                'ingredientes': all_ings,
                'nombre': ', '.join(r['nombre'] for r in rlist),
            }

    total_g = sum(len(v) for v in shopping['general'].values())
    total_r = sum(len(v) for v in dias.values())
    logger.info(f"  ✅ S{semana} | {fechas} | {total_r} recetas | {total_g} items shopping")

    return {
        'titulo': titulo,
        'semana': semana,
        'fechas': fechas,
        'es_especial': is_especial,
        'generado': datetime.now().isoformat(),
        'general': shopping['general'],
        'veggie': shopping['veggie'],
        'recetas': recetas,
        'dias': dias,
    }


# ── Descarga autenticada ───────────────────────────────────────────────────────

def get_session():
    """Crea sesión autenticada con almacen.paulinacocina.net."""
    user = os.environ.get('PAULINA_USER', '')
    pwd  = os.environ.get('PAULINA_PASS', '')
    if not user or not pwd:
        logger.warning('PAULINA_USER / PAULINA_PASS no configurados')
        return None

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'es-ES,es;q=0.9',
    })
    try:
        login_url = 'https://almacen.paulinacocina.net/wp-login.php'
        session.get(login_url, timeout=15)
        resp = session.post(login_url, data={
            'log': user, 'pwd': pwd,
            'wp-submit': 'Acceder',
            'redirect_to': 'https://almacen.paulinacocina.net/menu-semanal/',
            'testcookie': '1',
        }, timeout=15, allow_redirects=True)
        if 'wp-login.php' in resp.url and 'login_error' in resp.text:
            logger.error('Login fallido: credenciales incorrectas')
            return None
        logger.info('✅ Login exitoso')
        return session
    except Exception as e:
        logger.error(f'Error en login: {e}')
        return None


def discover_active_menus(session):
    """Descubre las URLs de menús activos en la página principal."""
    try:
        resp = session.get('https://almacen.paulinacocina.net/menu-semanal/', timeout=30)
        soup = BeautifulSoup(resp.text, 'html.parser')
        urls = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if re.search(r'/menu[-/]semana[-/]?\d+', href, re.I) or \
               re.search(r'/menu/menu-semana', href, re.I):
                if href not in urls:
                    urls.append(href)
        logger.info(f'  Menús activos encontrados: {len(urls)}')
        return urls
    except Exception as e:
        logger.error(f'Error descubriendo menús: {e}')
        return []


def download_menu(session, url):
    """Descarga el HTML de un menú y lo guarda en cache."""
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        # Cache HTML
        slug = re.sub(r'[^\w-]', '_', url.split('/')[-2] or url.split('/')[-1])
        cache_file = HTML_CACHE / f"{slug}.html"
        cache_file.write_text(resp.text, encoding='utf-8')
        logger.info(f'  📥 Descargado: {url} → {cache_file.name}')
        return resp.text
    except Exception as e:
        logger.error(f'Error descargando {url}: {e}')
        return None


# ── Base de datos ──────────────────────────────────────────────────────────────

def load_db():
    """Carga menus_database.json existente o retorna estructura vacía."""
    if DB_FILE.exists():
        with open(DB_FILE, encoding='utf-8') as f:
            return json.load(f)
    return {'version': '2.0', 'total_semanas': 0, 'generado': '', 'menus': []}


def save_db(db):
    """Guarda menus_database.json."""
    db['generado'] = datetime.now().isoformat()
    db['total_semanas'] = len(db['menus'])
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    logger.info(f'💾 {DB_FILE} guardado ({db["total_semanas"]} menús)')


def merge_menu(db, new_menu):
    """Agrega o reemplaza un menú en la DB por número de semana."""
    menus = db['menus']
    for i, m in enumerate(menus):
        if m['semana'] == new_menu['semana'] and m['semana'] > 0:
            menus[i] = new_menu
            logger.info(f'  🔄 Semana {new_menu["semana"]} actualizada')
            return
    menus.append(new_menu)
    menus.sort(key=lambda x: x['semana'])
    logger.info(f'  ➕ Semana {new_menu["semana"]} agregada')


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Actualiza menus_database.json')
    parser.add_argument('--url', help='URL específica a descargar')
    parser.add_argument('--rebuild-all', action='store_true',
                        help='Re-parsea todos los HTMLs en data/html/')
    parser.add_argument('--dry-run', action='store_true',
                        help='No escribe archivos')
    args = parser.parse_args()

    db = load_db()
    updated = 0

    if args.rebuild_all:
        # Re-parsear todos los HTMLs cacheados
        logger.info('🔁 Rebuild all desde cache...')
        db['menus'] = []
        for html_file in sorted(HTML_CACHE.glob('*.html')):
            logger.info(f'  Parseando {html_file.name}...')
            html = html_file.read_text(encoding='utf-8')
            menu = parse_html(html, html_file.stem)
            merge_menu(db, menu)
            updated += 1

    elif args.url:
        # Descargar URL específica
        logger.info(f'📥 Descargando URL: {args.url}')
        session = get_session()
        if not session:
            sys.exit(1)
        html = download_menu(session, args.url)
        if html:
            menu = parse_html(html)
            merge_menu(db, menu)
            updated += 1

    else:
        # Modo normal: descubrir y descargar menús activos
        logger.info('🔍 Descubriendo menús activos...')
        session = get_session()
        if not session:
            logger.error('No se pudo iniciar sesión. '
                         'Configurá PAULINA_USER y PAULINA_PASS.')
            sys.exit(1)

        urls = discover_active_menus(session)
        if not urls:
            logger.warning('No se encontraron menús activos.')
            sys.exit(0)

        for url in urls:
            logger.info(f'  📥 {url}')
            html = download_menu(session, url)
            if html:
                menu = parse_html(html, url)
                merge_menu(db, menu)
                updated += 1

    if updated == 0:
        logger.warning('No se actualizó ningún menú.')
        sys.exit(0)

    if args.dry_run:
        logger.info(f'[dry-run] Se actualizarían {updated} menú(s). No se escribió nada.')
    else:
        save_db(db)
        logger.info(f'✅ {updated} menú(s) actualizado(s). Total en DB: {db["total_semanas"]}')


if __name__ == '__main__':
    main()

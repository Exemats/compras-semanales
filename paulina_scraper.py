#!/usr/bin/env python3
"""
🍳 Paulina Cocina - Scraper de Lista de Compras
================================================
Descarga el menú semanal y lo sube a Firebase para sincronizar con la webapp.

Uso:
    python paulina_scraper.py                    # Descarga el menú actual
    python paulina_scraper.py --semana 5         # Descarga semana específica
    python paulina_scraper.py --local            # Solo guarda JSON local (no sube a Firebase)

Configuración:
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

# Intentar importar dependencias
try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("📦 Instalando dependencias básicas...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "beautifulsoup4", "-q"])
    import requests
    from bs4 import BeautifulSoup


class PaulinaExtractor:
    """Extrae la lista de compras del menú semanal de Paulina Cocina."""

    BASE_URL = "https://almacen.paulinacocina.net/menu-semana-{semana}"

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

    def __init__(self, semana: int = None):
        self.semana = semana
        self.html_content = None
        self.soup = None
        self.titulo = ""
        self.fechas = ""
        self.lista_general = {}
        self.lista_veggie = {}

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
        for semana in range(20, 0, -1):
            url = cls.BASE_URL.format(semana=semana)
            try:
                response = requests.head(url, timeout=5, allow_redirects=True)
                if response.status_code == 200:
                    disponibles.append(semana)
            except:
                continue
        return disponibles

    def descargar(self) -> bool:
        """Descarga el HTML del menú."""
        if self.semana is None:
            self.semana = self.detectar_semana_actual()

        url = self.BASE_URL.format(semana=self.semana)
        print(f"🌐 Descargando: {url}")

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            self.html_content = response.text
            self.soup = BeautifulSoup(self.html_content, 'html.parser')

            title_tag = self.soup.find('title')
            if title_tag:
                self.titulo = title_tag.text.split(' - ')[0].strip()

            meta_desc = self.soup.find('meta', {'name': 'description'})
            if meta_desc and meta_desc.get('content'):
                self.fechas = meta_desc['content']

            print(f"✅ Descargado: {self.titulo}")
            print(f"   {self.fechas}")
            return True

        except requests.RequestException as e:
            print(f"❌ Error descargando: {e}")
            return False

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
        """Método alternativo de extracción."""
        categorias = {}
        labels = self.soup.find_all('label')
        categoria_actual = 'Supermercado 🏪'

        for label in labels:
            texto = label.get_text(strip=True)
            texto = re.sub(r'^[\[\]✓\s]+', '', texto).strip()

            if not texto or len(texto) < 2:
                continue

            cat_detectada, orden = self._detectar_categoria(texto)
            if orden != 99 and len(texto) < 30:
                categoria_actual = cat_detectada
                continue

            if categoria_actual not in categorias:
                categorias[categoria_actual] = {'orden': 1, 'items': []}

            if texto not in categorias[categoria_actual]['items']:
                categorias[categoria_actual]['items'].append(texto)

        return categorias

    def extraer(self) -> bool:
        """Extrae las listas de compras del HTML."""
        if not self.soup:
            print("❌ Primero hay que descargar el HTML")
            return False

        print("🔍 Extrayendo listas de compras...")

        self.lista_general = self._extraer_lista('lista_compra_g')
        self.lista_veggie = self._extraer_lista('lista_compra_v')

        if not self.lista_general:
            self.lista_general = self._extraer_lista_alternativo()
            self.lista_veggie = self.lista_general.copy()

        total_general = sum(len(cat['items']) for cat in self.lista_general.values())
        total_veggie = sum(len(cat['items']) for cat in self.lista_veggie.values())

        print(f"   📋 Lista general: {total_general} items en {len(self.lista_general)} categorías")
        print(f"   🥬 Lista veggie: {total_veggie} items en {len(self.lista_veggie)} categorías")

        return total_general > 0

    def generar_json(self) -> dict:
        """Genera el JSON de la lista."""
        def ordenar_categorias(cats):
            return dict(sorted(cats.items(), key=lambda x: x[1].get('orden', 99)))

        return {
            'titulo': self.titulo,
            'fechas': self.fechas,
            'semana': self.semana,
            'general': {cat: data['items'] for cat, data in ordenar_categorias(self.lista_general).items()},
            'veggie': {cat: data['items'] for cat, data in ordenar_categorias(self.lista_veggie).items()},
            'generado': datetime.now().isoformat()
        }


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


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='🍳 Descarga el menú semanal de Paulina Cocina',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Ejemplos:
  python paulina_scraper.py                    # Descarga la semana más reciente
  python paulina_scraper.py --semana 4         # Descarga semana 4
  python paulina_scraper.py --listar           # Lista semanas disponibles
  python paulina_scraper.py --todas            # Descarga todas las semanas disponibles
  python paulina_scraper.py --rango 3-5        # Descarga semanas 3, 4 y 5
'''
    )
    parser.add_argument('--semana', '-s', type=int, help='Número de semana específico')
    parser.add_argument('--listar', '-l', action='store_true', help='Listar semanas disponibles sin descargar')
    parser.add_argument('--todas', '-t', action='store_true', help='Descargar todas las semanas disponibles')
    parser.add_argument('--rango', '-r', type=str, help='Rango de semanas (ej: 3-5)')
    parser.add_argument('--output', '-o', default='./menu_semana.json', help='Archivo JSON de salida')
    parser.add_argument('--local', action='store_true', help='Solo guardar localmente, no subir a Firebase')
    parser.add_argument('--credentials', '-c', default='firebase_credentials.json', help='Archivo de credenciales Firebase')

    args = parser.parse_args()

    print("🍳 Paulina Cocina - Scraper de Lista de Compras")
    print("=" * 50)

    # Modo listar: solo mostrar semanas disponibles
    if args.listar:
        semanas = PaulinaExtractor.listar_semanas_disponibles()
        if semanas:
            print(f"\n✅ Semanas disponibles: {', '.join(map(str, semanas))}")
            print(f"   Total: {len(semanas)} semanas")
        else:
            print("\n❌ No se encontraron semanas disponibles")
        return 0

    # Determinar qué semanas procesar
    semanas_a_procesar = []

    if args.todas:
        semanas_a_procesar = PaulinaExtractor.listar_semanas_disponibles()
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
    for semana in semanas_a_procesar:
        print(f"\n{'='*50}")
        extractor = PaulinaExtractor(semana)

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
        output_path = args.output.replace('.json', f'_s{extractor.semana}.json')
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
        print(f"📄 JSON guardado: {output_path}")

        # Subir a Firebase
        if uploader and uploader.db:
            uploader.upload(extractor.semana, datos)

        exitosas += 1
        print(f"✅ Semana {extractor.semana}: {datos['titulo']}")

        # Mostrar resumen
        total_general = sum(len(items) for items in datos['general'].values())
        total_veggie = sum(len(items) for items in datos['veggie'].values())
        print(f"   General: {total_general} items | Veggie: {total_veggie} items")

    # Resumen final
    print(f"\n{'='*50}")
    print(f"✨ ¡Listo! {exitosas}/{len(semanas_a_procesar)} semanas procesadas")

    if not args.local and (not uploader or not uploader.db):
        print("\n💡 Para subir a Firebase, creá el archivo de credenciales.")
        print("   Ver SETUP_FIREBASE.md para instrucciones.")

    return 0 if exitosas > 0 else 1


if __name__ == '__main__':
    sys.exit(main())

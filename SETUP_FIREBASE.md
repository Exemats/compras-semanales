# Configurar Firebase para Compras Semanales

Para que la sincronizacion en la nube funcione, necesitas crear un proyecto de Firebase (gratis).

## Pasos

### 1. Crear proyecto en Firebase

1. Ir a [Firebase Console](https://console.firebase.google.com/)
2. Click en "Agregar proyecto"
3. Nombre: `compras-semanales` (o el que quieras)
4. Desactivar Google Analytics (no es necesario)
5. Click "Crear proyecto"

### 2. Agregar app web

1. En la pagina principal del proyecto, click en el icono `</>` (Web)
2. Nombre: `compras-web`
3. NO marcar "Firebase Hosting"
4. Click "Registrar app"
5. Te mostrara el codigo de configuracion - copialo

### 3. Configurar Firestore

1. En el menu lateral, ir a "Firestore Database"
2. Click "Crear base de datos"
3. Seleccionar "Comenzar en modo de prueba" (importante!)
4. Elegir ubicacion cercana (ej: `southamerica-east1` para Argentina)
5. Click "Habilitar"

### 4. Configurar Authentication

1. En el menu lateral, ir a "Authentication"
2. Click en "Get started"
3. En la pestaña "Sign-in method", habilitar "Google"
4. Configurar el email de soporte del proyecto
5. Click "Save"

### 5. Actualizar el codigo

Abrir `index.html` y buscar este bloque:

```javascript
const firebaseConfig = {
    apiKey: "AIzaSyBxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    authDomain: "compras-semanales.firebaseapp.com",
    projectId: "compras-semanales",
    storageBucket: "compras-semanales.appspot.com",
    messagingSenderId: "123456789",
    appId: "1:123456789:web:abcdef123456"
};
```

Reemplazarlo con los valores que copiaste de Firebase.

## Reglas de Firestore (Recomendado)

Para que solo los usuarios autorizados (Mati y Vicky) puedan acceder:

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // Solo usuarios autenticados con emails permitidos
    function isAllowed() {
      return request.auth != null &&
             request.auth.token.email in ['matiarona@gmail.com', 'vickyswag02@gmail.com'];
    }

    // Coleccion de semanas - solo usuarios autorizados
    match /weeks/{weekId} {
      allow read, write: if isAllowed();
    }

    // Coleccion de menus de Paulina - lectura para autorizados, escritura solo desde Admin SDK
    match /paulina_menus/{menuId} {
      allow read: if isAllowed();
      allow write: if false; // Solo el scraper con Admin SDK puede escribir
    }
  }
}
```

---

## Configurar el Scraper (Opcional)

El scraper descarga automaticamente la lista de compras de Paulina Cocina y la sube a Firebase.

### 1. Obtener credenciales de Admin SDK

1. En Firebase Console, ir a "Project Settings" (engranaje)
2. Pestaña "Service Accounts"
3. Click en "Generate new private key"
4. Guardar el archivo como `firebase_credentials.json` en la carpeta del proyecto

**IMPORTANTE:** Este archivo contiene claves privadas. NO lo subas a git.

### 2. Instalar dependencias

```bash
pip install requests beautifulsoup4 firebase-admin
```

### 3. Ejecutar el scraper

```bash
# Descargar la semana actual
python paulina_scraper.py

# Descargar una semana especifica
python paulina_scraper.py --semana 5

# Solo guardar localmente (sin subir a Firebase)
python paulina_scraper.py --local
```

### 4. Automatizar (Opcional)

Para que se ejecute automaticamente cada viernes:

**Linux/Mac (cron):**
```bash
crontab -e
# Agregar esta linea:
0 9 * * 5 cd /ruta/al/proyecto && python paulina_scraper.py
```

**Windows (Task Scheduler):**
```powershell
$action = New-ScheduledTaskAction -Execute "python" -Argument "C:\ruta\al\proyecto\paulina_scraper.py"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At 9am
Register-ScheduledTask -Action $action -Trigger $trigger -TaskName "PaulinaScraper"
```

---

## Usuarios Autorizados

La app esta configurada para que solo estos emails puedan acceder:

- `matiarona@gmail.com`
- `vickyswag02@gmail.com`

Para agregar mas usuarios, editar el array `ALLOWED_EMAILS` en `index.html`.

---

## Sin Firebase (Modo Local)

La app funciona sin Firebase usando localStorage. Los datos se guardan en el navegador pero no se sincronizan entre dispositivos.

Para usar en modo local sin login, comentar o eliminar la seccion de autenticacion en el codigo.

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

### 4. Actualizar el codigo

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

## Reglas de Firestore (Opcional)

Para que cualquier persona pueda usar la app sin login, las reglas deben permitir lectura/escritura:

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /{document=**} {
      allow read, write: if true;
    }
  }
}
```

**Nota:** Estas reglas son abiertas. Si quieres mas seguridad, puedes agregar autenticacion despues.

## Sin Firebase

La app funciona perfectamente sin Firebase, usando solo localStorage. Los datos se guardan en el navegador pero no se sincronizan entre dispositivos.

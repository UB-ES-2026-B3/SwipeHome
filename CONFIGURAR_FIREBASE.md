# Configurar Firebase en local para SwipeHome

## Problema
El servidor backend no está configurado para crear cuentas. Falta la credencial de Firebase en el entorno local.

## Solución

Para ejecutar SwipeHome localmente, necesitas configurar Firebase en el backend. Hay dos formas:

### Opción 1: Usar el archivo JSON de la cuenta de servicio (Recomendado)

1. **Solicita a Arnau** el archivo JSON de la cuenta de servicio de Firebase
   - Este archivo contiene las credenciales del backend
   - Es confidencial: NUNCA lo compartas por chat ni lo comitas en el repositorio
   - Guárdalo en una carpeta FUERA del proyecto (ej: `C:\firebase-credentials\`)

2. **Configura la variable de entorno en PowerShell:**
   ```powershell
   # En una terminal PowerShell en el directorio del backend
   $env:GOOGLE_APPLICATION_CREDENTIALS = 'C:\ruta\fuera\del\repo\cuenta-de-servicio.json'
   $env:FIREBASE_PROJECT_ID = 'swipehome-a51d7'
   $env:DJANGO_DEV = '1'
   
   # Verifica que la variable está configurada
   echo $env:GOOGLE_APPLICATION_CREDENTIALS
   
   # Inicia el servidor
   .\.venv\Scripts\python.exe manage.py runserver
   ```

3. **Variables de entorno necesarias para el backend:**
   ```
   GOOGLE_APPLICATION_CREDENTIALS=C:\ruta\fuera\del\repo\cuenta-de-servicio.json
   FIREBASE_PROJECT_ID=swipehome-a51d7
   DJANGO_DEV=1
   ```

### Opción 2: Usar emulador de Firebase (Para desarrollo sin credenciales reales)

Si no tienes acceso al archivo JSON, puedes usar el emulador de Firebase:

1. **Instala Firebase CLI:**
   ```powershell
   npm install -g firebase-tools
   ```

2. **Inicia el emulador:**
   ```powershell
   cd backend
   firebase emulators:start --only auth,firestore
   ```

3. **Configura las variables de entorno para usar el emulador:**
   ```powershell
   $env:FIREBASE_EMULATOR_HOST = "127.0.0.1:9099"
   $env:FIRESTORE_EMULATOR_HOST = "127.0.0.1:8080"
   $env:FIREBASE_PROJECT_ID = "swipehome-a51d7"
   $env:DJANGO_DEV = "1"
   ```

## Verificar la configuración

Una vez configurado, el error debería desaparecer al:

1. Iniciar el servidor backend:
   ```powershell
   cd backend
   .\.venv\Scripts\python.exe manage.py runserver
   ```

2. Iniciar el servidor frontend:
   ```powershell
   cd frontend
   npm run dev
   ```

3. Abrir http://localhost:5173 en el navegador

## Referencias

- Backend README: `backend/README.md`
- Archivo de ejemplo: `backend/.env.example`
- Configuración Firebase: `backend/accounts/firebase.py`

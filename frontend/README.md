# Frontend de SwipeHome

React + Vite. La autenticación usa el SDK de Firebase Auth en el navegador; el
perfil del usuario lo da el backend Django (`GET /api/auth/me` con el ID token).
Contrato y reglas en la
[especificación de la migración](<../Agents mds/firebase_auth_migration.md>) (§3 y §7).

## Configuración

Copia `.env.example` a `.env.local` (ignorado por Git) y rellena los valores
`VITE_FIREBASE_*`. Están en la consola de Firebase → Configuración del proyecto →
General → Tus apps. No son secretos.

Para que Auth use un emulador local en lugar de Firebase real, establece también
`VITE_FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099`. Si la variable está vacía, el
SDK no se conecta al emulador. Usa un proyecto demo (por ejemplo,
`VITE_FIREBASE_PROJECT_ID=demo-swipehome-us3-8`) y no configures una cuenta de
servicio para la prueba frontend.

```powershell
npm install
npm run dev
```

## Backend al que apunta

Vite reenvía `/api/*` al backend desde su propio servidor, así que no hace falta
CORS.

- **Por defecto:** el Django local en `http://127.0.0.1:8000` (ver `backend/README.md`).
- **El backend desplegado en Render**, sin arrancar Django en local:

  ```powershell
  $env:VITE_API_TARGET = 'https://<servicio>.onrender.com'
  npm run dev
  ```

  `VITE_API_TARGET` se lee de la terminal, no de `.env.local`. Si Render estaba
  dormido, la primera carga tarda ~1 minuto y aparece el aviso "El servidor está
  despertando": es lo esperado.

## Comprobar la sesión en el navegador

Para ver que la sesión es de Firebase y no de cookies hacen falta las DevTools
(F12) de **Edge, Chrome o Firefox**. El navegador DuckDuckGo no tiene DevTools.

- **Network** → petición a `/api/auth/me`: lleva `Authorization: Bearer ...` y no hay
  cookies `sessionid` ni `csrftoken`.
- **Application** (Storage en Firefox): la sesión está en IndexedDB
  (`firebaseLocalStorageDb`); no hay cookies.

## Comprobaciones

```powershell
npm run lint
npm run build
```

Son las mismas que ejecuta el CI.

## Publicación de inmuebles (US3-8)

El vendedor abre `/publicar` desde «Publicar» en su inicio. La ruta exige rol
`SELLER`; a un `BUYER` se le redirige a su inicio. El formulario envía los campos
y las fotografías con `FormData` a `POST /api/inmuebles`, autenticando con el ID
token Firebase y dejando que el navegador genere el `Content-Type` multipart.
Se aceptan JPEG/PNG/WebP reales, hasta 10 fotos de 5 MiB cada una. Los errores
de campo o de foto evitan la solicitud; los errores de red/servidor conservan
los datos para reintentar.

`npm test` (18 pruebas) cubre validación y construcción del multipart. En la comprobación de
navegador de US3-8, Firebase Auth Emulator gestiona la sesión y las respuestas
de `POST /api/inmuebles` se interceptan. El backend usa Firestore Emulator en
sus pruebas de integración y mocks para Azure Blob; el recorrido de navegador
no prueba persistencia real en Firestore ni subida real a Azure. Los resultados
detallados están en
[README backend](../backend/README.md) y [project_context.md](../Agents%20mds/project_context.md).

## Integración US6

`api/auth.js` ofrece `updateProfile`, `changePassword` y logout con revocación
en servidor antes de limpiar el SDK. Contrato y límites:
[US6 backend](<../Agents mds/us6_backend.md>).
El consumidor debe tratar `reauthentication_required` como cambio guardado con
necesidad de iniciar sesión de nuevo. Ejecutar `npm test` para los tests Node
del cliente de API, además de `npm run lint` y `npm run build`.

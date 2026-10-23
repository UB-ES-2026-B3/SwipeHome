# Frontend de SwipeHome

React + Vite. La autenticación usa el SDK de Firebase Auth en el navegador; el
perfil del usuario lo da el backend Django (`GET /api/auth/me` con el ID token).
Contrato y reglas en la
[especificación de la migración](<../Agents mds/firebase_auth_migration.md>) (§3 y §7).

## Configuración

Copia `.env.example` a `.env.local` (ignorado por Git) y rellena los valores
`VITE_FIREBASE_*`. Están en la consola de Firebase → Configuración del proyecto →
General → Tus apps. No son secretos.

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

## Integración US6

`api/auth.js` ofrece `updateProfile`, `changePassword` y logout con revocación
en servidor antes de limpiar el SDK. Contrato y límites:
[US6 backend](<../Agents mds/us6_backend.md>).
El consumidor debe tratar `reauthentication_required` como cambio guardado con
necesidad de iniciar sesión de nuevo. Ejecutar `npm test` para los tests Node
del cliente de API, además de `npm run lint` y `npm run build`.

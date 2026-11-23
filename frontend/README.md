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

## Exploración y decisiones (US4.10)

BuyerHome consulta `GET /api/inmuebles/explorar?limit=20&cursor=...` y envía
decisiones a `POST /api/inmuebles/{id}/decision` con solo
`{"decision":"LIKE"|"PASS"}`. Conserva el cursor al vaciar cada página; cambia
de foto sin decidir, ignora el desplazamiento vertical, permite gesto
horizontal y flechas izquierda/derecha, y confirma únicamente respuestas cuya
decisión y match corresponden al inmueble. LIKE muestra confirmación sin
navegar a US5; PASS no muestra un match. Errores de carga/decisión conservan la
vivienda y permiten reintentar; el servidor garantiza idempotencia. Una sesión
expirada cierra el acceso y devuelve al usuario a la pantalla pública.

Verificación registrada el 10 de noviembre de 2026:

| Comprobación | Método | Resultado y límite |
|---|---|---|
| Campos, fotos múltiples, galería y no decidir al cambiar foto/desplazarse verticalmente | Navegador instrumentado con Auth Emulator y respuestas API interceptadas | Pasa con mocks; no descargó imágenes de Azure. |
| Botón LIKE, doble clic, respuesta temporal y reintento | Browser automation con 503 simulado después de persistir en el fixture; reintento 200 | Pasa con mocks: un match/aviso en fixture; idempotencia real probada aparte en Firestore Emulator. |
| PASS con teclado; gesto horizontal | Flecha izquierda y eventos pointer automatizados | Pasa con mocks; no se probó un dispositivo táctil físico. |
| Recarga, exclusión, pantalla vacía, fallo de carga y sesión expirada | Auth Emulator con perfil/API interceptados; respuestas 500 y 401 simuladas | Pasa con mocks. |
| Responsive | Viewport 1280×900 y 390×844; tarjeta móvil de 343 px | Pasa en navegador de escritorio emulado, no equivale a certificación en dispositivos físicos. |
| Publicación US3, persistencia, notificación, re-login y segundo Comprador | `test_published_multi_photo_listings_survive_full_buyer_flow` con Auth/Firestore Emulator y Azure Blob mock | Pasa con emuladores; Firestore/Azure de producción no verificados. |

`npm test`: 20 tests pasan. `npm run lint` y `npm run build` finalizan; lint
mantiene advertencias existentes. El test de API cubre también el rechazo de
red de `decideProperty`; no se forzó una desconexión física del navegador.

## Notificaciones (US 7.4)

`/notificaciones` está protegida para BUYER y SELLER. Ambos roles consultan
`GET /api/notificaciones` con el ID token Firebase; el backend deriva el
destinatario del token/perfil, ignora cualquier identidad proporcionada por el
cliente y filtra sus propios avisos. La pantalla consume `items/next_cursor`,
conserva los avisos al fallar una actualización, permite reintentar, evita
duplicados al paginar y presenta mensaje y fecha/hora local. En vacío muestra
un estado vacío; fallo inicial y fallo de refresco se distinguen.

Verificación US7.4: `npm test` pasa 25 pruebas, incluida la petición autenticada
de avisos, cursor, `no-store`, ausencia de usuario, error HTTP y error de red.
Lint y build finalizan; persisten avisos ya existentes (Fast Refresh, efecto
de carga y una importación no utilizada en `App.jsx`). En navegador, Auth
Emulator gestionó la sesión y la API se interceptó: se observó el indicador de
carga con la petición retenida; se inyectó un 500 inicial y se reintentó con
éxito; se paginó una respuesta solapada sin duplicados; un 503 al actualizar
conservó los avisos y el retry incorporó uno nuevo; se verificaron mensaje,
fecha/hora local y estado vacío. No hubo desbordamiento horizontal en
1280×900 ni 390×844. Es responsive emulado en escritorio, no una prueba en
hardware móvil ni persistencia real de UI en Firestore.

El estado descrito en la comprobación US7.4 precede a US5.8. US5.8 añadió el
aviso al Comprador al aceptar una candidatura y US5.9 incorporó la consulta
visual de matches y la gestión de candidaturas del Vendedor. La persistencia de
avisos/matches se comprueba en backend con Auth/Firestore Emulator; la UI de
US5.9 se validó aparte contra un mock HTTP local.

## Integración US6

`api/auth.js` ofrece `updateProfile`, `changePassword` y logout con revocación
en servidor antes de limpiar el SDK. Contrato y límites:
[US6 backend](<../Agents mds/us6_backend.md>).
El consumidor debe tratar `reauthentication_required` como cambio guardado con
necesidad de iniciar sesión de nuevo. Ejecutar `npm test` para los tests Node
del cliente de API, además de `npm run lint` y `npm run build`.

### Verificación US 6.8 — perfil y sesión

`npm test` pasa **22 tests**; `npm run lint` y `npm run build` finalizan. Lint
mantiene advertencias en archivos del proyecto, incluidas advertencias
preexistentes.

Con Auth Emulator y respuestas de `/api/auth/me`, contraseña y logout
interceptadas en navegador se comprobó: visualización de perfil/rol; validación
de nombre sin solicitud; conservación de valores ante 500 y retry exitoso;
recarga con perfil actualizado en fixture; error de contraseña; confirmación
de cambio; y logout que conserva la sesión ante 500 y permite reintentar hasta
204, regresar a `/` y bloquear `/mi-perfil`. Esto es verificación de interfaz
con mocks, no persistencia del navegador en Firestore.

La continuidad de token, persistencia de nombre/email y contraseña, carrera
con email duplicado y revocación del Bearer anterior están probadas aparte en
Auth/Firestore Emulators desde el backend. No se conectó Firebase de producción.

### Verificación US 6.9 — recorrido de perfil y logout

En navegador, Auth Emulator gestionó el inicio de sesión de cuentas sintéticas
Buyer y Seller; `/api/auth/me`, cambios de perfil, contraseña y logout se
interceptaron con fixtures. Se comprobó:

| Recorrido | Evidencia y resultado |
|---|---|
| Ambos roles y datos | Login con Buyer y Seller; ambos abrieron `/mi-perfil` y vieron nombre/email/rol esperados. **Pasa con mocks de API.** |
| Edición, cancelar, validar y guardar | Cancelar restableció el valor original; nombre inválido mostró error sin PATCH; duplicado 409 mostró el mensaje. Guardar con Enter confirmó el cambio. **Pasa con mocks.** |
| Carga y repetición | PATCH retenido mostró «Guardando…» y deshabilitó el botón; un segundo click programático no generó otra petición (1 PATCH). **Pasa con mock retenido.** |
| Persistencia visual | Tras guardar, recarga volvió a mostrar el valor actualizado del fixture. **Pasa con mocks; no es persistencia Firestore del navegador.** |
| Contraseña | Confirmación distinta fue rechazada sin petición; error de contraseña actual visible; éxito limpió los campos y conservó la sesión. Inputs observados como `type=password`. **Pasa con mocks.** |
| Logout, reintento y rutas | Con cambios sin guardar, el primer logout 500 mostró aviso y no envió PATCH; acción «Reintentar cierre de sesión» con 204 limpió Auth y llevó a `/`. Atrás y URL `/mi-perfil` quedaron protegidas; login volvió a funcionar. **Pasa con Auth Emulator y API interceptada.** |
| Viewports y teclado | Buyer en 390×844 y Seller en 1280×900; guardado por Enter en ambos formularios. **Pasa en navegador de escritorio emulado; no certifica hardware móvil.** |

El backend de US6.8 ya verificó aparte persistencia, duplicados concurrentes,
cambio de contraseña y revocación con Auth/Firestore Emulator. No se desplegó
Firebase ni se probó en producción en esta US.

## Recorrido de matches y candidaturas (US5.9)

`/mis-matches` es una ruta protegida compartida por BUYER y SELLER; consulta
`GET /api/matches` y presenta solo registros confirmados del usuario. BuyerHome
conserva el aviso de interés enviado sin presentarlo como confirmación. El
inicio SELLER incorpora «Candidaturas pendientes», que consulta
`GET /api/matches/candidatos` y permite ACCEPT/REJECT mediante el endpoint
existente. Se identifica al Comprador y la vivienda. Las decisiones bloquean
solicitudes repetidas; si la respuesta es ambigua o falla, se conserva la
candidatura para reintentar y no se muestra éxito sin confirmación. Cargas,
listas vacías, errores y paginación tienen estados visibles.

`npm test` pasa 27 pruebas, incluidas las nuevas llamadas autenticadas,
paginación y decisión por ID. `npm run lint` y `npm run build` finalizan; Oxlint
mantiene advertencias (`set-state-in-effect` en páginas, importación no usada y
Fast Refresh), sin errores de lint bloqueantes.

En navegador se utilizó Auth Emulator real y un mock HTTP local en memoria
(no Firestore ni el backend real): BUYER envió interés y vio confirmación; antes
de ACCEPT la lista de matches quedó vacía. SELLER identificó vivienda/comprador
y aceptó con Enter; la lista SELLER mostró el match. Un segundo Comprador mostró
interés en otra vivienda y SELLER la rechazó con doble clic; desapareció de
pendientes, no se incorporó a matches y el primer match se conservó. Se
comprobaron lista vacía, fallo 503 con retry y 401 con regreso al login.
Viewports 390×844 y 1280×900 no tuvieron overflow horizontal. Es una prueba
emulada en navegador de escritorio, no hardware móvil ni persistencia real de
la UI. La persistencia, privacidad, re-login e idempotencia se verifican aparte
con Auth/Firestore Emulator en backend. La visualización no depende de chat.

## Filtros del explorador y perfil (US8.6)

`BuyerHome` presenta «Filtros» en el explorador y `Mi perfil` comparte el mismo
componente `PreferenceFilters` para Compradores. El cliente usa
`GET/PUT /api/auth/preferences`, bloquea acciones y swipes mientras aplica o
restablece, conserva el último formulario válido al cancelar y distingue carga,
validación, guardado y consulta fallida. Sin resultados ofrece modificar,
restablecer y actualizar. Las respuestas tardías se invalidan con un identificador
de petición y no sustituyen resultados de una configuración posterior.

Verificación US8.6:

| CA US8 | Método | Resultado |
|---|---|---|
| CA-01/02 | Navegador y tests Node del cliente | Pasa con mocks; API valida los campos reales aparte. |
| CA-03/05 | Navegador con API interceptada y Firestore Emulator | Pasa con mocks visuales/emulador persistente. |
| CA-04/08 | Persistencia y dos compradores en Firestore Emulator | Pasa con emuladores. |
| CA-06/07/09 | Estados vacío/error/validación/reintento simulados | Pasa con mocks. |
| Responsive/teclado | Browser automation y viewports emulados 390×844/1280×900 | Pasa en escritorio emulado; sin hardware físico. |

`npm test` pasa 28 pruebas, `npm run lint` finaliza con advertencias existentes
(incluido el efecto de carga del componente nuevo) y `npm run build` termina
correctamente. Azure no participa en esta US y no se probaron índices ni datos
remotos.

## Disponibilidad en «Mis matches» (US9.7)

BUYER y SELLER ven «Vivienda no disponible» cuando `GET /api/matches`
devuelve `listing.available: false`. La tarjeta conserva la vivienda y la
fecha de confirmación del match.

`npm test` pasó 29 pruebas, incluida una respuesta simulada con un anuncio
disponible y otro cerrado. `npm run lint` terminó con advertencias
preexistentes y `npm run build` pasó. La verificación de este cambio de
interfaz en US9.7 se limitó al contrato del cliente y la compilación.

## Recorrido de selección definitiva (US9.8)

El Vendedor envía la propuesta desde un match confirmado en «Mis matches».
Puede revisarla o cancelarla en «Propuestas». El Comprador destinatario
abre el detalle desde «Propuestas» o desde el enlace del aviso, consulta los
datos vigentes y acepta o rechaza. Las propuestas resueltas quedan visibles
en el historial. Los avisos de indisponibilidad de otros candidatos contienen
los datos públicos de la vivienda.

Los controles se bloquean mientras se guarda. Si se pierde la respuesta de
un envío, «Reintentar envío» recupera la misma intención incluso después
de recargar esa pestaña. Una respuesta sobre una propuesta ya resuelta
actualiza el estado visible.

El comando para ejecutar los recorridos en Chrome o Chromium y los
emuladores está en el [README de backend](../backend/README.md). Los
controles locales del cliente son `npm test`, `npm run lint` y
`npm run build`.

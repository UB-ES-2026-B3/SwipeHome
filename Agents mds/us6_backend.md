# US6 backend: perfil y cierre de sesión con Firebase

Implementado en la rama `US6-backend`. Adaptación a Firebase autorizada por el
usuario el 22 de octubre de 2026. Este contrato sustituye, para US6, los
criterios originales basados en ORM, sesiones Django, cookies y CSRF.
No se crean modelos ni migraciones.

## Contrato HTTP

Todas las operaciones de cuenta identifican al usuario exclusivamente mediante
`Authorization: Bearer <ID token Firebase>` verificado. Admiten BUYER y SELLER.
El identificador del contrato vigente es `uid`, no el antiguo `id` numérico.

| Método y ruta | Entrada | Éxito | Errores |
|---|---|---|---|
| GET `/api/auth/me` | Sin cuerpo | 200: `{uid, name, email, role}` | 401, 404 si falta perfil, 500 |
| PATCH / PUT `/api/auth/me` | JSON con `name`, `email` o ambos | 200: perfil; incluye `custom_token` si se envió email | 400, 401, 404, 409 email ocupado, 500 |
| POST `/api/auth/me/password` | JSON: `current_password`, `new_password` | 200: `{custom_token}` | 400, 401, 404, 500 |
| POST `/api/auth/logout` | Bearer; sin cuerpo | 204 sin contenido; también si ya no hay identidad válida | 500 |
| GET `/api/auth/logout` | — | — | 405 |

Las respuestas de estas operaciones llevan `Cache-Control: no-store`.
Los fallos son genéricos; nunca se incluyen contraseñas, hashes, respuestas
REST completas del proveedor, tokens de sesión en logout ni trazas internas.
El `custom_token` es una credencial de continuidad **intencionada**, entregada
solo al cliente autenticado al editar email o contraseña, mediante HTTPS.
El SDK la intercambia inmediatamente con `signInWithCustomToken`; la aplicación
no la registra ni la conserva en su estado o almacenamiento propio.

## US6.4: validación e identidad

- Nombre: texto de 2–80 caracteres tras quitar espacios exteriores.
- Email: las reglas existentes de registro, hasta 254 caracteres, normalizado
  con `normalize_account_email` antes de enviarlo al proveedor.
- PATCH y PUT son parciales: exigen algún campo editable y preservan los omitidos.
- Se rechazan campos desconocidos, incluidos `id`, `uid`, `role` y `password`.
  Ninguna URL ni payload permite seleccionar una cuenta distinta.
- El propio email actual es válido; `EmailAlreadyExistsError` se traduce a 409.
- Contraseña actual: texto de 1–128 caracteres, comprobado mediante la API
  Firebase `accounts:signInWithPassword`. Se comprueba también que `localId`
  coincida con el uid del token original.
- Nueva contraseña: 15–128 caracteres, distinta de la actual, no solo espacios,
  ni común ni exclusivamente numérica (validadores Django). Firebase puede
  imponer una política adicional y su rechazo devuelve 400.
  Ninguna contraseña se recorta, trunca o transforma.
- El hashing lo realiza Firebase Auth. No se guardan hashes en Firestore ni se
  vuelve a introducir autenticación Django.

El módulo histórico `accounts/validation.py` se conserva intacto.
Las reglas US6 están en `profile_validation.py`.

## US6.5: persistencia, unicidad y atomicidad

**Firebase Auth es la fuente vigente de email y nombre editable
(`display_name`).** Se reutiliza la cuenta Auth existente. Una sola llamada
`auth.update_user` envía los campos editables recibidos: no se hace una
comprobación de unicidad seguida de una escritura independiente.
Firebase garantiza la unicidad del email; el test contra el emulador verifica
también el rechazo conjunto de nombre y email cuando el email está ocupado.

Firestore conserva el rol, la existencia del perfil y las relaciones.
Los `name/email` históricos de `users/{uid}` son una instantánea del registro,
**no una segunda fuente de datos editables**. Toda lectura vigente debe pasar
por `repository.get_user_profile`, que combina el rol de Firestore con el email
y nombre actuales de Auth. Si una cuenta antigua no tiene `display_name`, se
usa su nombre histórico hasta que se edita. Los nuevos registros ya crean
`display_name` en Auth.

Esta decisión evita una transacción distribuida imposible entre Auth y
Firestore. No hay escrituras dobles ni compensaciones que puedan sobrescribir
la edición concurrente de otro cliente. Los cambios se conservan en el proveedor
y no dependen del disco efímero de Render. El uid y el rol no se actualizan.
No se escriben inmuebles, decisiones ni matches. Al cambiar realmente el email
se borra su marca de verificación.

Un rechazo confirmado por Firebase no modifica el nombre/email ni la
contraseña anterior. Las validaciones, reautenticación y firma de la
credencial de continuidad se completan antes de escribir.
**Límite de una API remota:** si se pierde la conexión después de que Firebase
acepte una escritura, un 500 puede tener resultado ambiguo. No es posible
prometer rollback del proveedor ante ese caso ni restaurar un hash que Firebase
no expone. Consultar el perfil o volver a autenticar antes de reintentar;
no se documenta una garantía falsa de transacción distribuida.

## US6.7: logout y revocación

El SDK `signOut` por sí solo no invalida un ID token que haya sido copiado.
El backend persiste una revocación para el par `(uid, auth_time)` en
`revoked_sessions/{sha256(JSON([uid, auth_time]))}`.
El documento solo contiene `{revoked: true}`: nunca tokens ni credenciales.
La escritura `set` es idempotente.

La verificación compartida de todos los endpoints protegidos exige:
firma/caducidad válidas, cuenta habilitada, `check_revoked=True` y ausencia de
esa revocación en Firestore. Los tokens renovados conservan `auth_time`, por
lo que renovar el ID token no elude el logout. Si Firestore falla se devuelve
500 y se impide continuar; no se convierte un fallo de infraestructura en 401.
No se usa `revoke_refresh_tokens(uid)` para logout, porque afectaría a todas las
sesiones de la cuenta. No se borran los documentos de revocación por edad:
el refresh token puede seguir generando ID tokens nuevos.

**Granularidad:** Firebase no proporciona un identificador de dispositivo o de
sesión individual en este contrato. `auth_time` tiene precisión de segundos:
dos inicios de la misma cuenta en el mismo segundo comparten la revocación.
Otras cuentas y sesiones con distinto `auth_time` no se cierran. El bloqueo se
aplica a esta API; no invalida por sí mismo el refresh token en el proveedor
ni protege acceso directo a Firebase. Se mantienen las reglas Firestore
cerradas a clientes. Una separación exacta por dispositivo requeriría otro
contrato de sesiones y queda fuera de esta adaptación.

El frontend espera el 204 del servidor antes de ejecutar `signOut`.
Los errores de red/500 conservan el SDK y muestran un aviso para reintentar.
Los 401/404 al recuperar identidad limpian únicamente el SDK, sin solicitar un
nuevo logout al servidor.

No hay cookies de sesión de Django que eliminar ni autenticación automática
por cookie. CSRF de Django no se aplica a este contrato Bearer: una petición
con cookies solamente no puede revocar una sesión autenticada. No se habilita
CORS general. No se ha introducido un endpoint de cookies sin protección.

## Continuidad de sesión y configuración

Configurar `FIREBASE_WEB_API_KEY` en el backend con la Web API key del mismo
proyecto Firebase (valor público; ejemplo vacío en `backend/.env.example`).
Las credenciales Admin existentes deben permitir firmar custom tokens.
No se añaden dependencias de producción.

Cambiar email o contraseña puede invalidar sesiones Firebase existentes.
La respuesta incluye la credencial de continuidad para que el cliente actual
establezca una sesión válida sin pedir de nuevo sus credenciales.
No se promete conservar las demás sesiones al cambiar una contraseña.

`frontend/src/api/auth.js` incorpora `updateProfile` y `changePassword`.
Si el cambio persistió pero falla el intercambio de continuidad, devuelve
`ok: true` y `reauthentication_required: true`: el consumidor debe informar del
cambio guardado y pedir iniciar sesión de nuevo. Si se pierde la respuesta HTTP,
puede ser necesario iniciar sesión con los datos nuevos. No se incluyen
pantallas de edición en esta tarea backend.

## Verificación reproducible

Suite ordinaria, desde `backend/`:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test accounts properties --verbosity 2
```

La suite ordinaria omite los tests de emulador si no se configura
`FIREBASE_AUTH_EMULATOR_HOST`. Para ejecutarlos sin credenciales ni acceso a
producción, desde `backend/`, con Node 24 (versión comprobada):

```powershell
npx --yes --package firebase-tools@15.34.1 firebase emulators:exec --project demo-swipehome-us6 --only auth --config tests/firebase.json ".venv\Scripts\python.exe manage.py test accounts.test_profile.EmailRaceIntegrationTests --verbosity 2"
```

El comando arranca y detiene el emulador local. Las pruebas usan un proyecto
`demo-*`; el test REST redirige explícitamente la reautenticación al emulador.
Nunca se necesitan credenciales del proyecto real.

Desde `frontend/`:

```powershell
npm test
npm run lint
npm run build
```

Las pruebas Node usan el módulo real de API en un contexto aislado con Firebase
y fetch simulados. Comprueban logout, errores y continuidad sin nuevas
dependencias. CI ejecuta las pruebas ordinarias, los dos casos del emulador y
los tests del cliente, además de los controles anteriores.

Referencias de proveedor:
[actualización de usuarios](https://firebase.google.com/docs/auth/admin/manage-users),
[sesiones y revocación](https://firebase.google.com/docs/auth/admin/manage-sessions),
[API REST de Auth](https://firebase.google.com/docs/reference/rest/auth) y
[custom auth del cliente](https://firebase.google.com/docs/auth/web/custom-auth).

## Resultado de verificación (23 octubre 2026)

- Suite backend completa dentro de Firebase Auth Emulator: **90 tests, todos
  pasan, sin omisiones**, incluidos concurrencia real de email y cambio de
  contraseña con intercambio de custom token y consulta autenticada posterior.
- Suite ordinaria sin emulador: 88 pasan y 2 integraciones se omiten
  explícitamente.
- Cliente de autenticación: **8 tests pasan**.
- `manage.py check`: sin incidencias. `npm run build`: correcto.
- `npm run lint`: correcto con la advertencia preexistente de Fast Refresh en
  `AuthContext.jsx`. `git diff --check`: correcto.
- Instalado en el venv local Pillow 12.3.0, ya fijado en requirements, que
  faltaba en el entorno; no se modifica el manifiesto de dependencias.
- Se usaron únicamente cuentas sintéticas del emulador. No se verificó contra
  producción ni se ejecutó un despliegue o un workflow remoto.

## Archivos afectados

Backend:

- `backend/accounts/authentication.py`: verificación compartida y revocación.
- `backend/accounts/repository.py`: lectura del perfil vigente, actualización
  Auth y documentos de revocación en Firestore.
- `backend/accounts/views.py`: nombre Auth en nuevos registros.
- `backend/accounts/profile_views.py`, `profile_validation.py` y
  `passwords.py`: endpoints US6, reglas y reautenticación.
- `backend/config/urls.py`: rutas de perfil, contraseña y logout.
- `backend/accounts/test_profile.py`: nuevas pruebas e integración.
- `backend/accounts/test_authentication.py`, `test_repository.py` y
  `test_views.py`: adaptación de pruebas existentes.
- `backend/tests/firebase.json`: emulador de Auth, solo loopback.
- `backend/.env.example` y `backend/README.md`: configuración y contrato.

Cliente e integración:

- `frontend/src/api/auth.js`: logout de servidor y continuidad SDK.
- `frontend/src/context/AuthContext.jsx`: errores de logout y limpieza local
  tras rechazos de identidad.
- `frontend/tests/auth.test.mjs`, `frontend/package.json` y
  `frontend/README.md`: pruebas y su ejecución.
- `.github/workflows/ci.yml`: pruebas Node y Firebase Auth Emulator.

Contexto:

- Este `Agents mds/us6_backend.md` y los seis MDs previos:
  `backend_context.md`, `frontend_context.md`, `project_context.md`,
  `infra_context.md`, `firebase_auth_migration.md` y `skills.md`.
- Registro local en `agent_changelog_local.md`, excluido de Git.
  `resultado.md` era preexistente y se conserva sin modificar.

# Backend de SwipeHome

Django sin base de datos propia: las cuentas y sus campos editables
(nombre/email) viven en **Firebase Auth**; Firestore conserva el rol y las
relaciones. Django crea usuarios, verifica ID tokens y compone el perfil vigente.
El documento Firestore conserva una instantánea de nombre/email del registro;
las lecturas actuales pasan por `repository.get_user_profile`.

Documentación de referencia:
[migración a Firebase (contrato de la API)](<../Agents mds/firebase_auth_migration.md>),
[infraestructura](<../Agents mds/infra_context.md>),
[contexto backend](<../Agents mds/backend_context.md>) y
[pautas del equipo](<../Agents mds/skills.md>).
Donde se contradigan en base de datos, despliegue o autenticación, manda
`infra_context.md`.

Python **3.13** en local (el CI usa 3.12), Django **5.2.18**.

## Instalación

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

No hay migraciones ni modelos ORM: `DATABASES = {}`. Los perfiles y anuncios
se almacenan en Firestore.

## Ejecutar en local

Hace falta el JSON de la cuenta de servicio de Firebase, guardado **fuera** del
repositorio (pídeselo a Arnau). Nunca lo copies dentro del proyecto ni lo compartas
por chat.

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = 'C:\ruta\fuera\del\repo\cuenta-de-servicio.json'
$env:FIREBASE_PROJECT_ID = 'swipehome-a51d7'
$env:DJANGO_DEV = '1'
.\.venv\Scripts\python.exe manage.py runserver
```

[.env.example](.env.example) describe todas las variables. El archivo `.env` no se
carga automáticamente: hay que definirlas en la terminal. El frontend Vite
proxifica `/api/*` a `http://127.0.0.1:8000`.

**Ojo:** solo hay un proyecto de Firebase (`swipehome-a51d7`). Lo que registres en
local queda junto a los datos reales. Usa emails de prueba reconocibles y bórralos
desde la consola de Firebase al terminar.

## Endpoints

| Método | Ruta | Resumen |
|---|---|---|
| `GET` | `/api/notificaciones` | Avisos propios, paginados y de solo lectura: 200 / 400 / 401 / 403 / 500 |
| `GET` | `/api/health` | Comprobación de vida. No toca Firebase. |
| `POST` | `/api/auth/register` | `{name, email, password, role}` → 201 / 400 / 409 / 500 |
| `GET` | `/api/auth/me` | `Authorization: Bearer <ID token>` → 200 / 401 / 404 / 500 |
| `PATCH/PUT` | `/api/auth/me` | JSON parcial `name/email` → 200 / 400 / 401 / 404 / 409 / 500 |
| `POST` | `/api/auth/me/password` | `current_password/new_password` → 200 / 400 / 401 / 404 / 500 |
| `POST` | `/api/auth/logout` | Revocación persistente e idempotente → 204 / 500; GET → 405 |

El login lo hace el frontend directamente contra Firebase; no hay `/api/auth/login`.
La publicación se realiza mediante `POST /api/inmuebles`.
La publicación requiere un ID token Firebase válido y un perfil con rol `SELLER`.
El cuerpo es `multipart/form-data`, admite nombres de campos en inglés o
castellano y recibe entre 1 y 10 fotografías en `photos`, `fotografias` o
`images`. Cada archivo debe ser JPEG, PNG o WebP real y ocupar como máximo 5 MB.
Las fotografías se suben a Firebase Storage y el anuncio se guarda en la
colección Firestore `listings` con el `seller_uid` obtenido del token.
El contrato completo, el significado de cada código y cómo debe reaccionar el
frontend están en el §3 de la
[especificación](<../Agents mds/firebase_auth_migration.md>).

Las reglas de validación del registro están en `accounts/validation.py`: nombre
2–80, email normalizado (minúsculas, sin espacios) de hasta 254 caracteres,
contraseña de 15–128 caracteres sin recortar y rol `SELLER` o `BUYER`.

## Estructura de `accounts/`

- `views.py` — endpoints. No habla con Firestore directamente.
- `repository.py` — **único** módulo que accede a Firestore (colecciones `users`, `listings`, `notifications` y `revoked_sessions`).
- `authentication.py` — extrae y verifica el ID token. Nunca lo escribe en los logs.
- `firebase.py` — inicializa el Admin SDK, de forma perezosa y una sola vez.
- `validation.py` — validación del registro.
- `fields.py` — `normalize_account_email`, la única regla de normalización de email.

## Tests

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test accounts properties --verbosity 2
```

La suite cubre el registro y la autenticación Firebase, los permisos de
publicación, la asociación del anuncio con el uid verificado, la validación de
campos y fotografías reales, los alias en castellano, los límites de cantidad y
tamaño, la detección de alias contradictorios, la serialización de respuestas y
la compensación segura del almacenamiento cuando el resultado de Firestore es
ambiguo.

Referencias: [campos Django](https://docs.djangoproject.com/en/5.2/howto/custom-model-fields/),
[restricciones](https://docs.djangoproject.com/en/5.2/ref/models/constraints/),
[migraciones de datos](https://docs.djangoproject.com/en/5.2/ref/migration-operations/#runpython).

## Comprobación manual de autenticación y publicación

El frontend inicia sesión con Firebase y envía el ID token como
`Authorization: Bearer <token>`. Para consultar el perfil actual:

```javascript
const token = await firebase.auth().currentUser.getIdToken();
const meResponse = await fetch('/api/auth/me', {
  headers: {Authorization: `Bearer ${token}`},
  cache: 'no-store'
});
console.log(meResponse.status, await meResponse.json());
```

Para publicar un inmueble, el usuario debe tener perfil `SELLER`. El frontend
debe construir un `FormData` y no establecer manualmente `Content-Type`:

```javascript
const token = await firebase.auth().currentUser.getIdToken();
const form = new FormData();
form.append('title', 'Piso luminoso');
form.append('street', 'Calle Mayor 1');
form.append('city', 'Barcelona');
form.append('postal_code', '08001');
form.append('description', 'Una descripción válida');
form.append('price', '950.50');
form.append('surface', '65.50');
form.append('bedrooms', '2');
form.append('bathrooms', '1');
form.append('people', '3');
form.append('shared_accommodation', 'No');
form.append('photos', photoFile);

const response = await fetch('/api/inmuebles', {
  method: 'POST',
  headers: {Authorization: `Bearer ${token}`},
  body: form,
});
console.log(response.status, await response.json());
```

Se espera `201` y un identificador de anuncio. En Firestore debe aparecer un
documento en `listings` con `seller_uid` igual al uid del token y las URLs de
Firebase Storage. Un usuario sin token obtiene `401` y un usuario `BUYER`
obtiene `403`.

## Dependencias reproducibles

`requirements.txt` fija la versión exacta de todas las dependencias, directas y
transitivas. Se genera con `pip freeze` desde un entorno virtual limpio, no a mano.
Para añadir una dependencia: crea un venv nuevo, instala el `requirements.txt` actual
más el paquete nuevo con su versión fijada y sustituye el fichero por la salida de
`pip freeze`.

## Despliegue (Render)

Build `pip install -r requirements.txt`, start
`gunicorn config.wsgi:application --bind 0.0.0.0:$PORT`. Variables:
`DJANGO_SECRET_KEY`, `FIREBASE_SERVICE_ACCOUNT_JSON`, `FIREBASE_PROJECT_ID` y
`FIREBASE_STORAGE_BUCKET`. Render
inyecta `RENDER_EXTERNAL_HOSTNAME`, y `settings.py` lo añade a `ALLOWED_HOSTS` y
activa `SECURE_PROXY_SSL_HEADER`. Ver `infra_context.md` §3.

## US6: perfil, contraseña y logout

Contrato, decisiones de atomicidad, configuración y comandos del emulador:
[US6 backend](<../Agents mds/us6_backend.md>).

Configura también `FIREBASE_WEB_API_KEY` (Web API key pública del mismo proyecto)
para comprobar la contraseña actual. Auth gestiona hashing y unicidad.
Email y nombre se actualizan juntos en una sola operación Auth; Firestore
conserva rol y relaciones. Las lecturas usan datos Auth actuales.

El logout escribe una revocación por `uid/auth_time`; todos los endpoints
protegidos la consultan además de verificar Firebase con `check_revoked=True`.
No usa cookies ni CSRF Django. Las revocaciones no deben caducar automáticamente.
Una revocación afecta a los logins de la misma cuenta en el mismo segundo;
no es una revocación exacta por dispositivo ni invalida directamente el refresh
token del proveedor. Los límites y la recuperación ante respuestas perdidas
están descritos en el contrato.

El cliente intercambia `custom_token` tras cambiar email/contraseña.
Si el intercambio falla tras guardar, indica `reauthentication_required`.
Los consumidores deben pedir iniciar sesión de nuevo en ese caso.


## GET /api/notificaciones

Consulta de solo lectura para usuarios BUYER y SELLER. Reutiliza la autenticación
Firebase existente: `Authorization: Bearer <ID token>`, incluida la comprobación
de revocación. La vista construye `request.user` con la identidad verificada y el
rol del perfil; el destinatario de la consulta procede exclusivamente de ese objeto.
Las cookies por sí solas no autentican esta API.

| Query | Contrato |
|---|---|
| `limit` | Entero decimal entre 1 y 50, ambos incluidos. Predeterminado: 20. |
| `cursor` | Cadena opaca devuelta en `next_cursor`. Omitir en la primera consulta; enviar con codificación URL en las siguientes. |

Se rechazan con 400 los parámetros desconocidos (incluidos `uid`, `recipient_uid`
y cualquier selector de cuenta), repetidos, vacíos o inválidos. Un cursor está
firmado y vinculado a su usuario; no puede reutilizarse para otra cuenta ni
modificarse. Es opaco, no cifrado: el consumidor no debe interpretar su contenido.
El servidor usa `DJANGO_SECRET_KEY`, que debe ser estable y secreto en producción;
al rotarlo, los cursores anteriores dejan de ser válidos y se debe empezar de nuevo.

Orden fijo: `created_at DESC`, identificador de documento `DESC` como desempate.
Se consultan como máximo `limit + 1` registros para detectar otra página.
El cursor conserva la precisión de nanosegundos de Firestore y no depende de que
el documento de la página anterior siga existiendo. La paginación no representa
una instantánea: los avisos nuevos anteriores al cursor se verán al actualizar
desde la primera página. El escritor futuro debe mantener inmutables destinatario
y fecha de creación para conservar un recorrido estable.

Ejemplo de respuesta 200:

```json
{
  "items": [
    {
      "id": "notification-123",
      "type": "MATCH",
      "message": "Tienes un nuevo match.",
      "created_at": "2026-11-06T12:30:00.123456789Z"
    }
  ],
  "next_cursor": null
}
```

`MATCH` es un ejemplo de tipo, no un catálogo cerrado. Cada elemento contiene
únicamente `id`, `type`, `message` y `created_at` (RFC 3339 en UTC).
`next_cursor` es una cadena cuando quedan resultados y `null` al terminar.
Sin avisos: `200 {"items": [], "next_cursor": null}`.

| HTTP | Significado |
|---|---|
| 200 | Consulta correcta, incluida colección vacía. |
| 400 | Query o cursor inválido, manipulado o de otra cuenta. |
| 401 | Token ausente, inválido, caducado o sesión revocada. Incluye `WWW-Authenticate: Bearer`. |
| 403 | Perfil inexistente o rol diferente de BUYER/SELLER. |
| 405 | Método distinto de GET. |
| 500 | Fallo interno, de verificación del proveedor o de Firestore; permite reintentar conservando la sesión. |

Los errores contienen `{"error": "mensaje genérico"}` sin credenciales, hashes,
consultas ni trazas internas. Las respuestas llevan `Cache-Control: no-store`.
La consulta no genera avisos ni matches, no cambia decisiones, no marca avisos
como leídos y no elimina documentos.

### Persistencia compartida para US4 futura

US4 aún no está implementada. Esta ampliación define una única colección
Firestore `notifications`, que US4 deberá reutilizar al generar avisos:

| Campo | Tipo y origen |
|---|---|
| ID del documento | Identificador único del aviso; se devuelve como `id`. |
| `recipient_uid` | String: UID Firebase del destinatario, fijado por el servidor escritor. |
| `type` | String: tipo de aviso fijado por el servidor escritor. |
| `message` | String: mensaje público, sin datos secretos. |
| `created_at` | Timestamp Firestore UTC, fijado por el servidor escritor al crear. |

No hay modelos ORM, migraciones, otra colección paralela ni generación de avisos
en esta implementación. Firestore no requiere crear la colección vacía: aparecerá
con su primera escritura futura. Los registros sin `created_at` no participan
en la consulta ordenada; el escritor debe garantizar el esquema completo.

La consulta requiere el índice compuesto especificado en
[firestore.indexes.json](firestore.indexes.json): ámbito Collection para
`notifications`, `recipient_uid` ascendente, `created_at` descendente y nombre
de documento (`__name__`) descendente. Configurarlo en Firebase/Google Cloud
antes de usar la consulta y esperar a que esté habilitado. Este cambio incluye
la definición del índice, pero no lo despliega al proyecto remoto. Sin el índice,
Firestore puede rechazar la consulta; el endpoint devuelve 500 genérico.
Los clientes siguen sin acceso directo a Firestore; se mantienen sus reglas cerradas.

### Verificación de notificaciones

Desde `backend/`:

```powershell
.\.venv\Scripts\python.exe manage.py test accounts.test_notifications --verbosity 2
```

13 pruebas nuevas verifican autenticación y revocación, ambos roles, destinatario
verificado, rechazo de selectores de cuenta, límites, cursores firmados y su
vinculación a la cuenta, precisión temporal, campos públicos, consulta Firestore
y ausencia de escrituras. Firebase se simula; no se accede a producción.
Suite completa: 103 pruebas, 101 pasan y 2 integraciones Auth se omiten por
no estar configurado el emulador. `manage.py check`: sin incidencias.
La consulta y el índice no se han verificado contra Firestore real o su emulador.

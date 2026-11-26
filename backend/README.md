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

Para publicar anuncios con fotos hace falta además la cadena de conexión de
Azure Storage (pídesela a Arnau; es un secreto). Cópiala al portapapeles y
cárgala así, sin escribirla en la línea de comandos para que no quede en el
historial de PowerShell:

```powershell
$env:AZURE_STORAGE_CONNECTION_STRING = (Get-Clipboard -Raw).Trim()
$env:AZURE_STORAGE_CONNECTION_STRING.Length            # > 0
$env:AZURE_STORAGE_CONNECTION_STRING.Substring(0, 30)  # DefaultEndpointsProtocol=https
```

Comprueba la longitud y el inicio antes de seguir: un aviso oculto
(`Read-Host -AsSecureString`) puede no recibir el pegado y dejar la variable
vacía o con basura. Sin la variable, el servidor arranca pero publicar devuelve
`500` y el log dice qué falta.

[.env.example](.env.example) describe todas las variables. El archivo `.env` no se
carga automáticamente: hay que definirlas en la terminal. El frontend Vite
proxifica `/api/*` a `http://127.0.0.1:8000`.

**Ojo:** solo hay un proyecto de Firebase (`swipehome-a51d7`). Lo que registres en
local queda junto a los datos reales. Usa emails de prueba reconocibles y bórralos
desde la consola de Firebase al terminar.

## Endpoints

| Método | Ruta | Resumen |
|---|---|---|
| `GET` | `/api/notificaciones` | Avisos privados BUYER/SELLER paginados: 200 / 400 / 401 / 403 / 500 |
| `GET` | `/api/inmuebles` | Inmuebles publicados del SELLER autenticado: 200 / 401 / 500 |
| `GET` | `/api/inmuebles/mios` | Publicaciones propias del SELLER con estado y acciones: 200 / 401 / 403 / 500 |
| `GET` | `/api/inmuebles/{id}/gestion` | Detalle de un anuncio propio para gestionarlo: 200 / 401 / 403 / 404 / 500 |
| `PATCH` | `/api/inmuebles/{id}` | Modificar datos y fotografías (JSON o multipart): 200 / 400 / 401 / 403 / 404 / 409 / 500 |
| `POST` | `/api/inmuebles/{id}/pausar` | Pausar un anuncio activo (`{"version":N}`): 200 / 400 / 401 / 403 / 404 / 409 / 500 |
| `POST` | `/api/inmuebles/{id}/reactivar` | Reactivar un anuncio pausado (`{"version":N}`): 200 / 400 / 401 / 403 / 404 / 409 / 500 |
| `POST` | `/api/inmuebles/{id}/retirar` | Cerrar manualmente el anuncio (`{"version":N}`): 200 / 400 / 401 / 403 / 404 / 409 / 500 |
| `GET` | `/api/inmuebles/explorar` | Viviendas pendientes BUYER paginadas. |
| `POST` | `/api/inmuebles/{id}/decision` | Decisión BUYER; LIKE crea match y aviso: 201 / 200 / 400 / 401 / 403 / 404 / 409 / 500 |
| `GET` | `/api/health` | Comprobación de vida. No toca Firebase. |
| `POST` | `/api/auth/register` | `{name, email, password, role}` → 201 / 400 / 409 / 500 |
| `GET` | `/api/auth/me` | `Authorization: Bearer <ID token>` → 200 / 401 / 404 / 500 |
| `PATCH/PUT` | `/api/auth/me` | JSON parcial `name/email` → 200 / 400 / 401 / 404 / 409 / 500 |
| `POST` | `/api/auth/me/password` | `current_password/new_password` → 200 / 400 / 401 / 404 / 500 |
| `POST` | `/api/auth/logout` | Revocación persistente e idempotente → 204 / 500; GET → 405 |

El login lo hace el frontend directamente contra Firebase; no hay `/api/auth/login`.
La publicación se realiza mediante `POST /api/inmuebles`.
La lectura mediante `GET /api/inmuebles` devuelve únicamente los inmuebles
publicados por el vendedor autenticado.
La publicación requiere un ID token Firebase válido y un perfil con rol `SELLER`.
El cuerpo es `multipart/form-data`, admite nombres de campos en inglés o
castellano y recibe entre 1 y 10 fotografías en `photos`, `fotografias` o
`images`. Cada archivo debe ser JPEG, PNG o WebP real y ocupar como máximo 5 MB.
Las fotografías se suben a Azure Blob Storage (contenedor
`AZURE_STORAGE_CONTAINER`, por defecto `listings`, blobs
`{uid}/{uuid}`) y el anuncio se guarda en la colección Firestore
`listings` con el `seller_uid` obtenido del token y la URL pública de cada
blob. El contenedor tiene acceso anónimo «Blob»: las URLs se leen sin
credenciales ni token, pero el contenedor no se puede listar.
El contrato completo, el significado de cada código y cómo debe reaccionar el
frontend están en el §3 de la
[especificación](<../Agents mds/firebase_auth_migration.md>).

Las reglas de validación del registro están en `accounts/validation.py`: nombre
2–80, email normalizado (minúsculas, sin espacios) de hasta 254 caracteres,
contraseña de 15–128 caracteres sin recortar y rol `SELLER` o `BUYER`.

## Estructura de `accounts/`

- `views.py` — endpoints. No habla con Firestore directamente.
- `repository.py` — **único** módulo que accede a Firestore (colecciones `users`, `listings`, `swipes`, `matches`, `notifications` y `revoked_sessions`).
- `authentication.py` — extrae y verifica el ID token. Nunca lo escribe en los logs.
- `firebase.py` — inicializa el Admin SDK, de forma perezosa y una sola vez.
- `azure_storage.py` — crea el cliente del contenedor de fotografías, de forma perezosa y una sola vez. Nunca escribe la cadena de conexión en logs ni excepciones.
- `validation.py` — validación del registro.
- `fields.py` — `normalize_account_email`, la única regla de normalización de email.

## Tests

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test accounts properties --verbosity 2
```

Para ejecutar las integraciones con Auth y Firestore locales (desde `backend`):

```powershell
npx.cmd --yes --package firebase-tools@15.34.1 firebase emulators:exec --project demo-swipehome-us4 --only auth,firestore --config tests/firebase.json ".venv\Scripts\python.exe -B manage.py test accounts properties --verbosity 2"
```

La suite cubre registro y autenticación, permisos de publicación, propietario
derivado del ID token, campos y fotografías, límites inclusivos de 10 imágenes
y 5 MiB, formatos JPEG/PNG/WebP, URLs y orden, limpieza compensatoria ante
fallos, serialización sin información interna, y lecturas/escrituras contra
Firestore Emulator. Azure Blob se simula con mocks en los tests; no se requiere
cadena de conexión y no se prueba persistencia real en Azure.

#### Resultado US3-7 y regresión backend del merge

El comando anterior pasó **165 tests**, sin omisiones, y `manage.py check`
identificó cero incidencias. Se ejecutó Auth Emulator y Firestore Emulator; no se
usaron credenciales Firebase reales. Los tests de Azure Blob usan mocks. Si una
escritura Firestore falla y la lectura de conciliación también falla, el
resultado es indeterminado: se conservan los blobs para no romper un anuncio
que pudiera haberse guardado; ese caso requiere conciliación operativa y no
demuestra rollback distribuido absoluto.

#### Resultado US3-8: recorrido de publicación desde la interfaz

La ruta `/publicar` está protegida para `SELLER` y envía `multipart/form-data`
a `POST /api/inmuebles` con el ID token. La verificación en navegador emplea
Auth Emulator y respuestas interceptadas del endpoint: comprueba el flujo y el
contrato frontend, pero no crea el anuncio en Firestore ni sube las imágenes a
Azure. Los resultados detallados, los casos cubiertos y las limitaciones se
registran en el [contexto frontend](../Agents%20mds/frontend_context.md) y el
[contexto del proyecto](../Agents%20mds/project_context.md).

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
documento en `listings` con `seller_uid` igual al uid del token y las URLs
`https://<cuenta>.blob.core.windows.net/<contenedor>/<uid>/<uuid>`,
que se abren en el navegador sin iniciar sesión. Un usuario sin token obtiene `401` y un usuario `BUYER`
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
`DJANGO_SECRET_KEY`, `FIREBASE_SERVICE_ACCOUNT_JSON`, `FIREBASE_PROJECT_ID`,
`AZURE_STORAGE_CONNECTION_STRING` (secreto: contiene la clave de la cuenta) y,
opcionalmente, `AZURE_STORAGE_CONTAINER` (por defecto `listings`). Sin la
cadena de conexión el servidor arranca y responde, pero publicar devuelve `500`
y el log indica qué variable falta o qué le pasa. El cliente de Azure limita
reintentos y timeouts para que una subida fallida termine en ~19 s como máximo,
antes de los 30 s de gunicorn; no se cambia `--timeout` (ver
`infra_context.md`). Render
inyecta `RENDER_EXTERNAL_HOSTNAME`, y `settings.py` lo añade a `ALLOWED_HOSTS` y
activa `SECURE_PROXY_SSL_HEADER`. Ver `infra_context.md` §3.

## Docker (Azure Container Apps, en migración)

`Dockerfile` crea la imagen que ejecutará Azure Container Apps; Render no la usa
y sigue desplegando como en el apartado anterior. Se construye en la nube o en
local, siempre con `backend/` como contexto:

```powershell
az acr build --registry <registro> --image swipehome-backend:<etiqueta> backend
docker build -t swipehome-backend backend
```

`.dockerignore` es una lista blanca (solo entran `requirements.txt`,
`manage.py`, `config/`, `accounts/` y `properties/`): el JSON de la cuenta de
servicio o un `.env` dentro de `backend/` no llegan a la imagen. Si se añade
un paquete Python nuevo, hay que incluirlo ahí.

El contenedor escucha en el puerto 8000 (o `PORT`) con gunicorn, 2 workers ×
4 hilos y `--timeout 30`. No lleva secretos: necesita las mismas variables que
Render (`DJANGO_SECRET_KEY`, `FIREBASE_SERVICE_ACCOUNT_JSON`,
`FIREBASE_PROJECT_ID`, `FIREBASE_WEB_API_KEY`, `AZURE_STORAGE_CONNECTION_STRING`,
`AZURE_STORAGE_CONTAINER`) más `ALLOWED_HOSTS` con el dominio del servicio
(fuera de Render no existe `RENDER_EXTERNAL_HOSTNAME`) y las dos nuevas:

- `DJANGO_BEHIND_TLS_PROXY=1`: confía en `X-Forwarded-Proto` del ingress de
  Azure, que termina el TLS. Solo detrás de un proxy así.
- `CORS_ALLOWED_ORIGINS`: origen del frontend en Azure Static Web Apps (p. ej.
  `https://<app>.azurestaticapps.net`), separados por comas. Vacío no permite
  ningún origen, que es lo correcto en local y en Render.

Prueba rápida en local:

```powershell
docker run --rm -p 8000:8000 -e DJANGO_SECRET_KEY=solo-local -e ALLOWED_HOSTS=localhost swipehome-backend
curl.exe http://localhost:8000/api/health   # {"status": "ok"}
```

El job «Docker (backend)» del CI hace esta misma comprobación en cada PR. Ver
`infra_context.md`, apartado «Azure (en migración)».

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

#### Resultado US 6.8: API de perfil y sesión

El comando de emuladores descrito en este README pasó **171 tests** (10 de
noviembre de 2026), incluidos tests de API de ambos roles, edición normalizada,
duplicidad concurrente, cambio de contraseña, continuidad, fallos y logout.
Auth y Firestore usan emuladores locales; Azure Blob permanece con mocks.
No se usaron servicios ni credenciales de producción.

`ProfileSessionIntegrationTests` usa cuentas sintéticas y solicitudes HTTP
reales contra la aplicación Django. Dos PATCH concurrentes con el mismo email
normalizado producen un éxito y un conflicto; el estado final demuestra que la
cuenta perdedora no recibe el cambio de nombre. Un fallo inyectado antes de
`auth.update_user` deja intactos nombre y email. El logout guarda la revocación
en Firestore Emulator, invalida el Bearer anterior para `/api/auth/me`, es
idempotente y no afecta a otra cuenta.

La prueba de contraseña inicia sesión con la nueva contraseña y confirma el
rechazo de la anterior tras el cambio. La respuesta no incluye contraseña ni
hash. Se verifican GET logout = 405 y que una cookie sin Bearer no crea una
revocación. CSRF Django no forma parte del contrato Firebase Bearer; una
petición POST anónima responde 204 por idempotencia, pero no se autentica ni
modifica la persistencia.

En navegador se validaron consulta del perfil, validación cliente sin petición,
error y retry conservando el formulario, confirmación, recarga, error de
contraseña y logout con fallo 500 seguido de retry 204. Auth Emulator gestionó
el inicio de sesión; la API se interceptó, así que las respuestas visuales no
demuestran persistencia del navegador en Firestore.

#### US 6.9: recorrido de perfil desde la interfaz

La verificación visual detallada de ambos roles, edición/cancelación,
confirmación, carga y bloqueo de envíos, validación de contraseña, logout y
rutas tras salir está en [README frontend](../frontend/README.md). Se usó Auth
Emulator con respuestas API interceptadas; no se atribuye persistencia de UI a
Firestore. La cobertura de persistencia, revocación y nuevas credenciales es la
de los tests backend US6.8 con Auth/Firestore Emulator.

## US 4.4–4.7: exploración, decisiones y avisos privados

La adaptación a **Firebase Auth/Firestore** fue autorizada expresamente.
Se conserva el contrato Bearer existente. No hay sesiones por cookies, CSRF
Django ni migraciones ORM; no se añade `csrf_exempt`. Cookies por sí solas no
autentican estos endpoints. La identidad procede de `request.user`, construido
por el servidor con el token verificado, su revocación y el perfil actual.

**LIKE crea un match en estado PENDING y un aviso INTEREST al propietario.**
El match queda pendiente de la decisión posterior del Vendedor (US5). No hay
segundo swipe ni reserva o retirada automática del anuncio.

| Método | Ruta exacta | Rol |
|---|---|---|
| GET | `/api/inmuebles/explorar` | BUYER |
| POST | `/api/inmuebles/{id}/decision` | BUYER |
| GET | `/api/notificaciones` | BUYER / SELLER (solo avisos de la identidad verificada) |

Todos requieren `Authorization: Bearer <ID token Firebase>`.
401 significa token ausente, inválido, caducado o sesión revocada;
403 significa rol incorrecto o perfil ausente. 405 significa método incorrecto.
Los errores son `{"error": "mensaje seguro"}` y los fallos internos, 500.
Las respuestas llevan `Cache-Control: no-store` y no exponen credenciales,
SQL ni trazas. Los 500 permiten reintentar conservando el acceso del cliente.

### GET /api/inmuebles/explorar

Incluye únicamente anuncios `published=true` con todos los campos del esquema
de publicación, fecha y entre 1 y 10 referencias de fotografías.
Excluye cualquier decisión propia, LIKE o PASS; las decisiones y matches de
otros Compradores no excluyen el anuncio.

Respuesta 200 de ejemplo:

```json
{
  "items": [
    {
      "id": "listing-123",
      "title": "Piso luminoso",
      "street": "Calle Mayor 1",
      "city": "Barcelona",
      "postal_code": "08001",
      "description": "Una descripción válida",
      "price": "950.50",
      "surface": "65.50",
      "bedrooms": 2,
      "bathrooms": 1,
      "people": 3,
      "shared_accommodation": false,
      "photos": ["https://example.com/primera.jpg", "https://example.com/segunda.jpg"],
      "created_at": "2026-11-08T10:00:00Z"
    }
  ],
  "next_cursor": null
}
```

`price` y `surface` son cadenas decimales exactas con dos posiciones, a partir
de `price_cents` y `surface_hundredths` existentes. Las fotografías se devuelven
todas, en el orden del array guardado; no se ordenan por URL.
No se exponen el UID interno del propietario ni campos arbitrarios del documento.

### Paginación de ambas consultas GET

| Parámetro | Contrato |
|---|---|
| `limit` | Entero decimal de 1 a 50; predeterminado 20. |
| `cursor` | Cursor opaco de `next_cursor`; omitir en la primera página y codificar al enviarlo en la URL. |

Se rechazan con 400 parámetros desconocidos, repetidos, vacíos, límites inválidos
y cursores inválidos o de otra cuenta/recurso. El cursor está firmado con
`DJANGO_SECRET_KEY`: mantenerla estable; rotarla invalida los cursores previos.
El cursor es opaco, no cifrado, y conserva nanosegundos.

Orden: `created_at DESC, identificador DESC`. La posición es estrictamente una
fecha anterior, o igual fecha con ID menor. No se usa OFFSET. Decidir sobre
las viviendas de páginas anteriores no desplaza ni salta pendientes.
Se busca un elemento adicional para determinar si existe otra página.
`next_cursor` es `null` al terminar. Sin resultados, ambos endpoints devuelven
`200 {"items": [], "next_cursor": null}`.

Los registros nuevos situados antes del cursor se ven al volver a la primera
página; no se promete una instantánea del catálogo. Fecha e ID deben permanecer
inmutables. Exploración consulta anuncios en lotes y decisiones con lecturas
batch; fotos y avisos no provocan consultas por elemento.

### POST /api/inmuebles/{id}/decision

`Content-Type: application/json`. Único campo admitido:

```json
{"decision": "LIKE"}
```

Solo se aceptan cadenas exactas `LIKE` y `PASS`. Otros valores, campos extra
(incluidos IDs de Comprador o propietario), JSON mal formado o estructuras
incorrectas devuelven 400. Un inmueble inexistente, no publicado o incompleto
devuelve 404.

Respuesta LIKE 201, o 200 en un reintento idéntico:

```json
{
  "decision": {
    "id": "clave-canonica",
    "listing_id": "listing-123",
    "value": "LIKE",
    "created_at": "2026-11-08T10:01:00Z"
  },
  "match": {
    "id": "clave-canonica",
    "decision_id": "clave-canonica",
    "listing_id": "listing-123",
    "status": "PENDING",
    "created_at": "2026-11-08T10:01:00Z"
  }
}
```

PASS usa la misma estructura con `value: "PASS"` y `match: null`.

| HTTP | Resultado |
|---|---|
| 201 | Decisión nueva confirmada; LIKE incluye match y aviso en el mismo commit. |
| 200 | Misma decisión previa; mismos identificadores y fechas, sin aviso duplicado. |
| 400 | Cuerpo o decisión inválidos. |
| 401 / 403 | Autenticación o rol incorrectos. |
| 404 | Anuncio no disponible para decidir. |
| 409 | La decisión contraria ya quedó confirmada; no se modifica. |
| 500 | Fallo interno, inconsistencia o contención no resuelta; mensaje seguro. |

### GET /api/notificaciones

Solo devuelve avisos cuyo `recipient_uid` es el SELLER autenticado. No admite
elegir otro destinatario; BUYER obtiene 403.

Respuesta 200 para avisos nuevos de match:

```json
{
  "items": [
    {
      "id": "match-clave-canonica",
      "type": "INTEREST",
      "message": "Tienes un nuevo candidato interesado en tu vivienda.",
      "match_id": "clave-canonica",
      "created_at": "2026-11-08T10:01:00Z",
      "buyer": {"id": "buyer-uid", "name": "Ana"},
      "listing": {"id": "listing-123", "title": "Piso luminoso"}
    }
  ],
  "next_cursor": null
}
```

Nombre y título son instantáneas fijadas al crear el aviso. Se conservan
`type` y `message` del contrato anterior. **Compatibilidad histórica:** los avisos
previos sin match siguen devolviendo solo `id/type/message/created_at`; no se
les inventan identidades ni matches. Los avisos US4 tienen siempre las relaciones
completas. No se marca lectura ni se cambia ningún registro al consultar.

### GET /api/matches

Consulta paginada de matches mutuos confirmados (`status == "CONFIRMED"`).
- Para **BUYER**: devuelve exclusivamente sus viviendas confirmadas con datos completos del inmueble (`listing_item`).
- Para **SELLER**: devuelve exclusivamente matches confirmados de sus viviendas con datos del Comprador y vivienda.
- Admite parámetro opcional `inmueble`: solo permite consultar viviendas relacionadas con el usuario autenticado (403 si pertenece a otro o no hay relación).
- Ordenación: `confirmed_at DESC, __name__ DESC`.

Ejemplo respuesta Comprador (200):
```json
{
  "items": [
    {
      "id": "clave-canonica",
      "status": "CONFIRMED",
      "confirmed_at": "2026-11-10T12:00:00Z",
      "created_at": "2026-11-10T11:00:00Z",
      "seller": {
        "id": "seller-uid",
        "name": "Joan Propietario"
      },
      "listing": {
        "id": "listing-123",
        "title": "Ático en Gràcia",
        "price": "950.00",
        "surface": "65.00",
        "photos": ["https://..."],
        "created_at": "2026-11-08T10:00:00Z"
      }
    }
  ],
  "next_cursor": null
}
```

### GET /api/candidatos

Consulta paginada de candidaturas pendientes (`status == "PENDING"`) para el Vendedor autenticado (`SELLER`).
Un rol `BUYER` recibe 403.
- Admite parámetro opcional `inmueble`: solo permite consultar viviendas del Vendedor (403 si no le pertenece).
- Ordenación: `created_at DESC, __name__ DESC` (por fecha del interés inicial).
- Paginación estable por cursor que previene saltos al confirmar o rechazar candidatos entre páginas.

Ejemplo respuesta Vendedor (200):
```json
{
  "items": [
    {
      "id": "clave-canonica",
      "status": "PENDING",
      "created_at": "2026-11-10T11:00:00Z",
      "buyer": {"id": "buyer-uid", "name": "Ana"},
      "listing": {"id": "listing-123", "title": "Ático en Gràcia"}
    }
  ],
  "next_cursor": null
}
```

### POST /api/matches/{id}/decision-vendedor

Decisión del propietario sobre una candidatura (`SELLER`).
`Content-Type: application/json`. Cuerpo admitido: `{"decision": "LIKE"}` o `{"decision": "PASS"}`.
- Solo el propietario del inmueble asociado puede decidir (404 si no existe o es ajeno).
- Comprueba que la candidatura procede de un interés positivo previo del Comprador.
- `LIKE`: transforma `PENDING` en `CONFIRMED` y guarda `confirmed_at` y `decided_at`.
- `PASS`: transforma `PENDING` en `REJECTED` y guarda `decided_at`.
- No crea un segundo registro de match; actualiza el existente de forma atómica.
- Idempotente: repetir la misma decisión devuelve 200 con el estado actual.
- Conflicto: intentar contradecir una decisión ya tomada (`CONFIRMED` a `PASS` o `REJECTED` a `LIKE`) devuelve 409.

Respuesta 200:
```json
{
  "id": "clave-canonica",
  "status": "CONFIRMED",
  "decided_at": "2026-11-10T12:00:00Z",
  "confirmed_at": "2026-11-10T12:00:00Z"
}
```

### Modelos Firestore, unicidad y transacciones

Se reutilizan `users`, `listings` y `notifications`. La clave canónica es
SHA-256 del JSON ASCII de `[buyer_uid, listing_id]`. Se añaden:

- `swipes/{key}`: `buyer_uid, listing_id, value, created_at`.
- `matches/{key}`: `buyer_uid, listing_id, decision_id, seller_uid, buyer_name, listing_title, status, created_at` (y opcionalmente `decided_at, confirmed_at`).
- `notifications/match-{key}`: destinatario propietario, match, Comprador,
  nombre, vivienda, título, tipo (INTEREST), mensaje y fecha.

El propietario se resuelve inicialmente desde `listings.seller_uid`. El match
representa el interés mutuo pendiente o confirmado sin reservar ni retirar la vivienda.
Un LIKE inicial del Comprador crea un match PENDING y un aviso de interés; la decisión
favorable del Vendedor lo confirma.

Firestore garantiza unicidad de documento y precondición de `create()`.
El servicio central `repository.record_decision` garantiza valores permitidos,
vínculo positivo y coherencia entre documentos; **no son CHECK/FK SQL**.
Las escrituras van en una sola transacción, incluido el aviso. Si falla un
guardado o se rechaza el commit, se revierte el conjunto nuevo.
No se añaden trabajos asíncronos ni callbacks posteriores al commit.

Las peticiones simultáneas comparten la misma clave y convergen; la decisión
contraria recibe 409. Se contemplan abortos durante lecturas y commits,
colisiones de creación y reintentos con transacciones nuevas y espera acotada.
El wrapper transaccional del SDK se instancia por operación, sin compartir
estado de reintento entre hilos.
Los datos inconsistentes producen 500, sin reparación silenciosa.
La persistencia reside en Firestore y sobrevive al logout o reinicio de Django.

Si se pierde la respuesta después de un commit remoto, puede existir el
conjunto **completo** pese al error HTTP; repetir la misma decisión recupera
su resultado sin duplicarlo. No se promete deshacer un commit remoto aceptado.

### Evolución del esquema e índices

La evolución es aditiva: no hay migraciones Django que aplicar, datos borrados,
tablas paralelas ni cambio de base de datos. Las colecciones nuevas se crean
con su primera escritura. `backend/db.sqlite3` residual no se usa ni se modifica.

El código previo no tiene escritores de `swipes/matches`. No se inspeccionó
producción. Si existen datos externos en esas colecciones, comprobar antes del
despliegue su compatibilidad con las claves y relaciones anteriores; no se
transforman datos desconocidos automáticamente.

Se conserva el índice de avisos y se añade el de exploración en
[firestore.indexes.json](firestore.indexes.json). Desde `backend/`, con Firebase
CLI autenticado y permiso de administrar índices:

```powershell
npx.cmd --yes --package firebase-tools@15.34.1 firebase deploy --only firestore:indexes --project swipehome-a51d7 --config firebase.json
```

Este comando publica únicamente índices. Comparar antes la definición con los
índices remotos para conservar los ajenos a la tarea; esperar a que estén
habilitados. **No se ha ejecutado contra producción.** Sin los índices requeridos,
Firestore puede rechazar consultas y la API devuelve 500 seguro.
Se mantienen cerradas las reglas de acceso directo de clientes.
Las reglas de `tests/firestore.rules` son exclusivamente de los emuladores.

### Comprobar US4 y regresiones

Desde `backend/`:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe manage.py test accounts properties --verbosity 2
```

Sin emuladores: **170 pruebas descubiertas, 138 correctas y 32 integraciones
omitidas**. Para la verificación completa hacen falta Node 24 y Java 21.
Este comando inicia/detiene Auth y Firestore Emulator en loopback
(9099 y 8080), sin usar credenciales ni producción:

```powershell
npx.cmd --yes --package firebase-tools@15.34.1 firebase emulators:exec --project demo-swipehome-us4 --only auth,firestore --config tests/firebase.json ".venv\Scripts\python.exe -B manage.py test accounts properties --verbosity 2"
```

Resultado comprobado: **170 pruebas correctas, sin omisiones**, incluidos
concurrencia con barreras/hilos y Firestore real emulado, rollback de los tres
guardados y rechazo de commit, unicidad, privacidad, paginación tras decidir,
persistencia y registro/login/publicación. El recorrido de Auth real simula
únicamente Azure Blob Storage. `check`, `makemigrations --check --dry-run`, `pip check`
y `git diff --check` también pasan. No hay lint/formatter Python configurado.
CI está preparado para ejecutar esta misma suite con Java 21.
El emulador no demuestra el despliegue de índices ni el funcionamiento de
Storage o Firestore en producción.

### Ejemplo desde un consumidor Firebase existente

El SDK ya inicia sesión según el contrato del proyecto. Con el objeto
`currentUser` autenticado del SDK, sin guardar tokens en el repositorio:

```javascript
const headers = {Authorization: "Bearer " + await currentUser.getIdToken()};
const pageResponse = await fetch("/api/inmuebles/explorar?limit=20", {headers});
const page = await pageResponse.json();
const home = page.items[0];
if (home) {
  const response = await fetch("/api/inmuebles/" + encodeURIComponent(home.id) + "/decision", {
    method: "POST",
    headers: {...headers, "Content-Type": "application/json"},
    body: JSON.stringify({decision: "LIKE"})
  });
  console.log(response.status, await response.json());
}
if (page.next_cursor) {
  const next = await fetch("/api/inmuebles/explorar?limit=20&cursor=" +
    encodeURIComponent(page.next_cursor), {headers});
  console.log(await next.json());
}
```

Como SELLER, obtener su propio token y consultar:

```javascript
const response = await fetch("/api/notificaciones?limit=20", {
  headers: {Authorization: "Bearer " + await currentUser.getIdToken()}
});
console.log(response.status, await response.json());
```

No se necesitan cookies ni token CSRF para este contrato Bearer.
Detalle de arquitectura, garantías, compatibilidad y pruebas:
[US4 backend](<../Agents mds/us4_backend.md>).

## US 7.4: recepción y consulta de notificaciones

`GET /api/notificaciones` requiere ID token Firebase vigente y perfil BUYER o
SELLER. El UID se obtiene únicamente de `request.user`; `uid`,
`recipient_uid` y cualquier otro selector de cuenta se rechazan. La lectura
filtra por `recipient_uid`, ordena `created_at` e ID descendentes y no escribe
en Firestore. Los cursores firmados están ligados a la cuenta. Las respuestas
incluyen `items` y `next_cursor`.

La comprobación del 10 de noviembre de 2026 pasó **172 tests** con Auth y
Firestore Emulator de proyecto demo; Azure Blob se simula. El test de flujo
integrado crea el aviso del LIKE para el propietario y comprueba su lectura,
logout, rechazo del token revocado y persistencia tras nuevo inicio de sesión.
Otra prueba escribe fixtures locales destinados a BUYER, SELLER y una tercera
cuenta y verifica el aislamiento, parámetros manipulados y que las lecturas no
alteran `swipes` ni `matches`. PASS no crea aviso y los reintentos LIKE no
duplican aviso según las pruebas US4 existentes. No se usaron Firebase ni
Azure de producción.

La pantalla consulta al entrar, pagina con `next_cursor`, actualiza sin
duplicados, presenta fecha/hora local junto al mensaje y distingue carga,
vacío y error reintentable. `npm test` pasa 25 pruebas, `npm run lint` y
`npm run build` finalizan; lint conserva advertencias del repositorio. La
prueba visual usa Auth Emulator y respuestas API interceptadas; el navegador
no consulta Firestore directamente. Se contrastaron viewports 1280×900 y
390×844 emulados, no dispositivos físicos.

**Límite de avisos US5:** existe el endpoint de confirmación del vendedor, pero
no produce un aviso de confirmación para BUYER. La API puede consultar avisos BUYER si ya
están persistidos, pero no se afirma que la confirmación los genere. Esa parte
queda sin verificar y fuera de esta implementación de consulta.


## US8: preferencias de búsqueda (backend)

Contrato completo, campos/mapeo US3, errores, persistencia, precisión, localidades,
cursores y flujo de integración: [US8 backend](<../Agents mds/us8_backend.md>).
Todas estas operaciones requieren Firebase Bearer y rol **BUYER**:

| Método | Ruta | Respuesta |
|---|---|---|
| GET | `/api/exploracion/filtros` | 200, configuración completa propia, nulls si no existe. |
| PUT | `/api/exploracion/filtros` | JSON de sustitución completa; 200 con configuración canónica persistida. |
| DELETE | `/api/exploracion/filtros` | 200 con configuración sin restricciones; idempotente. |
| GET | `/api/inmuebles/opciones-filtro` | 200 `{"cities":["Barcelona","Madrid"]}`, publicadas completas, únicas y ordenadas. |
| GET | `/api/inmuebles/explorar` | Contrato US4, ahora aplica preferencias persistidas y exclusiones LIKE/PASS propias. |

PUT de ejemplo: `{"city":" Barcelona ","min_price":"0","max_price":"950.50","is_shared":false}`.
Devuelve `{"city":"Barcelona","postal_code":null,"min_price":"0.00","max_price":"950.50","min_area":null,"max_area":null,"bedrooms":null,"min_bathrooms":null,"people_offered":null,"is_shared":false}`.
GET inicial, PUT `{}` y DELETE devuelven las diez claves con null.
Los omitidos en PUT borran restricciones anteriores; no es PATCH.

400 validación `{"errors":{"max_price":"..."}}` o parámetros/cursores
`{"error":"..."}`; 401 credenciales inválidas/ausentes/revocadas; 403 rol no
permitido; 405 método no admitido; 500 fallo interno seguro. No hay cookies ni
CSRF de sesiones Django; se reutiliza la verificación Bearer existente.
Las preferencias residen en `search_preferences/{uid}` mediante una escritura
atómica sin borrado previo; errores no se presentan como éxito. Restablecer
conserva decisiones, matches y exclusiones. Cursores firmados ligados a UID,
propósito y configuración canónica; cambios incompatibles reciben 400.

Para US8.2: GET preferencias -> PUT/DELETE y esperar confirmación -> descartar
cursor -> GET explorar sin cursor. Si falla solo explorar, reintentarlo sin
revertir ni presentar como fallido el guardado. UI pendiente: bloqueo de envíos y
swipes antiguos, descarte de respuestas tardías, filtros activos, errores y acciones.
Estado vacío de UI: «No hay viviendas pendientes que coincidan con tus filtros.
Prueba a ampliar tus criterios de búsqueda.» La API mantiene lista vacía y cursor null.

Pruebas afectadas desde backend (Auth/Firestore Emulator demo, Azure simulado):

```powershell
npx.cmd --yes --package firebase-tools@15.34.1 firebase emulators:exec --project demo-swipehome-us4 --only auth,firestore --config tests/firebase.json ".venv\Scripts\python.exe -B manage.py test properties.test_preferences properties.test_firestore_preferences properties.test_discovery properties.test_firestore properties.test_firestore_matches --verbosity 1"
```

La suite completa usa el comando CI ya documentado `manage.py test accounts properties`;
incluye automáticamente los nuevos módulos. Resultados de esta entrega en
[resultado.md](../resultado.md). No hay lint/formatter Python configurado ni índices
nuevos. No se han ejecutado despliegues.


Validación de esta entrega (15/11/2026): **211 tests OK, sin omisiones**, con Auth
Emulator y Firestore Emulator (suite completa accounts/properties); 66 pruebas
afectadas pasaron antes de la regresión completa. `manage.py check`,
`makemigrations --check --dry-run`, `pip check` y `git diff --check` también pasan.
Ejecución local Windows/Python 3.13; no es un resultado remoto de CI ni un despliegue.


## US9.4–9.6: selección definitiva

Contrato y garantías: [US9 backend](<../Agents mds/us9_backend.md>).
La selección se hace por candidatura para una vivienda; no modifica `people` ni
candidaturas en otras viviendas. Firebase Bearer y roles verificados del perfil.

- `GET/POST /api/propuestas`: historial propio paginado / creación SELLER con
  `{"listing_id":"...","match_id":"...","request_id":"clave-nueva"}`.
- `GET /api/propuestas/{id}`: detalle privado, condiciones actuales y vendedor.
- `POST /api/propuestas/{id}/aceptar`, `/rechazar` (BUYER), `/cancelar` (SELLER): `{}`.
- `PATCH /api/inmuebles/{id}`: edición de todos los campos canónicos US3 sin fotos.
- `PUT /api/inmuebles/{id}/disponibilidad`: `{"availability":"ACTIVE","version":N}` o PAUSED.

PENDING pasa a ACCEPTED/REJECTED/CANCELLED; ACCEPTED es definitivo y cierra la
vivienda con motivo «Alquiler acordado». PENDING bloquea edición/disponibilidad.
Crear admite ACTIVE y PAUSED sin cambiarlos. Rechazar/cancelar libera el bloqueo.
201 en creación nueva; 200 en reintento idéntico y resoluciones. Una clave usada
con contenido distinto o una transición incompatible devuelve 409. Datos inválidos
400, autenticación 401, rol 403, recurso ajeno/inexistente 404, fallo interno 500.

El repositorio central transacciona propuesta, control privado por vivienda,
idempotencia, cierre y avisos US7 deduplicados. Para más de 100 destinatarios de
cierre, guarda eventos duraderos y los procesa en lotes reintentables; la API
intenta diez lotes y el comando `manage.py process_selection_notifications --limit 100`
recupera los restantes. Debe programarse periódicamente en producción.
Todos usan timestamps del servidor.
Se añaden `selection_proposals`, `selection_requests`, `listing_selections`,
`selection_notification_events` y dos
índices versionados. No hace falta backfill: disponibilidad ausente equivale a
ACTIVE para anuncios publicados. Los matches mantienen su estado y muestran
`listing.availability`/`closure_reason`. Las referencias al seleccionado no salen
en anuncios ni avisos de otros candidatos. No se han desplegado índices ni reglas.


Verificación US9 (16/11/2026): **228 tests correctos, sin omisiones**, suite
completa `accounts properties` con Auth Emulator y Firestore Emulator Standard
en loopback (`demo-swipehome-us4`), Python 3.13 y Java 21. Incluye 17 pruebas US9
nuevas: permisos y contratos, estados y bloqueos, idempotencia, concurrencia,
rollback de avisos/eventos, recuperación tras fallo entre lotes, privacidad,
historial, otras viviendas, autenticación real emulada y denegación REST por Rules.
Azure se mantiene simulado por las pruebas existentes. `manage.py check`,
`makemigrations --check --dry-run`, `pip check`, sintaxis Python/JSON y
`git diff --check` correctos. No se han usado servicios de producción ni se han
realizado despliegues, commits o push. Los índices compuestos deben publicarse y
comprobarse en producción: el emulador no certifica su disponibilidad. También
queda por configurar allí la ejecución periódica del comando de recuperación.

## US11.3–US11.7 · Conversaciones con match

BUYER y SELLER pueden abrir una sola conversación por match CONFIRMED,
consultar sus cabeceras y enviar o paginar mensajes. Los envíos usan un UUID
idempotente y un commit Firestore para mensaje, resumen y aviso US7. El
historial permanece accesible tras pausar o cerrar un anuncio.

El [contrato US11](<../Agents mds/us11_backend.md>) incluye rutas, campos,
códigos de error, índices, paginación y un ejemplo con dos cuentas. Para ejecutar
la verificación aislada desde `backend/`:

```powershell
npx.cmd --yes --package firebase-tools@15.34.1 firebase emulators:exec --project demo-swipehome-us4 --only auth,firestore --config tests/firebase.json ".venv\Scripts\python.exe -B manage.py test properties.test_conversations --verbosity 2"
```

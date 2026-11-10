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
| `GET` | `/api/notificaciones` | Avisos privados SELLER paginados: 200 / 400 / 401 / 403 / 500 |
| `GET` | `/api/inmuebles` | Inmuebles publicados del SELLER autenticado: 200 / 401 / 500 |
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

## US 4.4–4.7: exploración, decisiones y avisos privados

La adaptación a **Firebase Auth/Firestore** fue autorizada expresamente.
Se conserva el contrato Bearer existente. No hay sesiones por cookies, CSRF
Django ni migraciones ORM; no se añade `csrf_exempt`. Cookies por sí solas no
autentican estos endpoints. La identidad procede de `request.user`, construido
por el servidor con el token verificado, su revocación y el perfil actual.

**LIKE crea directamente el match y un aviso al propietario.** No hay
aceptación del Vendedor, segundo swipe ni reserva o retirada automática del anuncio.

| Método | Ruta exacta | Rol |
|---|---|---|
| GET | `/api/inmuebles/explorar` | BUYER |
| POST | `/api/inmuebles/{id}/decision` | BUYER |
| GET | `/api/notificaciones` | SELLER |

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
      "type": "MATCH",
      "message": "Tienes un nuevo match.",
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

### Modelos Firestore, unicidad y transacciones

Se reutilizan `users`, `listings` y `notifications`. La clave canónica es
SHA-256 del JSON ASCII de `[buyer_uid, listing_id]`. Se añaden:

- `swipes/{key}`: `buyer_uid, listing_id, value, created_at`.
- `matches/{key}`: `buyer_uid, listing_id, decision_id, created_at`.
- `notifications/match-{key}`: destinatario propietario, match, Comprador,
  nombre, vivienda, título, tipo, mensaje y fecha.

El propietario se resuelve desde `listings.seller_uid`. Un match no almacena
otro propietario, reserva ni retira la vivienda. Un LIKE completo tiene un
match y un aviso; PASS no los crea.

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

Sin emuladores: **152 pruebas descubiertas, 128 correctas y 24 integraciones
omitidas**. Para la verificación completa hacen falta Node 24 y Java 21.
Este comando inicia/detiene Auth y Firestore Emulator en loopback
(9099 y 8080), sin usar credenciales ni producción:

```powershell
npx.cmd --yes --package firebase-tools@15.34.1 firebase emulators:exec --project demo-swipehome-us4 --only auth,firestore --config tests/firebase.json ".venv\Scripts\python.exe -B manage.py test accounts properties --verbosity 2"
```

Resultado comprobado: **152 pruebas correctas, sin omisiones**, incluidos
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

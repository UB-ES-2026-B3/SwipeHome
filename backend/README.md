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
| `GET` | `/api/inmuebles/explorar` | Viviendas pendientes BUYER paginadas. |
| `POST` | `/api/inmuebles/{id}/decision` | Decisión BUYER; LIKE crea candidatura pendiente: 201 / 200 / 400 / 401 / 403 / 404 / 409 / 500 |
| `GET` | `/api/matches` | Matches confirmados propios de BUYER o SELLER, paginados. |
| `GET` | `/api/matches/candidatos` | Candidaturas LIKE pendientes de viviendas propias, solo SELLER. |
| `POST` | `/api/matches/candidaturas/{decision_id}/decision` | Aceptar/rechazar candidatura propia, solo SELLER. |
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

Histórico de la implementación original, actualizado en el siguiente apartado
por US5.8. El contrato vigente separa candidatura LIKE pendiente y match
confirmado: no usar las descripciones históricas de match inmediato como estado
actual.

La adaptación a **Firebase Auth/Firestore** fue autorizada expresamente.
Se conserva el contrato Bearer existente. No hay sesiones por cookies, CSRF
Django ni migraciones ORM; no se añade `csrf_exempt`. Cookies por sí solas no
autentican estos endpoints. La identidad procede de `request.user`, construido
por el servidor con el token verificado, su revocación y el perfil actual.

**LIKE crea una candidatura pendiente; no crea un match confirmado.** El
Vendedor propietario puede aceptarla o rechazarla. Solo la aceptación crea el
match y un aviso privado al Comprador. PASS no crea candidatura, match ni aviso.
El match no reserva ni retira automáticamente el anuncio.

| Método | Ruta exacta | Rol |
|---|---|---|
| GET | `/api/inmuebles/explorar` | BUYER |
| POST | `/api/inmuebles/{id}/decision` | BUYER |
| GET | `/api/matches` | BUYER / SELLER (solo matches de la identidad verificada) |
| GET | `/api/matches/candidatos` | SELLER (solo viviendas propias) |
| POST | `/api/matches/candidaturas/{decision_id}/decision` | SELLER (solo candidatura y vivienda propias) |
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

Respuesta LIKE 201, o 200 en un reintento idéntico mientras siga pendiente:

```json
{
  "decision": {
    "id": "clave-canonica",
    "listing_id": "listing-123",
    "value": "LIKE",
    "seller_decision": "PENDING",
    "created_at": "2026-11-08T10:01:00Z"
  },
  "match": null
}
```

PASS usa la misma estructura con `value: "PASS"` y `match: null`.
Si el Comprador reintenta después de una aceptación, recibe `seller_decision:
ACCEPT` y el match existente; no se cambia su ID ni fecha.

| HTTP | Resultado |
|---|---|
| 201 | Decisión nueva guardada; LIKE queda pendiente y no incluye match. |
| 200 | Reintento de la misma decisión; no duplica datos. Si ya fue aceptada, devuelve el match existente. |
| 400 | Cuerpo o decisión inválidos. |
| 401 / 403 | Autenticación o rol incorrectos. |
| 404 | Anuncio no disponible para decidir. |
| 409 | La decisión contraria ya quedó confirmada; no se modifica. |
| 500 | Fallo interno, inconsistencia o contención no resuelta; mensaje seguro. |

### GET /api/matches y GET /api/matches/candidatos

`GET /api/matches` admite BUYER y SELLER y devuelve únicamente matches
confirmados relacionados con la identidad verificada.
`GET /api/matches/candidatos` solo admite SELLER y devuelve LIKE pendientes
para viviendas propias, con el comprador y la ficha de vivienda. Ambos aceptan
la paginación anterior. No se aceptan UID de cliente para seleccionar al usuario.

### POST /api/matches/candidaturas/{decision_id}/decision

Solo SELLER y JSON exacto `{"decision":"ACCEPT"}` o
`{"decision":"REJECT"}`. La propiedad se comprueba contra el `seller_uid` de la
vivienda dentro de la transacción. Candidatura inexistente o ajena devuelve 404;
una transición contradictoria devuelve 409; reintentar la transición ya
confirmada devuelve 200 sin alterar fechas.

ACCEPT actualiza la candidatura y crea el match y el aviso al Comprador en un
único commit. REJECT guarda el estado y elimina la candidatura de pendientes,
sin crear match ni aviso. Un LIKE pendiente no aparece en ninguna lista de
matches confirmados.

### GET /api/notificaciones

Solo devuelve avisos cuyo `recipient_uid` corresponde a la identidad verificada;
BUYER y SELLER pueden consultar los propios, sin seleccionar destinatario.
La aceptación produce un aviso privado al Comprador:

```json
{
  "items": [
    {
      "id": "buyer-match-clave-canonica",
      "type": "MATCH",
      "message": "El propietario ha confirmado tu interés.",
      "match_id": "clave-canonica",
      "created_at": "2026-11-08T10:01:00Z",
      "buyer": {"id": "buyer-uid", "name": "Ana"},
      "listing": {"id": "listing-123", "title": "Piso luminoso"}
    }
  ],
  "next_cursor": null
}
```

Nombre y título son instantáneas fijadas al confirmar. **Compatibilidad histórica:**
los avisos previos sin match siguen devolviendo solo `id/type/message/created_at`;
no se les inventan relaciones. No se marca lectura ni se cambia ningún registro
al consultar.

### Modelos Firestore, unicidad y transacciones

Se reutilizan `users`, `listings` y `notifications`. La clave canónica es
SHA-256 del JSON ASCII de `[buyer_uid, listing_id]`. Se añaden:

- `swipes/{key}`: `buyer_uid, listing_id, value, created_at`.
- LIKE añade `seller_uid, buyer_name, seller_decision=PENDING`; al decidir el
  Vendedor se fijan `seller_decision=ACCEPT|REJECT` y `seller_decided_at`.
- `matches/{key}`: `buyer_uid, seller_uid, listing_id, decision_id, created_at`;
  solo se escribe al aceptar.
- `notifications/buyer-match-{key}`: destinatario Comprador, match, comprador,
  nombre, vivienda, título, tipo, mensaje y fecha; solo se escribe al aceptar.

El propietario se verifica desde `listings.seller_uid`. Un match no reserva ni
retira la vivienda. Una candidatura LIKE no equivale a un match; PASS no crea
candidatura ni aviso.

Firestore garantiza unicidad de documento y precondición de `create()`.
`repository.record_decision` y `repository.transition_seller_decision` garantizan
valores permitidos, vínculo positivo y coherencia entre documentos; **no son
CHECK/FK SQL**. La decisión inicial, y después la transición/match/aviso, son
commits transaccionales separados. Un fallo al aceptar revierte todo lo escrito
en esa transición y conserva la candidatura pendiente.

Solicitudes iniciales simultáneas comparten una clave y convergen; transiciones
SELLER simultáneas contradictorias tienen un único ganador y la otra devuelve
409. Se contemplan abortos durante lecturas y commits,
colisiones de creación y reintentos con transacciones nuevas y espera acotada.
El wrapper transaccional del SDK se instancia por operación, sin compartir
estado de reintento entre hilos.
Los datos inconsistentes producen 500, sin reparación silenciosa.
La persistencia reside en Firestore y sobrevive al logout o reinicio de Django.

Si se pierde la respuesta después de un commit remoto, puede existir el
conjunto **completo** pese al error HTTP; repetir la misma decisión o transición
recupera su resultado sin duplicarlo. No se promete deshacer un commit remoto aceptado.

### Evolución del esquema e índices

La evolución es aditiva: no hay migraciones Django que aplicar, datos borrados,
tablas paralelas ni cambio de base de datos. Las colecciones nuevas se crean
con su primera escritura. `backend/db.sqlite3` residual no se usa ni se modifica.

El código previo no tiene escritores de `swipes/matches`. No se inspeccionó
producción. Si existen datos externos en esas colecciones, comprobar antes del
despliegue su compatibilidad con las claves y relaciones anteriores; no se
transforman datos desconocidos automáticamente.

Se conservan los índices existentes y se añaden los de candidaturas y matches en
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

Este comando inicia/detiene Auth y Firestore Emulator en loopback (9099 y 8080),
sin usar credenciales ni producción:

```powershell
npx.cmd --yes --package firebase-tools@15.34.1 firebase emulators:exec --project demo-swipehome-us4 --only auth,firestore --config tests/firebase.json ".venv\Scripts\python.exe -B manage.py test accounts properties --verbosity 2"
```

Resultado de US 4.9, ejecutado el 10 de noviembre de 2026: **166 pruebas
correctas, sin omisiones**, con Auth y Firestore Emulator. Incluye solicitudes
realmente simultáneas mediante barreras, hilos y clientes HTTP separados;
comprobación del estado Firestore después de cada operación/rollback; una prueba
de rol integrada para los tres endpoints; Azure Blob permanece simulado donde
lo necesita el recorrido de publicación. La ejecución no utilizó Firebase ni
Azure de producción. El emulador no demuestra el despliegue de índices ni el
funcionamiento en producción.

#### US 4.9: evidencia histórica por criterio de aceptación

Esta tabla registra la verificación de US4.9 antes de US5.8; su semántica de
match inmediato está supersedida por la evidencia actual de US5.8 al final de
este README.

| CA | Prueba y método | Resultado y límite |
|---|---|---|
| CA-01 — Acceso al explorador | `test_all_three_endpoints_enforce_roles_without_persisting_changes` y `test_authentication_and_buyer_permissions_for_both_endpoints`: BUYER consulta y decide; vendedor/BUYER en endpoint no permitido reciben 403 y sin token 401. | **Parcial (solo API):** autenticación/autorización y exploración están verificadas; inicio/ruta de interfaz no pertenece a esta US. La prueba integrada de roles usa verifier/perfil mockeados; Firestore es emulado. |
| CA-02 — Información y fotografías | `test_explore_excludes_only_own_decisions_and_preserves_all_photos` y `ListingContractTests.test_all_public_fields_and_ordered_photos_without_internal_data`: respuesta con datos del anuncio y todas las URLs de foto en el orden persistido. | **Parcial (solo API):** contrato, datos y orden pasan con Firestore Emulator; no se verifica mostrar tarjeta ni recorrer fotos en UI, ni recuperar los blobs de Azure. |
| CA-03 — Creación del match | Comportamiento previo a US5.8: un LIKE se confirmaba inmediatamente. | **Histórico, supersedido:** el contrato actual crea match solo tras ACCEPT del Vendedor. |
| CA-04 — Aviso al Vendedor | Comportamiento previo a US5.8: aviso generado al recibir LIKE. | **Histórico, supersedido:** el contrato actual crea aviso al Comprador tras ACCEPT; la candidatura se lista por API del propietario. |
| CA-05 — Descarte persistente | `test_pass_creates_only_decision_and_no_notice`, `test_explore_excludes_only_own_decisions_and_preserves_all_photos` y `test_empty_and_exact_limit_pages_have_no_next_cursor`: PASS persiste sin match/aviso y deja de aparecer al mismo comprador. | **Pasa en API/persistencia local:** UI de «No me interesa» no verificada en esta US. |
| CA-06 — Independencia entre Compradores | `test_two_buyers_create_independent_matches_with_same_home`: dos Compradores generan matches separados para la misma vivienda. | **Pasa con Firestore Emulator.** |
| CA-07 — Continuidad y fin de la exploración | `test_pagination_ties_previous_page_decisions_and_last_page`, `test_scan_multiple_batches_of_decided_homes_without_skip_or_n_plus_one` y `test_empty_and_exact_limit_pages_have_no_next_cursor`: se decide en página previa, se obtiene la siguiente pendiente y la API devuelve lista vacía al terminar. | **Parcial (solo API):** cursor y fin de resultados pasan; mostrar la siguiente tarjeta y el mensaje de fin en interfaz no se verificó en esta US. |
| CA-08 — Fallos y reintentos | `test_each_staged_write_failure_rolls_back_entire_operation`, `test_rejected_commit_does_not_persist_any_staged_document`, `test_same_decision_retries_return_identical_records`, `test_simultaneous_identical_likes_converge_to_same_pending_candidate` y `test_internal_failures_are_safe_for_both_endpoints`: se inspeccionan errores, rollback, respuesta idempotente y conteos finales. | **Parcial (solo backend):** errores y reintento sin duplicados pasan en emulador; aviso visual del problema y control para reintentar en UI no se verificaron en esta US. |

La suite confirma la persistencia local emulada y usa fallos de escritura
inyectados para algunos escenarios. No prueba Firebase/Azure de producción.

#### US 4.10: recorrido integrado publicación-exploración-match (histórico)

La siguiente ejecución es anterior a US5.8 y documenta el comportamiento de
ese momento; la confirmación inmediata descrita aquí ya no es el contrato vigente.

En la ejecución conjunta de US4.10, la suite pasó **167 tests** con el comando
anterior. `FirebaseFlowTests.test_published_multi_photo_listings_survive_full_buyer_flow`
registra un Vendedor y dos Compradores mediante Auth Emulator, publica dos
anuncios válidos con dos fotografías ordenadas cada uno, y consulta el
explorador con datos persistidos en Firestore Emulator. Después comprueba que
LIKE crea match/aviso al propietario, PASS no crea ninguno, el mismo Comprador
continúa excluyendo los inmuebles tras cerrar y volver a iniciar sesión, un
reintento devuelve el match existente, y otro Comprador crea su propio match
para la misma vivienda. Azure Blob se simula y sus URLs se conservan ordenadas.

La parte de navegador se verificó aparte con Auth Emulator y respuestas de API
interceptadas: esto cubre presentación e interacción, no persistencia del
navegador en Firestore. No se usaron Firestore ni Azure de producción.

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

La comprobación histórica del 10 de noviembre de 2026 pasó **172 tests** con Auth y
Firestore Emulator de proyecto demo; Azure Blob se simula. El test de flujo
integrado de esa US creaba el aviso del LIKE para el propietario y comprobaba su lectura,
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

US5.8 añade el productor de aviso al Comprador al aceptar una candidatura; su
persistencia en Firestore Emulator y lectura por el usuario se verifican en la
sección siguiente.

## US5.8: APIs, permisos y transiciones del match

El recorrido implementado separa la decisión del Comprador del match confirmado:
LIKE persiste una candidatura PENDING sin match/aviso; el propietario puede
consultar sus candidatos y aceptar o rechazar. ACCEPT crea el match y el aviso
para el Comprador en una transacción; REJECT persiste el rechazo y no genera
match ni aviso. Las listas de matches se filtran por UID autenticado y solo
incluyen decisiones aceptadas. Otro Comprador puede interesarse por la misma
vivienda de forma independiente.

La suite se ejecutó con el comando de emuladores indicado en este README:
Auth y Firestore Emulator locales, Azure Blob mockeado, sin credenciales ni
servicios de producción. **Resultado final: 182 tests, todos pasan**, sin
omisiones; `manage.py check` no detectó incidencias. La primera suite detectó
un error de serialización del cursor de candidatos; se normalizaron timestamps
antes de firmar/devolver páginas y la suite completa se repitió con éxito.
Después se añadió una comprobación de retry del Comprador tras REJECT; el test
de transición se volvió a ejecutar de forma aislada en el emulador y pasó.

| CA US5 | Evidencia automatizada | Resultado / límite |
|---|---|---|
| CA-01 — Consulta de matches del Comprador | `test_accept_and_reject_are_persistent_idempotent_and_independent`, `test_two_buyers_create_independent_matches_with_same_home`, `FirebaseFlowTests.test_published_multi_photo_listings_survive_full_buyer_flow`; GET `/api/matches` filtra BUYER. | **Pasa con Firestore Emulator**; pantalla añadida y verificada en US5.9. |
| CA-02 — Interés mutuo obligatorio | `test_like_creates_one_pending_candidate_without_confirming_a_match`, `test_accept_and_reject_are_persistent_idempotent_and_independent`; LIKE deja lista confirmada vacía hasta ACCEPT. | **Pasa con Firestore Emulator.** |
| CA-03 — Consulta de candidatos del Vendedor | `test_candidates_and_matches_are_scoped_by_verified_owner_and_role`, `test_match_and_candidate_lists_paginate_and_return_empty_distinctly`; candidatos incluyen comprador y vivienda y están filtrados por vendedor. | **Pasa con Firestore Emulator**; interfaz añadida y verificada en US5.9. |
| CA-04 — Confirmación del match | `test_accept_and_reject_are_persistent_idempotent_and_independent`, `FirebaseFlowTests.test_published_multi_photo_listings_survive_full_buyer_flow`; aceptación produce match para ambas listas. | **Pasa con Firestore Emulator.** |
| CA-05 — Rechazo de candidatura | `test_accept_and_reject_are_persistent_idempotent_and_independent`; REJECT desaparece de pendientes y no crea match ni aviso. | **Pasa con Firestore Emulator.** |
| CA-06 — Privacidad e independencia | `test_candidates_and_matches_are_scoped_by_verified_owner_and_role`, `test_two_buyers_create_independent_matches_with_same_home`; IDs/roles ajenos reciben 403/404 y la otra candidatura permanece intacta. | **Pasa con emulador**; Auth verifier es mock en tests de permisos, real en flujo integrado. |
| CA-07 — Persistencia y ausencia de duplicados | `test_accept_and_reject_are_persistent_idempotent_and_independent`; reintentos comprueban IDs y fechas sin cambios. | **Pasa con Firestore Emulator.** |
| CA-08 — Listas vacías y errores | `test_match_and_candidate_lists_paginate_and_return_empty_distinctly`, `MatchApiTests.test_invalid_payloads_identifiers_and_query_are_rejected`, `test_simultaneous_accept_and_reject_have_one_atomic_winner`, `test_accept_creation_failures_roll_back_decision_match_and_notice`. | **Pasa con mocks y emulador**; falla de persistencia inyectada y carrera realmente concurrente, con estado final inspeccionado. |

Suposiciones: `decision_id` (clave canónica buyer-vivienda) identifica la
candidatura; BUYER puede repetir LIKE para recuperar el estado/match actual,
pero no revertir una decisión SELLER. Los matches históricos con decisión LIKE
y documento match preexistente se leen como aceptados; no se migran datos
externos. El aviso se genera al aceptar y se entrega al Comprador; no se añadió
pantalla para revisar candidatos ni matches. Los índices fueron modificados en
`firestore.indexes.json`, pero no se desplegaron ni verificaron en producción.
BuyerHome se ajustó para confirmar respuestas PENDING, ACCEPT recuperadas tras
un retry y el resultado REJECT, sin mostrar un match antes de tiempo. `npm test` pasó 25 tests; `npm run lint` y
`npm run build` terminaron correctamente. Lint conserva advertencias del
repositorio (efectos con setState, import no usado y Fast Refresh); no se
abordaron por ser ajenas a US5.8. En aquel corte no se verificó la interfaz con navegador
ni hardware móvil; la verificación visual queda ampliada en US5.9.

Cambios funcionales incluidos: endpoints `GET /api/matches`,
`GET /api/matches/candidatos`, `POST /api/matches/candidaturas/{id}/decision`,
transición transaccional e idempotente, filtros por propiedad/rol, paginación,
índices Firestore, aviso de aceptación al Comprador y ajuste del explorador para
mostrar interés pendiente en lugar de anunciar un match inmediato.

## US5.9: recorrido integrado Comprador–Vendedor

US5.9 añade la interfaz protegida `/mis-matches` para BUYER y SELLER y el panel
«Candidaturas pendientes» del Vendedor. BuyerHome mantiene la confirmación de
interés enviado sin presentarlo como match. El panel del Vendedor identifica
Comprador y vivienda, ofrece ACCEPT/REJECT con bloqueo de envíos repetidos y
mantiene disponible el reintento tras errores. Las pantallas muestran cargas,
listas vacías, errores y reintentos; solo una respuesta coherente elimina la
candidatura de pendientes.

El recorrido persistente se verificó con Auth y Firestore Emulator mediante
`FirebaseFlowTests.test_published_multi_photo_listings_survive_full_buyer_flow`:
un Vendedor publica dos viviendas, dos Compradores muestran interés, el
Vendedor acepta una candidatura y rechaza otra. Se comprobaron listas privadas
de ambos roles, continuidad al re-login, el estado final tras REJECT y un retry
de ACCEPT con el mismo match. La suite completa indicada en este README pasó
**184 tests**, sin omisiones; Azure Blob usa mocks y no se usaron Firebase/Azure
de producción.

| CA US5 | Evidencia automatizada | Resultado / límite |
|---|---|---|
| CA-01 — Matches del Comprador | `test_published_multi_photo_listings_survive_full_buyer_flow` consulta GET `/api/matches` como ambos Compradores. | **Pasa con Firestore Emulator**; la presentación visual se prueba con API mock local. |
| CA-02 — Interés mutuo obligatorio | LIKE crea candidatura PENDING; lista Buyer vacía hasta ACCEPT, verificado por `test_like_creates_one_pending_candidate_without_confirming_a_match` y flujo integrado. | **Pasa con Firestore Emulator.** |
| CA-03 — Candidaturas del Vendedor | Flujo integrado contrasta `buyer` y `listing` para cada candidatura; permisos también en `test_candidates_and_matches_are_scoped_by_verified_owner_and_role`. | **Pasa con Firestore Emulator**; UI usa mock HTTP. |
| CA-04 — Confirmación | Aceptación y consulta de listas Buyer/Seller en el flujo integrado y `test_accept_and_reject_are_persistent_idempotent_and_independent`. | **Pasa con Firestore Emulator.** |
| CA-05 — Rechazo | El flujo integrado rechaza la candidatura de la segunda vivienda; después no queda pendiente ni aparece en matches. | **Pasa con Firestore Emulator.** |
| CA-06 — Privacidad e independencia | Flujo de dos Compradores/dos viviendas, más `test_candidates_and_matches_are_scoped_by_verified_owner_and_role` y `test_two_buyers_create_independent_matches_with_same_home`. | **Pasa con emulador**; permisos unitarios usan perfiles mock, Auth Emulator es real en el flujo integrado. |
| CA-07 — Persistencia y duplicados | Re-login y retry ACCEPT en `test_published_multi_photo_listings_survive_full_buyer_flow`; IDs/fechas inmutables en `test_accept_and_reject_are_persistent_idempotent_and_independent`. | **Pasa con Auth/Firestore Emulator.** |
| CA-08 — Vacíos y errores | Vacíos/cursor y errores en `test_match_and_candidate_lists_paginate_and_return_empty_distinctly`, `MatchApiTests.test_invalid_payloads_identifiers_and_query_are_rejected` y fallos atómicos US5.8. | **Pasa con mocks y emulador**; en navegador se simularon 503/retry y 401. |

La interfaz se verificó en navegador de escritorio con Auth Emulator real y un
mock HTTP local en memoria para la API: interés pendiente, ACCEPT por teclado,
REJECT por doble clic, lista vacía, error 503 reintentable y 401 que conduce al
login. Se comprobaron 390×844 y 1280×900, sin overflow horizontal. Esta
comprobación **no** es persistencia Firestore de la interfaz ni prueba en móvil
físico; esa persistencia se verifica en la suite backend con emuladores. No se
implementó chat ni se depende de él para ver matches.

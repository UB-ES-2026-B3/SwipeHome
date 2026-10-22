# Backend de SwipeHome

Django sin base de datos propia: los usuarios viven en **Firebase Auth** y los
perfiles en **Firestore**. Django crea usuarios en el registro, verifica el ID token
de Firebase y lee los perfiles.

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
| `GET` | `/api/health` | Comprobación de vida. No toca Firebase. |
| `POST` | `/api/auth/register` | `{name, email, password, role}` → 201 / 400 / 409 / 500 |
| `GET` | `/api/auth/me` | `Authorization: Bearer <ID token>` → 200 / 401 / 404 / 500 |

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
- `repository.py` — **único** módulo que accede a Firestore (colecciones `users` y `listings`).
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

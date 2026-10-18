# Especificación: migración de autenticación a Firebase

Rama: `feature/firebase-auth` (sale de `dev`). Escrito el 18 de octubre de 2026.

Este fichero es el **plan de implementación**. `dev` se queda intacta y funcional
para poder enseñarla al profesor mientras esta rama avanza.

---

## 0. Qué cambia y qué no

**NO se toca:**
- `backend/accounts/validation.py` — no toca modelos ni base de datos. Se queda igual.
- Los componentes de React: `LoginForm`, `RegisterForm`, `FormField`.
  *Corrección:* `LoginForm` y `RegisterForm` **sí** llaman directamente a `login()` y
  `registerUser()` de `api/auth.js` y usan su respuesta `{ ok, status, data }`. No se
  enteran del cambio porque `api/auth.js` conserva ese contrato (ver §7).
- `useAuth.js`.
- Las páginas, salvo un botón mínimo de "Cerrar sesión" en `SellerHome` y `BuyerHome`
  (ver §7).

**SÍ se toca:**
- `backend/accounts/views.py` — reescritura.
- `backend/accounts/models.py`, `migrations/` — se eliminan (ver §6).
- `backend/accounts/fields.py` — se reduce a `normalize_account_email` (ver §6).
- `backend/config/settings.py` — fuera ORM, sesiones y CSRF de auth.
- `frontend/src/api/auth.js` — reescritura.
- `frontend/src/context/AuthContext.jsx` — pasa a escuchar el estado de Firebase.
- Los tests de vistas.

---

## 1. El problema que resuelve

El registro y el login actuales usan el ORM de Django, sesiones en base de datos
y SQLite. En Render el disco se borra cada vez que el servicio se duerme (15 min
sin tráfico), así que los usuarios desaparecerían varias veces al día. Además
`views.py` importa `sqlite3` directamente para detectar emails duplicados.

Ver `infra_context.md` para el contexto completo.

## 2. Decisión de diseño: quién crea el usuario

Hay dos formas de hacer el registro. **Elegimos la B.**

**A) El frontend crea el usuario en Firebase** (`createUserWithEmailAndPassword`)
y luego avisa a Django para que guarde el perfil.
*Problema:* Django nunca ve la contraseña, así que la regla de 15–128 caracteres
pasaría a ser solo validación de cliente. Eso contradice el principio que ya está
escrito en `backend_context.md`: *"las validaciones del cliente no sustituyen las
del servidor"*.

**B) Django crea el usuario** con el Admin SDK. ✅
El frontend envía `{name, email, password, role}` a `POST /api/auth/register`;
Django ejecuta `validate_registration` **sin cambios**, crea el usuario en Firebase
Auth y escribe el perfil en Firestore. Después el frontend hace sign-in con el SDK
de Firebase para obtener el token.

Se elige B porque conserva toda la validación en el servidor y reutiliza
`validation.py` tal cual.

**Riesgo de B y cómo se cubre:** si `create_user` funciona pero la escritura en
Firestore falla, quedaría un usuario de Firebase sin perfil. La vista debe hacer
una **acción compensatoria**: capturar el fallo, borrar el usuario de Firebase
recién creado (`auth.delete_user(uid)`) y devolver 500. No hay transacciones entre
Firebase Auth y Firestore, así que esto se gestiona a mano.

Si el borrado compensatorio **también** falla, la vista lo registra a nivel `error`
con el uid y sigue devolviendo 500. Ese usuario queda huérfano: ver el 404 de
`/api/auth/me` en §3.

**Ventaja gratis:** Firebase Auth garantiza emails únicos de serie. Desaparece la
constraint UNIQUE, el `CheckConstraint` de email normalizado y toda la detección de
duplicados comparando textos de error de SQLite. El 409 pasa a venir de
`auth.EmailAlreadyExistsError`.

## 3. Contrato de la API (nuevo)

### `POST /api/auth/register`
Body: `{name, email, password, role}` (igual que ahora).
- 201 → `{uid, name, email, role}`
- 400 → `{errors: {...}}` (de `validate_registration`, sin cambios)
- 409 → `{error: "El email ya está registrado."}` (de `EmailAlreadyExistsError`)
- 500 → error genérico

> **Nota para el futuro: políticas de contraseña de Firebase.** Hoy Firebase acepta
> todo lo que acepta `validate_registration` (comprobado de verdad con 15 espacios y
> con 128 caracteres de emoji). Si alguien activa una política de contraseñas en la
> consola de Firebase, el rechazo llega del servidor como
> `firebase_admin.exceptions.InvalidArgumentError` (no como `ValueError`) y la vista
> actual lo convierte en un **500** para una contraseña que nuestro validador dio por
> buena. En ese caso: capturar `InvalidArgumentError` → 400 con error en `password`,
> o mejor, alinear la regla de `validation.py` con la política.

Ya **no** devuelve cookie de sesión. Ya **no** existe el `GET` que servía el token CSRF.

### `GET /api/auth/me`
Cabecera: `Authorization: Bearer <ID token de Firebase>`
- 200 → `{uid, name, email, role}` (perfil leído de Firestore)
- 401 → token ausente, inválido o caducado
- 404 → `{error: "..."}`: token válido pero sin perfil en Firestore (caso huérfano, §2).
  Es un problema de **integridad de datos**, no de autenticación: significa que
  falló la escritura del perfil y también el borrado compensatorio. El backend lo
  registra a nivel `error` con el uid (nunca el token).
- 500 → `{error: "..."}` genérico: el servidor no pudo verificar el token o leer
  el perfil (credencial de Firebase ausente o inválida, fallo al descargar los
  certificados de Google, Firestore no disponible). **No** significa que la
  sesión haya terminado. Es la misma convención que el `/api/auth/me` actual.

### Regla para el frontend: 401 frente a 5xx
- **401** → la sesión no es válida: `signOut(auth)` y mostrar la interfaz sin sesión.
- **404** → `signOut(auth)` y mostrar un error **distinto** del de sesión caducada:
  la cuenta está incompleta y el usuario debe contactar con el equipo.
- **5xx o fallo de red** (el `fetch` lanza una excepción) → mostrar un error y
  permitir reintentar, **conservando la sesión**: ni `signOut` ni `setUser(null)`.

Un fallo de red o del servidor **nunca** debe parecer un cierre de sesión.

> **Por qué este camino se verá a menudo: Render se duerme.** El backend está en el
> plan gratuito de Render, que se duerme tras 15 minutos sin tráfico y tarda ~1 minuto
> en despertar. La primera petición tras un rato de calma no falla de inmediato: se
> queda **colgada** hasta que el servicio despierta, o acaba en error. Por eso el
> frontend:
> - muestra el aviso si `/api/auth/me` no ha respondido en unos segundos, sin esperar
>   a un error, para que nunca haya un spinner sin salida;
> - redacta el aviso como algo normal ("El servidor está despertando, puede tardar un
>   momento."), no como un fallo grave;
> - mantiene el botón **Reintentar** siempre accesible mientras dure.
>
> Es decir: este camino de error lo verán usuarios normales en uso normal, no solo
> cuando algo se rompe de verdad.

### Usuario huérfano (404): diagnóstico y recuperación
Un usuario con cuenta en Firebase Auth pero sin documento en `users/{uid}` es un
**callejón sin salida**: no puede entrar (el 404 le cierra la sesión) y tampoco
puede volver a registrarse, porque Firebase rechaza su email como ya registrado
(409).

- **Cómo detectarlo:** en los logs del backend, un `error` de `/api/auth/me` con el
  uid, o un `error` del registro diciendo que falló el borrado compensatorio.
- **Cómo recuperarlo:** consola de Firebase → Authentication → Usuarios, buscar
  ese uid y **eliminar el usuario**. Después ya puede registrarse de nuevo con el
  mismo email.

### `POST /api/auth/login` — **se elimina**
El login lo hace el frontend contra Firebase (`signInWithEmailAndPassword`).
Django no necesita participar. Tras el sign-in, el frontend llama a `/api/auth/me`
con el token para obtener el perfil.

### `GET /api/health`
Sin cambios. No toca ni Firestore ni Firebase Auth, a propósito.

## 4. Ficheros nuevos en el backend

### `backend/accounts/firebase.py`
Inicializa el Admin SDK una sola vez. Lee la credencial de, por este orden:
1. `FIREBASE_SERVICE_ACCOUNT_JSON` (contenido JSON completo, usado en Render), o
2. `GOOGLE_APPLICATION_CREDENTIALS` (ruta a un fichero, cómodo en local).

Si no hay credencial, debe fallar con un mensaje claro, no con un error críptico.

### `backend/accounts/repository.py`
**Único sitio del proyecto que habla con Firestore.** Las vistas llaman aquí, nunca
a Firestore directamente. Si algún día cambiamos de base de datos, se reescribe este
fichero y nada más.

Funciones mínimas:
- `create_user_profile(uid, *, name, email, role) -> dict`
- `get_user_profile(uid) -> dict | None`

Colección `users`, **id del documento = uid de Firebase**. Documento:

```
users/{uid}
  name       string
  email      string   (normalizado: minúsculas, sin espacios)
  role       string   ("SELLER" | "BUYER")
  created_at timestamp
```

El uid como id del documento evita tener que buscar por campo: el perfil se lee
directo con el uid que viene del token. Una lectura, sin índices.

### `backend/accounts/authentication.py`
Helper que extrae y verifica el token:
- Lee la cabecera `Authorization`, comprueba el prefijo `Bearer `.
- `firebase_admin.auth.verify_id_token(token)` → devuelve el uid.
- Distingue token ausente, mal formado, inválido y caducado; todos acaban en 401
  pero conviene registrarlos distinto para poder depurar.
- **No** debe registrar el token en los logs.

## 5. Cambios en `settings.py`
- Quitar `AUTH_USER_MODEL`.
- Quitar de `INSTALLED_APPS`: `django.contrib.auth`, `django.contrib.contenttypes`,
  `django.contrib.sessions`. Dejar solo `accounts`.
- Quitar de `MIDDLEWARE`: `SessionMiddleware`, `CsrfViewMiddleware`,
  `AuthenticationMiddleware`.
- Quitar `SESSION_*`, `CSRF_*`, `CSRF_FAILURE_VIEW`, `PASSWORD_HASHERS`.
- `DATABASES = {}` — sin modelos ni sesiones, Django no necesita base de datos.
  Dejarlo vacío y explícito es mejor que dejar un SQLite que nadie usa.
- **Conservar** el bloque de Render (`RENDER_EXTERNAL_HOSTNAME`,
  `SECURE_PROXY_SSL_HEADER`, `ALLOWED_HOSTS`): eso sigue haciendo falta.
- `_DEV` / `DJANGO_DEV` se puede conservar para `DEBUG`, pero ya no controla cookies.

`requirements.txt`: añadir `firebase-admin`. Fijar la versión exacta de todas las
dependencias, también las transitivas (como ya se hacía con `asgiref` y `sqlparse`),
generándolas con `pip freeze` desde un entorno virtual limpio, no a mano.

## 6. Qué se elimina y a quién afecta
Esto borra trabajo reciente de compañeros. Conviene avisar antes, no después.

- `models.py` (el modelo `User`) y `migrations/0001`, `0002`, `0003`.
- `fields.py` **no se borra**: se elimina `NormalizedEmailField` y se conserva
  `normalize_account_email`. `validation.py` la importa (y no se puede tocar) y
  `repository.py` la usa para guardar el email normalizado, así que hay una sola
  regla de normalización en todo el backend.
- `management/commands/runhttps.py` — **eliminado**, junto con `VITE_API_TARGET` en
  `vite.config.js`. Servía para probar en local las cookies `Secure` por HTTPS; sin
  cookies ya no hay motivo, y Firebase Auth funciona sobre `http://localhost`. Se
  conservan en `.gitignore` las entradas de `.local-tls/` para que nadie suba por
  error una clave privada que aún tenga en local.
- Tests que dependen del ORM: `test_persistence.py`, buena parte de `tests.py`,
  `test_login.py`, `test_current_user.py`, `test_development.py`.

> **Decidido: `0003` y `createsuperuser` se eliminan sin sustituto.** La migración
> `0003` se añadió para poder usar `createsuperuser`, pero `django.contrib.admin`
> nunca estuvo en `INSTALLED_APPS` ni había ruta `/admin`: los permisos de
> administrador no tenían dónde usarse. `SuperuserTests` se va con el modelo. Para
> ver usuarios y datos está la consola de Firebase.

## 7. Cambios en el frontend

`package.json`: añadir `firebase`.

### `frontend/src/firebase.js` (nuevo)
Inicializa el SDK con las variables `VITE_FIREBASE_*` (ver §8). El `firebaseConfig`
**no es secreto**: está pensado para viajar en el bundle.

### `frontend/src/api/auth.js` (reescritura)
- `registerUser(payload)` → `POST /api/auth/register` (sin CSRF, sin
  `credentials: 'include'`), y si va bien, sign-in con Firebase.
- `login({email, password})` → `signInWithEmailAndPassword` **y después**
  `fetchCurrentUser()`, devolviendo `{ ok, status: 200, data: perfil }`. *Cambio
  respecto a la primera versión* ("y nada más"): `LoginForm` hace `setUser(data)` y
  navega según `data.role` con lo que devuelve `login()`, así que sin el perfil habría
  que modificar `LoginForm` (§0). Los errores de Firebase se traducen a los códigos
  que el formulario ya maneja: 401 credenciales, 400 datos, 429 demasiados intentos,
  500 resto; un fallo de red se lanza.
- `fetchCurrentUser()` → coge el token del usuario actual de Firebase y llama a
  `GET /api/auth/me` con `Authorization: Bearer`. Devuelve `{ ok, status, data }`
  y lanza solo si falla la red.
- `logout()` → `signOut(auth)`. Ahora es trivial; antes no existía.

> **Redundancia conocida, a limpiar cuando el frontend vuelva a su responsable:** en
> el login el usuario se fija **dos veces**: con lo que devuelve `login()` (en
> `LoginForm`) y con `onAuthStateChanged` (en `AuthContext`), que vuelve a pedir
> `/api/auth/me`. Es inofensivo, porque son los mismos datos, pero cuesta una lectura
> de Firestore de más por login. La limpieza natural: que `LoginForm` deje de usar el
> perfil devuelto y navegue cuando el contexto tenga `user`, y que `login()` vuelva a
> ser solo el sign-in.

Desaparecen `getCsrfToken()`, todos los `credentials: 'include'` y la cabecera
`X-CSRFToken`.

### `frontend/src/context/AuthContext.jsx`
Ahora mismo llama a `fetchCurrentUser()` una vez al montar. Pasa a suscribirse a
`onAuthStateChanged(auth, ...)`:
- Si hay usuario de Firebase → pedir el perfil a `/api/auth/me` → `setUser(perfil)`.
- Si `/api/auth/me` responde 401 → `signOut(auth)`. Si responde 404 → `signOut(auth)`
  con un error propio de cuenta incompleta. Si responde 5xx o falla la red → error
  visible y **se conserva** la sesión (regla de §3).
- Si no hay → `setUser(null)`.
- `loading` en `true` hasta que se sabe quién es el usuario. **Sigue en `true`** si el
  perfil no se pudo cargar por un 5xx o un fallo de red: así `PrivateRoute` no
  redirige a `/` y el fallo no parece un cierre de sesión.
- El aviso (5xx, red, respuesta lenta o 404) lo pinta `AuthErrorBanner`, que se
  renderiza **dentro de `AuthProvider`**, con `retry()` y `dismissAuthError()` en el
  contexto.

> **Decisión temporal, no un patrón a copiar:** poner un componente visual dentro de
> `AuthProvider` mezcla estado y presentación. Se ha hecho así solo para no tocar los
> componentes existentes en esta rama. El responsable del frontend puede mover el
> aviso a `App.jsx` o al layout y quitarlo del proveedor.

### Botón de cerrar sesión (provisional)
No existía ninguna forma de cerrar sesión. Se añade un botón mínimo "Cerrar sesión" en
`SellerHome` y `BuyerHome` que llama a `logout()` del contexto; `onAuthStateChanged`
limpia el usuario y `PrivateRoute` lleva a `/`. Solo desbloquea el flujo registro →
login → recarga → logout: el equipo de frontend puede moverlo o rediseñarlo.

Esto es mejor que antes: el SDK renueva el token solo y avisa de los cambios de
sesión, así que la recarga de página deja de ser un caso especial.

**La forma del objeto `user` cambia:** `id` (número) pasa a ser `uid` (string).
Revisar si algún componente usa `user.id`.

## 8. Variables de entorno

**Backend** (`.env.example` ya las documenta):
- `FIREBASE_SERVICE_ACCOUNT_JSON` — JSON completo de la cuenta de servicio, en una
  línea. **Solo en Render.** Nunca en el repo ni por chat.
- `FIREBASE_PROJECT_ID=swipehome-a51d7`
- En local: `GOOGLE_APPLICATION_CREDENTIALS` apuntando al fichero JSON,
  guardado **fuera** del repositorio.

**Frontend** (`frontend/.env.example`, nuevo):
```
VITE_FIREBASE_API_KEY=
VITE_FIREBASE_AUTH_DOMAIN=
VITE_FIREBASE_PROJECT_ID=swipehome-a51d7
VITE_FIREBASE_APP_ID=
```
Valores en la consola de Firebase → Configuración del proyecto → General.
No son secretos, pero van por variable de entorno para no tener que tocar código
si algún día cambia el proyecto.

> **Compromiso conocido: un solo proyecto de Firebase.** Solo existe
> `swipehome-a51d7`. Local, las pruebas manuales y producción escriben en el mismo
> Firebase Auth y la misma colección `users`, así que los datos de prueba quedan al
> lado de los reales. Es aceptable a esta escala. Para que se distingan, los usuarios
> de prueba usan emails con un prefijo reconocible (p. ej. `curl<fecha>-...@example.com`)
> y se borran desde la consola cuando ya no hacen falta. Los tests automáticos nunca
> llegan a Firebase (§9). Si el proyecto crece, la solución es un segundo proyecto
> de Firebase para desarrollo o el Emulator Suite.

## 9. Tests
- `validation.py`: **sin cambios**. No tenía tests propios: sus casos se probaban a
  través del endpoint de registro en `tests.py`, comprobando el resultado con el ORM.
  Todos esos casos (tipos, límites, Unicode, email de 254, contraseña solo de
  espacios, JSON mal formado) se han portado a `test_views.py` con Firebase simulado.
- Tests de vistas: reescribir simulando (`mock`) `firebase_admin.auth` y el
  repositorio. No se llama a Firebase de verdad desde el CI: sería lento, haría
  falta una credencial en GitHub y gastaría cuota.
- Casos que conviene cubrir: token ausente, token inválido, token válido sin perfil
  (404), registro con email repetido (409), y el caso compensatorio de §2 (si
  Firestore falla, el usuario de Firebase no debe quedarse).
- El CI (`.github/workflows/ci.yml`) no necesita cambios si los tests están mockeados.
- Con `DATABASES = {}` todos los tests deben ser `SimpleTestCase` (comprobado en
  local y en una réplica del CI con Python 3.12: el runner informa de
  `Skipping setup of unused database(s)`). Un `django.test.TestCase`, aunque esté
  vacío, falla con `ImproperlyConfigured: settings.DATABASES is improperly
  configured`. Es lo esperado: un test que pide base de datos está probando algo
  que ya no existe.

> **Compromiso conocido y deliberado: registros simultáneos con el mismo email.**
> `test_simultaneous_duplicates_use_database_uniqueness` lanzaba tres registros a la
> vez con variantes del mismo email y comprobaba un 201 y dos 409. Se elimina y **no
> tiene equivalente mockeado**: un mock no puede demostrar la unicidad bajo
> concurrencia, solo la simularía. A partir de ahora confiamos en la garantía de
> Firebase Auth (un email por usuario, `EmailAlreadyExistsError` → 409) en vez de en
> una restricción propia. El email llega a Firebase ya normalizado por
> `validate_registration`, así que las variantes de mayúsculas y espacios colisionan.
> Si algún día se cambia de proveedor de autenticación, hay que recuperar esta
> garantía y su test.

## 10. Orden de trabajo sugerido
1. `firebase.py` + `repository.py` + `authentication.py`, con tests mockeados.
2. Reescribir `views.py` y `urls.py`. Comprobar con `curl` contra el Django local.
3. Limpiar `settings.py` y borrar modelo, migraciones y tests obsoletos.
4. Frontend: `firebase.js`, `api/auth.js`, `AuthContext.jsx`.
5. Probar el flujo completo en local: registro → login → recarga de página → logout.
6. Comprobar en la consola de Firebase que aparecen el usuario y el documento.
7. Desplegar en Render **desde `feature/firebase-auth`**: pasos exactos en §12. Así,
   un problema con la credencial aparece antes de que el código llegue a `dev`, y el
   equipo puede ver la API en una URL real.
8. PR a `dev` cuando todo funcione.
9. Tras el merge, volver a apuntar Render a `dev` (último paso de §12).

## 11. Lo que no entra en esta rama
- Hosting del frontend y CORS (con el proxy de Vite no hace falta todavía).
- Subida de fotos (Firebase Storage necesita plan de pago).
- Las colecciones `listings`, `swipes`, `matches`.
- Arreglar `main`.

## 12. Despliegue en Render, paso a paso (pasos 7 y 9)

Preparado y comprobado en local, pero **no** ejecutado contra Render. Primero se
despliega desde `feature/firebase-auth`; tras el merge de la PR se vuelve a apuntar a
`dev` (paso 9 al final).

### Antes de empezar, ten a mano
- La URL del servicio en Render: `https://<servicio>.onrender.com`.
- La ruta local del JSON de la cuenta de servicio (fuera del repo).
- `VITE_FIREBASE_API_KEY` (está en `frontend/.env.local`; no es secreta).
- Una terminal Git Bash para los `curl` del paso 5.

### Punto de partida
- El servicio construye hoy desde `deploy/render-bootstrap`: el código antiguo, con
  sesiones y SQLite.
- La configuración está solo en el panel; no hay `render.yaml`. Root directory
  `backend`, build `pip install -r requirements.txt`, start
  `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT`. **Nada de esto cambia.**
- Comprobado: las 41 dependencias fijadas tienen wheel para Linux x86_64 con Python
  3.12 y 3.13, así que Render no compila nada desde el código fuente.

### Paso 1 — Copiar la credencial en una línea (en local)
Desde `backend/`, en PowerShell:

```powershell
.\.venv\Scripts\python.exe -I -c "import json,sys; print(json.dumps(json.load(open(sys.argv[1], encoding='utf-8'))))" 'C:\ruta\fuera\del\repo\cuenta-de-servicio.json' | Set-Clipboard
```

Deja en el portapapeles el JSON en **una línea** (unos 2.400 caracteres), sin
escribirlo en ningún fichero ni mostrarlo. Comprobado en local: el backend arranca con
esa línea y verifica tokens.

### Paso 2 — Variables de entorno
Render → el servicio → **Environment** → *Add Environment Variable*:

| Key | Value |
|---|---|
| `FIREBASE_SERVICE_ACCOUNT_JSON` | pegar (Ctrl+V) |
| `FIREBASE_PROJECT_ID` | `swipehome-a51d7` |

Revisa la lista:
- `DJANGO_SECRET_KEY` → ya existe; no tocar.
- `DJANGO_DEV` → **no debe existir**: activaría `DEBUG` en producción.
- `GOOGLE_APPLICATION_CREDENTIALS` → no debe existir (confunde; el JSON tiene prioridad).
- `DATABASE_PATH` → si existe, borrarla (ya no se usa).

Guarda. Si Render ofrece elegir, **"Save only"**: el código antiguo ignora estas
variables, así que no pasa nada si se despliega antes del paso 3.

**Justo después:** sobrescribe el portapapeles copiando cualquier otra cosa. Si usas
el historial del portapapeles de Windows (`Win+V`), borra también esa entrada: es la
clave de administrador del proyecto.

### Paso 3 — Cambiar la rama y desplegar
Render → el servicio → **Settings** → *Build & Deploy* → **Branch**:
`deploy/render-bootstrap` → **`feature/firebase-auth`**. Guarda.

Después: **Manual Deploy** → *Deploy latest commit*.

Mientras apunte a esta rama, con auto-deploy activado, **cada push a
`feature/firebase-auth` despliega**.

### Paso 4 — Revisar el log de build
En **Events / Logs** del deploy:
- Versión de Python: debe ser 3.12 o 3.13 (las comprobadas). Si es otra, añadir
  `PYTHON_VERSION=3.13.14` en Environment y redesplegar.
- Instalados `firebase-admin==7.7.0` y `gunicorn==23.0.0`, sin errores.
- gunicorn arranca y el deploy queda *Live*.

### Paso 5 — Verificar
En Git Bash: `BASE=https://<servicio>.onrender.com`. La primera petición puede
tardar ~1 minuto si el servicio estaba dormido.

**5a. El proceso está vivo**
```bash
curl -i "$BASE/api/health"
```
→ `200 {"status": "ok"}`. No toca Firebase: solo dice que Django arranca.

**5b. Es el código nuevo**
```bash
curl -i "$BASE/api/auth/me"
```
→ `401` **con la cabecera `WWW-Authenticate: Bearer`**. El código antiguo también
daba 401 aquí, pero sin esa cabecera.

**5c. La credencial se ha cargado** (no crea datos)
```bash
curl -i -H "Authorization: Bearer no-es-un-jwt" "$BASE/api/auth/me"
```
- **`401` → credencial cargada.** Para rechazar el token, Django ha tenido que
  inicializar el Admin SDK con la credencial y conocer el project id.
- **`500` → problema con la credencial.** Ir al paso 7.

Comprobado en local: sin credencial da 500; con la línea del paso 1 da 401.

**5d. Flujo completo** (crea un usuario real; ver el compromiso de §8)
```bash
KEY=<VITE_FIREBASE_API_KEY>
EMAIL="deploy$(date +%m%d%H%M)@example.com"
PASS="contrasena de prueba de despliegue"

curl -s -w "\n-> %{http_code}\n" -H "Content-Type: application/json" \
  -d "{\"name\":\"Deploy Check\",\"email\":\"$EMAIL\",\"password\":\"$PASS\",\"role\":\"BUYER\"}" \
  "$BASE/api/auth/register"

TOKEN=$(curl -s -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\",\"returnSecureToken\":true}" \
  "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=$KEY" \
  | python -c "import json,sys; print(json.load(sys.stdin)['idToken'])")

curl -s -w "\n-> %{http_code}\n" -H "Authorization: Bearer $TOKEN" "$BASE/api/auth/me"
```
→ `201` en el registro y `200` con el mismo perfil en `/me`. Demuestra que la
credencial puede crear usuarios en Firebase Auth y escribir y leer en Firestore.

**Limpieza:** borra ese usuario en la consola de Firebase en **dos sitios**:
Authentication → Usuarios, y Firestore → `users/{uid}`. Borrar solo uno deja un
huérfano (§3) o un documento suelto.

**5e. Logs de Render:** tras 5a–5d no debe haber ninguna línea `ERROR`. Sí aparecen
un `INFO` por 5b y un `WARNING` por 5c, que son esperados.

### Paso 6 — Demo con la interfaz (opcional)
El frontend no está alojado (§11), pero se puede usar en local contra el backend de
Render, sin CORS:

```powershell
cd frontend
$env:VITE_API_TARGET = 'https://<servicio>.onrender.com'
npm run dev
```

Antes de la demo, abre `$BASE/api/health` un par de minutos antes para despertar el
servicio.

### Paso 7 — Si algo falla
- **5c da 500:** en los logs de Render, la línea `ERROR accounts.firebase: ...` dice
  la causa exacta:
  - `No hay credenciales de Firebase...` → la variable no existe o está vacía.
  - `FIREBASE_SERVICE_ACCOUNT_JSON no contiene un JSON válido.` → se pegó mal
    (cortada, con saltos de línea o con comillas de más). Repetir los pasos 1 y 2.
  - `...no es una cuenta de servicio de Firebase válida.` → es otro JSON (por
    ejemplo, el `firebaseConfig` del frontend).
- **5c da 401 pero 5d da 500 en el registro:** la credencial vale para verificar
  tokens pero no para crear usuarios o escribir. El log dice qué falló, por ejemplo
  `No se pudo crear el usuario en Firebase Auth (InsufficientPermissionError)`.
  Revisar los permisos de la cuenta de servicio en Google Cloud → IAM.
- **Volver atrás:** Settings → Branch → `deploy/render-bootstrap` y *Deploy latest
  commit*, o Events → deploy anterior → *Rollback*. El código antiguo vuelve a
  funcionar tal cual, con el problema original: SQLite se borra cada vez que el
  servicio se duerme.

### Paso 8 — PR a `dev`
Con el paso 5 en verde, abrir la PR de `feature/firebase-auth` a `dev`. Render sigue
desplegando desde la rama de trabajo mientras se revisa.

### Paso 9 — Tras el merge: volver a apuntar Render a `dev`
1. Render → Settings → *Build & Deploy* → **Branch**: `feature/firebase-auth` →
   **`dev`**. Guarda.
2. **Manual Deploy** → *Deploy latest commit*.
3. Repetir **5a, 5b y 5c**. No hace falta repetir 5d: la credencial y las variables
   son las mismas; solo cambia de qué rama sale el código.
4. Desde aquí, cada push a `dev` despliega. `deploy/render-bootstrap` deja de usarse;
   borrarla o conservarla es decisión aparte.

# Especificación: migración de autenticación a Firebase

Rama: `feature/firebase-auth` (sale de `dev`). Escrito el 18 de octubre de 2026.

Este fichero es el **plan de implementación**. `dev` se queda intacta y funcional
para poder enseñarla al profesor mientras esta rama avanza.

---

## 0. Qué cambia y qué no

**NO se toca:**
- `backend/accounts/validation.py` — no toca modelos ni base de datos. Se queda igual.
- Los componentes de React: `LoginForm`, `RegisterForm`, `FormField`, las páginas.
  Consumen `useAuth()`, no la API directamente, así que no se enteran del cambio.
- `useAuth.js`.

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
- `management/commands/runhttps.py` — revisar si sigue teniendo sentido.
- Tests que dependen del ORM: `test_persistence.py`, buena parte de `tests.py`,
  `test_login.py`, `test_current_user.py`, `test_development.py`.

> **DECISIÓN PENDIENTE PARA EL EQUIPO:** la migración `0003` se añadió para poder
> usar `createsuperuser` y el admin de Django. Sin modelo `User` eso desaparece.
> ¿Alguien lo estaba usando? Si hace falta un panel de administración, hay que
> decidir otra cosa (la consola de Firebase sirve para ver usuarios y datos).

## 7. Cambios en el frontend

`package.json`: añadir `firebase`.

### `frontend/src/firebase.js` (nuevo)
Inicializa el SDK con las variables `VITE_FIREBASE_*` (ver §8). El `firebaseConfig`
**no es secreto**: está pensado para viajar en el bundle.

### `frontend/src/api/auth.js` (reescritura)
- `registerUser(payload)` → `POST /api/auth/register` (sin CSRF, sin
  `credentials: 'include'`), y si va bien, sign-in con Firebase.
- `login({email, password})` → `signInWithEmailAndPassword` y nada más.
- `fetchCurrentUser()` → coge el token del usuario actual de Firebase y llama a
  `GET /api/auth/me` con `Authorization: Bearer`.
- `logout()` → `signOut(auth)`. Ahora es trivial; antes no existía.

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
- `loading` en `true` hasta la primera respuesta.

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

## 9. Tests
- `validation.py` y sus tests: **sin cambios**. Deberían seguir pasando tal cual.
- Tests de vistas: reescribir simulando (`mock`) `firebase_admin.auth` y el
  repositorio. No se llama a Firebase de verdad desde el CI: sería lento, haría
  falta una credencial en GitHub y gastaría cuota.
- Casos que conviene cubrir: token ausente, token inválido, token válido sin perfil
  (404), registro con email repetido (409), y el caso compensatorio de §2 (si
  Firestore falla, el usuario de Firebase no debe quedarse).
- El CI (`.github/workflows/ci.yml`) no necesita cambios si los tests están mockeados.

## 10. Orden de trabajo sugerido
1. `firebase.py` + `repository.py` + `authentication.py`, con tests mockeados.
2. Reescribir `views.py` y `urls.py`. Comprobar con `curl` contra el Django local.
3. Limpiar `settings.py` y borrar modelo, migraciones y tests obsoletos.
4. Frontend: `firebase.js`, `api/auth.js`, `AuthContext.jsx`.
5. Probar el flujo completo en local: registro → login → recarga de página → logout.
6. Comprobar en la consola de Firebase que aparecen el usuario y el documento.
7. Añadir `FIREBASE_SERVICE_ACCOUNT_JSON` en Render y desplegar.
8. PR a `dev` cuando todo funcione.

## 11. Lo que no entra en esta rama
- Hosting del frontend y CORS (con el proxy de Vite no hace falta todavía).
- Subida de fotos (Firebase Storage necesita plan de pago).
- Las colecciones `listings`, `swipes`, `matches`.
- Arreglar `main`.

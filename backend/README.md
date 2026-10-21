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

No hay migraciones: `DATABASES = {}`.

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
El contrato completo, el significado de cada código y cómo debe reaccionar el
frontend están en el §3 de la
[especificación](<../Agents mds/firebase_auth_migration.md>).

Las reglas de validación del registro están en `accounts/validation.py`: nombre
2–80, email normalizado (minúsculas, sin espacios) de hasta 254 caracteres,
contraseña de 15–128 caracteres sin recortar y rol `SELLER` o `BUYER`.

## Estructura de `accounts/`

- `views.py` — endpoints. No habla con Firestore directamente.
- `repository.py` — **único** módulo que accede a Firestore (colección `users`).
- `authentication.py` — extrae y verifica el ID token. Nunca lo escribe en los logs.
- `firebase.py` — inicializa el Admin SDK, de forma perezosa y una sola vez.
- `validation.py` — validación del registro.
- `fields.py` — `normalize_account_email`, la única regla de normalización de email.

## Tests

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test accounts --verbosity 2
```

Para incluir HTTPS real, establece LOCAL_TLS_CERT y LOCAL_TLS_KEY como indica
el apartado de pruebas HTTPS. La suite completa tiene 53 casos. Las nuevas
pruebas cubren normalizacion por distintas vias ORM, Unicode, restricciones
SQL directas, actualizaciones duplicadas, hashes, identificadores, errores
500 aun cuando ya existe el email y migraciones con/sin colisiones.
La concurrencia utiliza tres hilos y conexiones independientes, con una barrera
tras el hashing: ningun registro puede insertar hasta que los tres alcanzan
ese punto. Se comprueban una respuesta 201, dos 409 y exactamente una cuenta.
Se mantienen las pruebas de atomicidad, CSRF y sesiones de US1.3/US1.4.1.

Referencias: [campos Django](https://docs.djangoproject.com/en/5.2/howto/custom-model-fields/),
[restricciones](https://docs.djangoproject.com/en/5.2/ref/models/constraints/),
[migraciones de datos](https://docs.djangoproject.com/en/5.2/ref/migration-operations/#runpython).

## Registro con CSRF y comprobacion manual en navegador

`GET /api/auth/register` devuelve `csrfToken` y establece la cookie CSRF segura.
No crea una sesion y su respuesta tiene Cache-Control: no-store.
`POST` requiere esa cookie y `X-CSRFToken`, con origen HTTPS de la misma web.
Sin proteccion CSRF valida devuelve 403; las validaciones mantienen 400,
el email duplicado 409 y los fallos internos 500. No se habilita CORS general
ni se anaden origenes de confianza externos.

Abre `https://localhost:8443/api/auth/register` y, en la consola del navegador,
ejecuta usando un email nuevo en cada registro exitoso:

```javascript
const {csrfToken} = await fetch('/api/auth/register').then(r => r.json());
const response = await fetch('/api/auth/register', {
  method: 'POST',
  headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
  body: JSON.stringify({name: 'Ana Garcia', email: 'ana@example.com',
    password: 'una contrasena completa', role: 'BUYER'})
});
console.log(response.status, await response.json());
```

Espera 201 con id, name, email y role. Repite con SELLER y otro email.
En Network revisa los atributos de Set-Cookie, sin copiar su valor a logs.
En Application > Cookies revisa sessionid con HttpOnly, Secure y SameSite=Lax.
Recarga la pagina y comprueba que el navegador conserva la cookie y la envia
al servidor. JavaScript no debe poder leer sessionid mediante document.cookie.
Login rota tambien el token CSRF: vuelve a obtenerlo antes de otro POST.

## Consultar el usuario actual: GET /api/auth/me

Disponible sin barra final. Reutiliza la cookie de sesion Django creada al
registrarse y no necesita enviar id, rol ni token de sesion en el cuerpo.

- 200: {"id": 1, "name": "Ana Garcia", "email": "ana@example.com", "role": "BUYER"}.
- 401: {"error": "No hay una sesion autenticada."}, sin redireccion al login.
- 500: error generico si no se puede consultar la identidad; no debe tratarse
  como un cierre de sesion confirmado.

La identidad y el rol se leen del usuario almacenado por el servidor en cada
solicitud. No se exponen contrasenas, hashes ni identificadores de sesion.
Las respuestas llevan Cache-Control con no-store y private para evitar que el
navegador o un intermediario reutilicen datos de otra consulta de identidad.
El GET no modifica datos de cuenta ni crea una sesion autenticada.
Una sesion caducada/invalida, una cuenta eliminada o una contrasena cambiada
devuelven 401. El registro conserva su proteccion CSRF; este GET no necesita
token CSRF. No se cambia CORS ni la configuracion de origenes.

Tras registrar al usuario con el ejemplo anterior, o al cargar/recargar la
interfaz, ejecuta desde el mismo origen HTTPS:

```javascript
const meResponse = await fetch('/api/auth/me', {
  credentials: 'same-origin',
  cache: 'no-store'
});
if (meResponse.status === 200) {
  const user = await meResponse.json();
  console.log(user); // El frontend recupera aqui su estado autenticado.
} else if (meResponse.status === 401) {
  // Mostrar la interfaz sin sesion.
} else {
  // Mostrar el error y permitir reintentar la consulta.
}
```

Para una demo abre https://localhost:8443/api/auth/me despues del registro:
veras el usuario y puedes recargar para comprobar la consulta en navegador.
El frontend debe conectar /api al backend con el origen HTTPS/proxy configurado.
Las pruebas de identidad del nuevo endpoint usan las rutas reales del backend,
y la prueba HTTPS consulta /api/auth/me tres veces con la cookie recibida.
Los casos historicos de US1.4.1 conservan su vista exclusiva de pruebas.
La recarga real y la consulta de sesion desde la interfaz tambien se
comprobaron en navegador durante US1-6 para ambos roles, a traves del proxy Vite.

## Dependencias reproducibles

`requirements.txt` fija la versión exacta de todas las dependencias, directas y
transitivas. Se genera con `pip freeze` desde un entorno virtual limpio, no a mano.
Para añadir una dependencia: crea un venv nuevo, instala el `requirements.txt` actual
más el paquete nuevo con su versión fijada y sustituye el fichero por la salida de
`pip freeze`.

## Despliegue (Render)

Build `pip install -r requirements.txt`, start
`gunicorn config.wsgi:application --bind 0.0.0.0:$PORT`. Variables:
`DJANGO_SECRET_KEY`, `FIREBASE_SERVICE_ACCOUNT_JSON` y `FIREBASE_PROJECT_ID`. Render
inyecta `RENDER_EXTERNAL_HOSTNAME`, y `settings.py` lo añade a `ALLOWED_HOSTS` y
activa `SECURE_PROXY_SSL_HEADER`. Ver `infra_context.md` §3.

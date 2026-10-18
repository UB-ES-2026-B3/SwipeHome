# Backend de SwipeHome - US1.3, US1.4.1 y persistencia de cuentas

## Decisiones y documentación

La rama de trabajo para la PR es `features-US-1.3-implementar-api-registro`.
La rama de destino de la PR para estas US es `dev` (`origin/dev` en remoto).
US1.4.1 se desarrolla directamente sobre el codigo existente de US1.3.
El commit, el push y la PR los realizará el usuario manualmente.

Documentación revisada:
[contexto backend](<../Agents mds/backend_context.md>),
[contexto general y US1](<../Agents mds/project_context.md>),
[pautas del equipo](<../Agents mds/skills.md>) y
[contexto frontend](<../Agents mds/frontend_context.md>).
Estas son las referencias principales; no se mantiene una copia duplicada del
contexto original de Descargas. No hay AGENTS.md aplicables.
La documentación recuperada no fija otro stack ni cambia las reglas de registro.
Django, SQLite local y hashing Django fueron autorizados expresamente por el usuario.

Python **3.13** (verificado con 3.13.7), Django **5.2.18**.
SQLite es exclusivamente la decisión de desarrollo local; la base del futuro
deployment sigue pendiente. No se necesita emulador ni credenciales cloud.
Sesiones/cookies siguen siendo el mecanismo previsto; no se añade JWT.

## Instalacion y modos de desarrollo

### Modo HTTP (runserver) — para desarrollo rápido sin certificado

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
$env:DJANGO_DEV = '1'
.\.venv\Scripts\python.exe manage.py runserver
```

Con `DJANGO_DEV=1` las cookies de sesión y CSRF no requieren HTTPS (`Secure=False`)
y `DEBUG=True` activa los mensajes de error detallados de Django.
El frontend Vite proxifica `/api/*` a `http://127.0.0.1:8000` automáticamente.
**No usar `DJANGO_DEV=1` en producción ni con `runhttps`.**

### Modo HTTPS local (runhttps) — replica la configuración de producción

Desde la raiz, PowerShell (Python 3.13 y Git para Windows):

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
New-Item -ItemType Directory -Force .local-tls | Out-Null
& 'C:/Program Files/Git/usr/bin/openssl.exe' req -x509 -newkey rsa:2048 -nodes -keyout .local-tls/localhost-key.pem -out .local-tls/localhost.pem -days 30 -subj '/CN=localhost' -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1'
.\.venv\Scripts\python.exe manage.py runhttps --cert .local-tls/localhost.pem --key .local-tls/localhost-key.pem
```

El comando usa ssl y wsgiref de Python, escucha solo en loopback y no tiene
autoreload. Es exclusivamente un servidor de desarrollo. Ctrl+C para detenerlo.
Si OpenSSL esta en PATH, puede usarse `openssl` en lugar de la ruta de Git.
No se instala ninguna dependencia Python adicional ni herramienta global.
Los certificados caducan a los 30 dias: vuelve a generarlos cuando sea necesario.
`.local-tls/` esta ignorado por Git. Nunca compartas ni versiones la clave privada.
La cookie conserva Secure: utiliza siempre `https://localhost:8443`.

Para que Edge/Chrome en Windows confien en el certificado local, convierte e
importa **solo el certificado publico** al almacen de tu usuario (paso manual):

```powershell
& 'C:/Program Files/Git/usr/bin/openssl.exe' x509 -in .local-tls/localhost.pem -outform DER -out .local-tls/localhost.cer
$localCert = Import-Certificate -FilePath .local-tls/localhost.cer -CertStoreLocation Cert:\CurrentUser\Root
$localCert.Thumbprint
```

Conserva esa huella para retirar la confianza cuando termines:
`Remove-Item -LiteralPath "Cert:\CurrentUser\Root\HUELLA_GUARDADA"`.
La importacion de confianza no se ha ejecutado automaticamente.
Firefox puede necesitar importar el certificado en su propio almacen.

La persistencia es SQLite local (`backend/db.sqlite3`); `migrate` prepara tambien
`django_session`. No hay servicios cloud.
[.env.example](.env.example) describe todas las variables de entorno disponibles.
El archivo .env no se carga automaticamente. Variables habituales:

```powershell
$env:DJANGO_SECRET_KEY = 'swipehome-local-development-only'
$env:DATABASE_PATH = Join-Path (Get-Location) 'db.sqlite3'
# Solo en modo HTTP local; NO usar con runhttps:
$env:DJANGO_DEV = '1'
```

El secreto de ejemplo es publico y exclusivo de desarrollo local.

## Crear un superusuario

Desde `backend`, con el entorno y las dependencias anteriores preparados:

```powershell
uv run python manage.py migrate
uv run python manage.py createsuperuser
```

El comando solicita email, nombre, rol (`BUYER` o `SELLER`) y contrase?a.
El email se normaliza y la contrase?a se guarda con el hashing de Django.
Los permisos administrativos (`is_staff`, `is_superuser`) son independientes
del rol de producto; no existe un rol `ADMIN`. Las cuentas existentes conservan
sus datos y reciben permisos administrativos desactivados en la migraci?n 0003.
No hay panel Django admin configurado en este proyecto.

Para arrancar por HTTP desde CMD (las variables no se comparten con otra terminal):

```bat
cd backend
set DJANGO_DEV=1
uv run python manage.py runserver
```

En PowerShell usa `$env:DJANGO_DEV = '1'` antes de arrancar el backend.
Copiar `.env.example` a `.env` no activa esta variable autom?ticamente.
Reinicia Django tras cambiarla. En HTTPS elimina la variable en esa terminal:
`Remove-Item Env:DJANGO_DEV -ErrorAction SilentlyContinue` en PowerShell
o `set DJANGO_DEV=` en CMD. El navegador tambi?n debe usar HTTPS para recibir
cookies Secure; un proxy a un backend HTTPS no convierte el frontend HTTP en HTTPS.
El cliente solicita un token CSRF nuevo antes de cada registro/login para admitir
la rotaci?n de Django y evita cachear esa consulta.

## Dependencias reproducibles

`requirements.txt` fija todas las dependencias directas y transitivas:
Django==5.2.18, asgiref==3.12.1, sqlparse==0.6.0 y tzdata==2026.5.
Es el archivo de instalación y bloqueo del entorno Python inicial; no existía
otro gestor ni lockfile. tzdata se fija también para otros sistemas, aunque
Django lo requiere específicamente en Windows. No se instala nada global.

## Contrato implementado

`POST /api/auth/register`, sin barra final y sin redirección, acepta un
objeto JSON con `name`, `email`, `password`, `role`, todos strings.
No se convierten tipos. Campos adicionales no afectan a la creación.

- Nombre: trim exterior, longitud 2–80.
- Email: trim exterior y minúsculas; formato validado por EmailValidator
  de Django, ningún espacio interior y máximo 254 caracteres normalizados.
  No se comprueba entregabilidad ni se hacen consultas de red.
- Contraseña: 15–128 caracteres Unicode, incluidos espacios; sin modificar,
  recortar ni truncar. Sin reglas adicionales de complejidad.
- Rol: exactamente SELLER o BUYER.

La estructura JSON de salida no estaba cerrada en el contexto. Para esta
implementación se define el siguiente contrato local:
201 con `id`, `name`, `email`, `role`;
400 con `errors` por campo o `error` para formato de petición;
409 con `error` por email ya registrado; 500 con `error` genérico y reintento.
No se incluyen contraseña, hash, SQL ni trazas. Los logs internos solo
registran un mensaje fijo sin payload ni excepciones.

Se usa un usuario Django personalizado basado en AbstractBaseUser y hashing
PBKDF2-SHA256 con sal mediante set_password/check_password.
La migración impone UNIQUE al email y CHECK al rol.
La inserción y preparación de respuesta están dentro de transaction.atomic;
el hashing se realiza antes de bloquear la escritura.
Las transacciones SQLite IMMEDIATE serializan las escrituras concurrentes;
un conflicto de unicidad se trata después del rollback y devuelve 409.
Otros errores se devuelven como 500 sin cuenta parcial.

Referencias técnicas:
[contraseñas Django](https://docs.djangoproject.com/en/5.2/topics/auth/passwords/),
[transacciones](https://docs.djangoproject.com/en/5.2/topics/db/transactions/),
[SQLite](https://docs.djangoproject.com/en/5.2/ref/databases/#sqlite-notes).

## Persistencia de cuentas e integridad (US1-5)

Se conserva un unico modelo `accounts.User` y la base SQLite local.
Ya existian BigAutoField como identificador unico, hash PBKDF2-SHA256 de Django,
UNIQUE sobre email, CHECK de rol SELLER/BUYER y registro atomico con sesion.
Esta tarea completa la normalizacion centralizada y distingue especificamente
la violacion de unicidad del email de los demas fallos de base de datos.
El contrato sigue siendo 201/400/409/500 (y 403 para CSRF).

`NormalizedEmailField` aplica la misma funcion `strip().lower()` antes de
persistir. Cubre create_user, create, save, bulk_create y las actualizaciones
con valores del ORM, incluidas bulk_update. La validacion del endpoint y el
manager reutilizan esa misma regla. No se utiliza la normalizacion de dominio
parcial de BaseUserManager: se convierte toda la direccion a minusculas.
Los objetos creados con save reflejan el email normalizado; tras update o
bulk_update, usa refresh_from_db para actualizar su estado en memoria.

La nueva restriccion `accounts_user_normalized_email` exige que el email
almacenado ya sea canonico. Con el UNIQUE existente garantiza que una escritura
SQL o una expresion que eluda el campo no introduzca variantes del mismo email.
Los roles siguen protegidos por `accounts_user_valid_role`.

Para que Python y SQLite apliquen exactamente las mismas reglas Unicode,
AccountsConfig registra `swipehome_normalize_email` en cada conexion SQLite
Django (tambien en las conexiones de los hilos). No usa LOWER/TRIM de SQLite,
que no tienen la misma semantica Unicode. La funcion solo normaliza emails;
el hashing sigue siendo set_password/check_password de Django.
Crea cuentas mediante create_user o el flujo existente de registro; no asignes
contrasenas en texto plano al campo password.

La base requiere esa funcion para escribir en accounts_user. Usa conexiones
Django (por ejemplo manage.py shell); un cliente SQLite externo sin la funcion
fallara al escribir, sin saltarse la restriccion. Este ajuste es para SQLite
local; otro motor futuro requerira adaptar la restriccion y el reconocimiento
del conflicto de email. No se añade infraestructura ni dependencia adicional.

### Migracion local segura

`0002_normalize_account_emails` revisa primero TODOS los emails existentes.
Si hay colisiones tras normalizar, se detiene sin cambiar cuentas y requiere
resolucion manual del equipo. No fusiona, elimina ni cambia contrasenas.
Sin colisiones normaliza los emails, conserva IDs, nombres, hashes y roles,
y añade el CHECK en la misma transaccion. La marcha atras del esquema no
restaura las mayusculas o espacios originales de los emails.
La base local revisada antes de aplicar la migracion tenia cero cuentas.

Desde backend:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py showmigrations accounts
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
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

## Verificación

Desde backend:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test accounts --verbosity 2
```

Las pruebas crean SQLite en un directorio temporal exclusivo de cada proceso,
fuera de la base de desarrollo, aplican migraciones y lo eliminan al terminar.
No usar --keepdb: el directorio es temporal.
Incluyen ambos roles, campos ausentes/null/tipos incorrectos, límites,
Unicode/espacios en contraseñas, emails normalizados/duplicados,
peticiones malformadas, restricciones SQL, concurrencia real con conexiones
separadas y rollback incluso tras insertar o al preparar la respuesta.
Verifican respuestas sin secretos y logs seguros ante fallos.

## Sesion implementada y alcance pendiente

US1.4.1 (US1-4A del contexto) integra las sesiones de base de datos y la
AuthenticationMiddleware de Django con el usuario personalizado de US1.3.
`login(request, user)` renueva la clave de sesion y rota CSRF. La identidad
procede del usuario creado, y el rol se consulta en el modelo del servidor;
no se almacena una copia del rol que pueda quedar obsoleta.

La cuenta, last_login, renovacion y guardado de sesion estan dentro de la misma
transaction.atomic. SessionMiddleware prepara la cookie y persiste antes del
commit; se marca la sesion como no modificada para evitar un segundo guardado
fuera de la transaccion. Si falla la persistencia, la respuesta o el commit,
se revierten la cuenta y la sesion y se restaura el estado previo de la peticion.
Una sesion autenticada anterior se conserva si el registro falla.
No se devuelven claves de sesion, contrasenas, hashes ni trazas en JSON o logs.
La duracion local usa el valor predeterminado Django: 14 dias; no se renueva en
cada solicitud. La politica de deployment sigue pendiente.

La redireccion y el estado de interfaz pertenecen a US1-4B. Logout sigue
pendiente. GET /api/auth/me permite consultar la identidad al recargar.
El backend ya reconoce las cookies en las solicitudes siguientes mediante
request.user. No se implementa infraestructura ni se realizan push o merges.

## Login implementado (US2.3 y US2.4)

POST /api/auth/login recibe un objeto JSON con `email` y `password`, sin rol.
Devuelve 200 con `id`, `name`, `email` y `role` cuando las credenciales son
correctas. Datos invalidos devuelven 400 con `errors`; un email inexistente y
una contrasena incorrecta devuelven 401 con el mismo mensaje; un fallo interno
devuelve 500 con un mensaje generico.

Reutiliza accounts.User, NormalizedEmailField, UserManager.normalize_email,
las migraciones existentes y SQLite local. No crees otra tabla de usuarios ni
otro mecanismo de autenticacion. Usa authenticate/check_password de Django;
no compares hashes manualmente ni vuelvas a generar el hash para comprobarlo.
La contrasena de login admite 1-128 caracteres, sin trim ni truncamiento:
no reutilices sin adaptar la validacion de registro, que exige 15-128.
Email inexistente y contrasena incorrecta deben devolver el mismo 401 y mensaje
"Email o contraseña incorrectos."; datos invalidos 400 y fallo interno 500.

Tras autenticar, reutiliza login(request, user) de Django y el patron atomico
del registro para persistir la sesion antes de responder con exito. Ten en
cuenta la renovacion de clave, last_login, la rotacion de CSRF y el rollback
del estado de la peticion si falla el guardado. No conviertas un fallo de
persistencia en credenciales incorrectas. Un login rechazado no debe crear
una sesion nueva ni cerrar automaticamente una sesion previa.
Mantener HttpOnly/Secure/SameSite=Lax, middleware de autenticacion/sesiones,
CSRF activo, HTTPS local y errores/logs sin secretos. El rol siempre procede
del usuario autenticado en el servidor. GET /api/auth/me se reutiliza sin
crear un segundo endpoint para consultar la sesion de login.

Las pruebas en `accounts/test_login.py` cubren ambos resultados de autenticacion,
normalizacion, contrasenas de 1-128 caracteres, validacion de tipos y limites,
errores indistinguibles, cookie segura, sesion asociada, ruta exacta y rollback
ante fallos al verificar credenciales y al guardar la sesion. Tambien comprueban
que dos sesiones distintas identifican exclusivamente a su cuenta y que las
respuestas y logs no exponen datos sensibles. Ejecutar tambien la suite completa
para conservar registro, persistencia y consulta de usuario.

## Resultado verificado

Suite completa: 53 pruebas correctas, incluida la prueba HTTPS real al definir
`LOCAL_TLS_CERT` y `LOCAL_TLS_KEY`. Sin esas variables, Django omite solamente
la prueba HTTPS. Tambien pasan `manage.py check` y
`makemigrations --check --dry-run`.
Las migraciones sessions.0001_initial y accounts.0002_normalize_account_emails
se aplicaron a SQLite local conservando la base existente.
No se han modificado requirements.txt ni sus versiones fijadas.

### Resultado de verificación de US1-6 (18 octubre 2026)

Ejecución local con certificado HTTPS configurado:

```powershell
$env:LOCAL_TLS_CERT = (Resolve-Path '.local-tls\localhost.pem').Path
$env:LOCAL_TLS_KEY = (Resolve-Path '.local-tls\localhost-key.pem').Path
.\.venv\Scripts\python.exe manage.py test accounts --verbosity 2
```

**Resultado: 53 tests correctos, ninguno fallido ni omitido.** También pasan
`manage.py check` y `manage.py makemigrations --check --dry-run`. La ejecución
verifica los registros SELLER y BUYER, datos y hashes persistidos, sesión,
validaciones directas a la API y límites, email normalizado y duplicado
concurrente, rollback de cuenta/sesión ante fallos y respuestas/logs sin datos
sensibles.

El frontend también se verificó en navegador a través del proxy Vite → Django
con `DJANGO_DEV=1`. Se registró un Vendedor y un Comprador: ambas solicitudes
devolvieron 201, guardaron el rol correcto y redirigieron respectivamente a
`/vendedor/inicio` y `/comprador/inicio`. Tras recargar, ambas rutas se
mantuvieron y `GET /api/auth/me` devolvió 200 con la identidad y el rol
correspondientes. La cookie `sessionid` no fue accesible desde JavaScript. Con
los cuatro campos vacíos, el formulario impidió el envío y mostró los cuatro
errores requeridos. La base aislada de esta prueba terminó con exactamente dos
cuentas y dos sesiones.

También se ejecutaron `npm --prefix frontend ci`, `npm --prefix frontend run
build` y `npm --prefix frontend run lint`. La instalación y el build terminaron
correctamente; el lint terminó con código 0 y mostró una advertencia
`react(only-export-components)` en `src/context/AuthContext.jsx:15`. No hubo
fallos que requirieran cambios de implementación. La suite backend y esta
comprobación integrada cubren las rutas de aceptación de US1-6.

## Prueba HTTPS real

Desde backend, con los certificados locales anteriores:

```powershell
$env:LOCAL_TLS_CERT = Join-Path (Get-Location) '.local-tls/localhost.pem'
$env:LOCAL_TLS_KEY = Join-Path (Get-Location) '.local-tls/localhost-key.pem'
.\.venv\Scripts\python.exe manage.py test accounts --verbosity 2
```

La suite usa SQLite en un directorio temporal aislado. No usar --keepdb.
Sin estas variables se omite explicitamente la prueba HTTPS; con ellas se
verifica TLS con confianza explicita en el certificado, sin desactivar su
validacion. Usa el mismo servidor runhttps, una cookie jar real y tres
solicitudes autenticadas consecutivas. Verifica tambien el duplicado por HTTPS.
Las otras pruebas cubren ambos roles, atributos de cookie, identidad desde el
servidor, rol actualizado, fijacion de sesion, solicitudes anonimas, CSRF,
validaciones de US1.3, concurrencia, rollback y fallo al confirmar el commit.

La verificacion automatica HTTPS y las solicitudes del cliente de pruebas no
constituyen una recarga real de navegador. La comprobacion manual de navegador
queda pendiente; los pasos anteriores permiten realizarla.

Referencias: [sesiones Django](https://docs.djangoproject.com/en/5.2/topics/http/sessions/),
[login Django](https://docs.djangoproject.com/en/5.2/topics/auth/default/#how-to-log-a-user-in),
[CSRF Django](https://docs.djangoproject.com/en/5.2/howto/csrf/).

## Verificacion de login US2-6 (18 octubre 2026)

La bateria automatizada en `accounts/test_login.py` verifica el login SELLER y
BUYER, respuestas 401 iguales para email desconocido y contrasena incorrecta,
validaciones directas de campos ausentes/vacios, tipos no admitidos y limites.
Comprueba la normalizacion de emails con mayusculas y espacios exteriores, y que
una contrasena con espacios solo autentica cuando se conserva exactamente.
Tambien verifica la cookie `sessionid` (Path=/, HttpOnly, Secure y SameSite=Lax),
la identidad aislada de dos cuentas mediante `GET /api/auth/me`, fallos simulados
en la comprobacion de credenciales y en el guardado de la sesion, y ausencia de
secretos en respuestas y logs.

Desde `backend`:

```powershell
.\.venv\Scripts\python.exe manage.py test accounts.test_login --verbosity 1
.\.venv\Scripts\python.exe manage.py test accounts --verbosity 1
```

Verificacion ejecutada: los 11 tests de login pasan. La suite `accounts` cuenta
56 tests: 55 pasan y se omite la prueba HTTPS real al no definir
`LOCAL_TLS_CERT` y `LOCAL_TLS_KEY`. La prueba HTTPS documentada arriba corresponde
a la verificacion US1-6 del 18 de octubre, con certificado configurado.

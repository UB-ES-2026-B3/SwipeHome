# Backend de SwipeHome — US1.3

## Decisiones y documentación

La rama de trabajo para la PR es `features-US-1.3-implementar-api-registro`,
creada desde `features` local, que sigue `origin/features`.
Se incorporaron mediante fast-forward los dos commits de `origin/main`
que contienen la documentación del equipo en `Agents mds/`.
La implementación de US1.3 se conserva como cambios locales en la rama de PR.
El commit, el push y la PR los realizará el usuario manualmente.
La base local incluye los dos commits de documentación de main todavía ausentes
en origin/features; si no se sincroniza antes el destino remoto, aparecerán
también en la comparación de la PR.
Git no admite espacios ni dos puntos en ramas. Además, la rama features
impide usar features/ como prefijo para otra referencia; por eso se usa un guion.

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

## Instalación y ejecución local

Desde la raíz del repositorio, en PowerShell:

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

No hace falta activar el entorno. Para detener el servidor: Ctrl+C.
La configuración local funciona sin variables: crea `backend/db.sqlite3`.
[.env.example](.env.example) describe las variables opcionales:
`DJANGO_SECRET_KEY` y `DATABASE_PATH`. El archivo .env no se carga
automáticamente; establece las variables en PowerShell antes de ejecutar:

```powershell
$env:DJANGO_SECRET_KEY = 'swipehome-local-development-only'
$env:DATABASE_PATH = Join-Path (Get-Location) 'db.sqlite3'
```

El valor de ejemplo es local y público. DEBUG está desactivado.
Entorno virtual, bases SQLite, bytecode y .env están excluidos en .gitignore.

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

## Ejemplo

Con el servidor iniciado, en otra terminal PowerShell:

```powershell
$body = @{
    name = 'Ana García'
    email = '  ANA@Example.COM  '
    password = '  una contraseña completa  '
    role = 'BUYER'
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/auth/register' -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
```

Respuesta 201 (identificador ilustrativo):

```json
{"id": 1, "name": "Ana García", "email": "ana@example.com", "role": "BUYER"}
```

Repetir con el mismo email devuelve 409.

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

## Alcance pendiente

US1.3 implementa la creación de cuenta. No crea sesión ni redirige:
el propio contexto asigna la sesión a US1.4A y la navegación a US1.4B.
El endpoint no usa autenticación basada en cookies ni muta una sesión,
y admite el registro JSON directo sin token CSRF. US1.4A deberá integrar
sesiones, cookies y protección CSRF acorde al contrato del equipo.
No hay login, deployment, infraestructura ni otras funcionalidades.
El contrato general de respuestas y la base de producción deberán coordinarse
con el equipo cuando se aborden sus tareas.

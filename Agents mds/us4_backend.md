# US 4.4–4.7: exploración, decisiones, matches y avisos

Estado comprobado el 8 de noviembre de 2026. El usuario autorizó expresamente
implementar el alcance con **Firebase Auth y Firestore**, conservando el stack
de esta rama. Esta adaptación sustituye los requisitos originales de sesiones,
cookies/CSRF Django, SQLite, modelos ORM y migraciones SQL. No se cambia de
proveedor ni se incorpora un segundo sistema de usuarios.

## Estado funcional y contratos

| US | Resultado implementado |
|---|---|
| 4.4 | GET `/api/inmuebles/explorar`, solo BUYER. Publicaciones completas, pendientes del Comprador; fotografías completas en el orden existente; paginación por fecha e ID. |
| 4.5 | POST `/api/inmuebles/{id}/decision`, solo BUYER. LIKE crea directamente decisión, match y aviso. PASS solo crea decisión. 201 nuevo, 200 reintento, 409 contradicción. |
| 4.6 | Colecciones `swipes`, `matches` y `notifications` con claves canónicas y escritura transaccional centralizada. Persistencia independiente de la sesión y del proceso Django. |
| 4.7 | GET `/api/notificaciones`, solo SELLER. Avisos privados con match, Comprador y vivienda; paginación estable y lectura de avisos históricos. |

**Un LIKE del Comprador crea el match y el aviso al propietario directamente.**
No existe aceptación del Vendedor, segundo swipe ni reserva del inmueble.
Distintos Compradores pueden tener matches sobre la misma vivienda.

Los contratos completos, ejemplos y códigos HTTP están en
[README backend](../backend/README.md). No se añaden frontend, chat, email,
push ni marcado de lectura.

## Arquitectura reutilizada

`accounts.authentication.firebase_role` verifica el ID token con revocación
Firebase y con las revocaciones persistentes US6. Lee el perfil real mediante
`repository.get_user_profile` y construye `request.user` con UID, rol y nombre
verificados. Las operaciones utilizan ese objeto, nunca un UID del cuerpo o query.
Un acceso sin Bearer válido devuelve 401; un rol incorrecto o perfil ausente, 403.
Un fallo del proveedor devuelve 500 seguro, sin fingir un cierre de sesión.

No hay autenticación por cookies ni middleware CSRF Django en esta rama.
Las pruebas usan `Client(enforce_csrf_checks=True)`: Bearer válido funciona,
cookies por sí solas devuelven 401. No se añade `csrf_exempt`.

Todo acceso a Firestore permanece en `accounts/repository.py`.
Las vistas, servicios y serialización pública nuevos están en `properties/`.
Se conserva `listings.created_at` como fecha de publicación y el array
`photos` en su orden original; no se vuelven a subir ni se modifican fotos.

## Persistencia y evolución aditiva del esquema

No hay migraciones ORM ni tablas equivalentes nuevas. Las colecciones aparecen
con la primera escritura. Los usuarios y anuncios existentes se reutilizan por
su UID/ID actual; la SQLite local residual sigue sin usarse y no se modifica.

Sea `key = SHA256(JSON([buyer_uid, listing_id]))`, serializado de forma
determinista con JSON ASCII:

| Documento | Campos obligatorios escritos por el servidor |
|---|---|
| `swipes/{key}` | `buyer_uid`, `listing_id`, `value` LIKE/PASS, `created_at` |
| `matches/{key}` | `buyer_uid`, `listing_id`, `decision_id=key`, `created_at` |
| `notifications/match-{key}` | `recipient_uid`, `match_id=key`, `buyer_uid`, `buyer_name`, `listing_id`, `listing_title`, `type=MATCH`, `message`, `created_at` |

Las fechas nuevas son timestamps UTC fijados por el reloj del backend durante
la operación; nunca proceden del cliente. El nombre del Comprador es una
instantánea de su nombre vigente en Auth en ese momento; el título es una
instantánea del anuncio. Se evita una lectura de usuario/vivienda por aviso.
El match no duplica el propietario: se resuelve mediante
`listings/{listing_id}.seller_uid`. El aviso fija el destinatario de ese anuncio.

Firestore impone la unicidad del **path del documento** y la precondición de
inexistencia de `create()`. No tiene CHECK, FK ni UNIQUE sobre campos arbitrarios.
La validación LIKE/PASS, la correspondencia del origen, las claves canónicas y
el conjunto completo LIKE/match/aviso son garantías del **servicio transaccional**,
con acceso directo de clientes a Firestore cerrado. Admin SDK y cambios manuales
pueden saltarse ese servicio; no se les atribuyen restricciones SQL inexistentes.

El código previo no contiene escritores de decisiones o matches ni modelos ORM
equivalentes. No se han inspeccionado registros remotos de producción.
Antes de activar sobre datos externos preexistentes de `swipes` o `matches`,
debe comprobarse que siguen estas claves y relaciones. No se ejecuta una
conversión destructiva ni se inventa una migración de datos desconocidos.

Se reutiliza la colección `notifications`. Los avisos antiguos conservan
`id/type/message/created_at`; no se borran, duplican ni se les fabrica un match.
Los avisos creados por US4 añaden las relaciones completas. Un registro con
`match_id` y relaciones incompletas se considera inconsistente y devuelve 500.
Los documentos sin `created_at` quedan fuera de las consultas ordenadas Firestore.
Los anuncios parciales o sin fotografías quedan fuera de exploración y decisión.

## Atomicidad, reintentos y concurrencia

`repository.record_decision` es el único escritor de US4. Lee publicación,
decisión, match y aviso dentro de la transacción, antes de cualquier escritura.
Crea los tres documentos LIKE en el mismo commit, sin callbacks ni tareas.
Si falla una escritura o Firestore rechaza el commit, no queda un subconjunto
nuevo. PASS no crea match ni aviso.

Un reintento igual devuelve los documentos guardados, incluidas fechas e IDs,
sin crear otro aviso. La decisión contraria devuelve 409 sin sobrescribirla.
Un LIKE incompleto o de origen incompatible devuelve 500 y no se repara
silenciosamente. No se devuelve éxito sin match.

El SDK reintenta abortos durante commit (hasta 10 intentos). El servicio contempla
también abortos durante **lecturas**, colisiones `AlreadyExists` y agotamiento
del SDK causado por `Aborted`: hasta 5 transacciones nuevas, con espera aleatoria
acotada. No vuelve a consultar una transacción invalidada. Cada operación instancia
un wrapper transaccional SDK propio para no compartir retry_id entre hilos. Otros errores no se
reintentan como si fueran conflictos. Al agotar reintentos devuelve 500 seguro.

Una pérdida de conexión después de que Firestore acepte un commit puede dejar
resultado HTTP incierto: todos los documentos podrían haberse guardado, nunca
solo una parte del commit. El cliente debe repetir la misma decisión para
recuperar el resultado; no se promete deshacer un commit ya confirmado en remoto.

## Consultas e índices

Ambas colecciones se ordenan por `created_at DESC, __name__ DESC`.
`limit` tiene valor 20 y admite 1–50. Los cursores están firmados por usuario
y recurso, conservan nanosegundos y no requieren que sobreviva el documento
que marcó la posición. Continuar significa fecha anterior, o misma fecha e ID
menor. Se rechazan cursores manipulados, ajenos, cruzados entre endpoints,
parámetros desconocidos, vacíos o repetidos.

Exploración recorre lotes con `start_after` y carga decisiones canónicas con
`get_all`. No usa OFFSET, no carga todo el historial de decisiones y no hace
consultas por fotografía. Busca `limit+1` viviendas pendientes; el cursor sale
de la última **entregada**, incluso si se inspeccionaron descartes posteriores.
Se comprueba explícitamente decidir sobre una página y continuar sin saltos.
El coste de lectura aumenta cuando hay muchos anuncios ya decididos;
los lotes acotan la memoria, no el número total de lecturas necesario para
encontrar pendientes. La paginación no es una instantánea del catálogo.

Índices en [firestore.indexes.json](../backend/firestore.indexes.json):
`listings(published ASC, created_at DESC, __name__ DESC)` y
`notifications(recipient_uid ASC, created_at DESC, __name__ DESC)`.
El archivo [firebase.json](../backend/firebase.json) permite desplegar solo
índices. Los comandos están en el README. No se han desplegado índices remotos.
El emulador no certifica el requisito de índices de producción.

## Verificación real

Resultado final: **140 pruebas correctas, sin omisiones** con Auth y Firestore
Emulator, proyecto `demo-swipehome-us4`, Node 24 y Java 21.
La última ejecución completa tardó 46,564 s. Incluye 37 pruebas nuevas sobre las
103 previas; las pruebas existentes de avisos se ajustan a SELLER y las US6
usan el proyecto demo del emulador activo.

- Tres solicitudes simultáneas LIKE: 201/200/200, mismo match y un aviso.
- Tres solicitudes simultáneas PASS: 201/200/200, sin match ni aviso.
- LIKE y PASS simultáneos: un 201 y un 409; se conserva el ganador.
- Barreras e hilos con clientes HTTP independientes; persistencia y transacciones
  contra Firestore Emulator real, sin simular el motor.
- Rollback ante fallo inducido de cada guardado y rechazo real de commit por
  precondición incumplida; unicidad real de `create`; orígenes inconsistentes.
- Permisos, identidad verificada, JSON inválido, reintentos, privacidad,
  fotografías, fechas empatadas, lotes, cursores, última página y colección vacía.
- Persistencia tras logout, nueva sesión y nuevo cliente Firestore.
- Recorrido con Auth real del emulador: registro, login, publicación, LIKE,
  logout, token revocado y nuevo login; solo Storage se simula en ese recorrido.
- Suite sin emuladores: **116 correctas y 24 integraciones omitidas**.
- `manage.py check`: sin incidencias; `makemigrations --check --dry-run`:
  sin cambios; `pip check`: dependencias correctas; `git diff --check`: correcto.
- No hay formatter/linter Python configurado en el repositorio.
  No se añaden dependencias de formato para esta tarea.

Las primeras ejecuciones identificaron y corrigieron aislamiento de revocaciones,
proyectos distintos en las regresiones US6 y abortos de lectura bajo concurrencia.
Los resultados anteriores fallidos no se presentan como comprobaciones superadas.
No se ha probado producción, Storage real, ni se ha lanzado CI remoto.
El workflow queda actualizado para Java 21 y la suite completa con ambos emuladores.

## Archivos de implementación

- `backend/accounts/authentication.py`: autorización y request.user verificado.
- `backend/accounts/repository.py`: escritura transaccional y consultas Firestore.
- `backend/accounts/pagination.py`: validación y cursores compartidos.
- `backend/accounts/notification_service.py` y `notification_views.py`: avisos SELLER.
- `backend/properties/discovery_views.py`, `discovery_service.py`,
  `serialization.py`: decisiones y exploración.
- `backend/config/urls.py`: rutas exactas.
- `backend/firestore.indexes.json` y `backend/firebase.json`: evolución de índices.
- `backend/properties/test_discovery.py`, `test_firestore.py`,
  `backend/accounts/test_notifications.py`, `test_profile.py`: pruebas.
- `backend/tests/firebase.json`, `firestore.rules`: emuladores demo con reglas cerradas.
- `backend/.gitignore`: logs del emulador; `.github/workflows/ci.yml`: integración.
- Documentación vigente: este archivo, `backend/README.md` y los documentos
  de contexto backend, proyecto, infraestructura, frontend, Firebase y pautas.

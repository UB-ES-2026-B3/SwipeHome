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
| 4.7 | LIKE genera un aviso privado al SELLER con match, Comprador y vivienda. Lectura paginada; US7.4 amplía el GET a consulta propia BUYER/SELLER. |

**Un LIKE del Comprador crea el match y el aviso al propietario directamente.**
No existe aceptación del Vendedor, segundo swipe ni reserva del inmueble.
Distintos Compradores pueden tener matches sobre la misma vivienda.

Los contratos completos, ejemplos y códigos HTTP están en
[README backend](../backend/README.md). No se añaden frontend, chat, email,
push ni marcado de lectura.

## Arquitectura reutilizada

`accounts.authentication.firebase_roles` verifica el ID token con revocación
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

## Verificación US 4.9

Ejecutado el 10 de noviembre de 2026 mediante el comando de emuladores del
[README backend](../backend/README.md): **166 pruebas correctas, sin omisiones**.
Auth Emulator y Firestore Emulator ejecutan localmente con el proyecto demo
`demo-swipehome-us4`; Azure Blob se mockea donde aplica. No se usaron servicios
ni credenciales de producción. La prueba adicional
`test_all_three_endpoints_enforce_roles_without_persisting_changes` hace
solicitudes autenticadas e anónimas a los tres endpoints y comprueba códigos y
ausencia de escrituras indebidas.

| CA | Evidencia automatizada | Resultado |
|---|---|---|
| CA-01 — Acceso al explorador | `test_all_three_endpoints_enforce_roles_without_persisting_changes`, `test_authentication_and_buyer_permissions_for_both_endpoints`: BUYER autorizado; otro rol o ausencia de token rechazados. | Parcial (solo API): ruta/inicio de Comprador en UI no se prueba aquí. Firebase verifier/perfil están mockeados en el test de roles; Firestore usa emulador. |
| CA-02 — Información y fotografías | `test_explore_excludes_only_own_decisions_and_preserves_all_photos`, `test_all_public_fields_and_ordered_photos_without_internal_data`: datos completos y orden de URLs conservado en API. | Parcial (solo API): tarjeta y navegación de fotos en UI, y acceso a blobs, no verificados. |
| CA-03 — Creación del match | `test_like_has_exactly_one_consistent_decision_match_and_notice`, `test_same_decision_retries_return_identical_records`: LIKE asocia decisión/match a comprador y vivienda; repetición no duplica. | Pasa en API/Firestore Emulator; swipe o botón de interfaz no verificado. |
| CA-04 — Aviso al Vendedor | `test_private_notices_include_match_buyer_home_and_stable_pagination`: aviso identifica comprador y vivienda y solo lo consulta el vendedor destinatario. | Pasa con Firestore Emulator; vista visual no verificada. |
| CA-05 — Descarte persistente | `test_pass_creates_only_decision_and_no_notice`, `test_explore_excludes_only_own_decisions_and_preserves_all_photos`, `test_empty_and_exact_limit_pages_have_no_next_cursor`: PASS persiste sin match/aviso y excluye la vivienda para ese comprador. | Pasa en API/Firestore Emulator; control «No me interesa» de UI no verificado. |
| CA-06 — Independencia entre Compradores | `test_two_buyers_match_same_home_without_reserving_or_hiding_it`: dos compradores tienen documentos/matches propios para la misma vivienda. | Pasa con Firestore Emulator. |
| CA-07 — Continuidad y fin de la exploración | `test_pagination_ties_previous_page_decisions_and_last_page`, `test_scan_multiple_batches_of_decided_homes_without_skip_or_n_plus_one`, `test_empty_and_exact_limit_pages_have_no_next_cursor`: cursor continúa con pendientes y responde lista vacía al final. | Parcial (solo API): tarjeta siguiente y mensaje de fin en UI no verificados. |
| CA-08 — Fallos y reintentos | `test_each_staged_write_failure_rolls_back_entire_operation`, `test_rejected_commit_does_not_persist_any_staged_document`, `test_same_decision_retries_return_identical_records`, `test_simultaneous_identical_likes_converge_to_same_match_and_notice`, `test_internal_failures_are_safe_for_both_endpoints`: rollback, estado final y retry idempotente. | Parcial (solo backend): mensajes/control de reintento de UI no verificados. |

La suite completa también ejecuta el flujo de Auth con Auth Emulator; el test
de rol específico de CA-01 inyecta identidad/perfil y no prueba Auth.

No se ejecutaron Azure Blob ni Firestore de producción, no se desplegaron los
índices remotos ni se lanzó CI remoto. La persistencia real verificada aquí es
la del Firestore Emulator; las pruebas de rollback usan Firestore Emulator con
fallos de escritura inyectados. No hay linter/formatter Python configurado.

## Verificación integrada US 4.10

El comando de emuladores del README backend pasó **167 tests** con Auth y
Firestore Emulator, incluido
`FirebaseFlowTests.test_published_multi_photo_listings_survive_full_buyer_flow`.
El test registra vendedor y dos Compradores, publica dos anuncios válidos de
US3 con dos fotos cada uno y URLs Azure simuladas, explora los campos/fotos
ordenados, registra LIKE y PASS, consulta el aviso como propietario, cierra y
reabre sesión, verifica exclusión/reintento idempotente y confirma que el
segundo Comprador obtiene otro match para la misma vivienda.

La interfaz BuyerHome se probó en navegador con Auth Emulator y la API
interceptada (fixtures), no contra Firestore. Se verificaron visualización de
campos y fotos, cambio de foto y desplazamiento vertical sin decisión, botón
LIKE/doble clic, confirmación, PASS por teclado, evento de puntero horizontal,
respuesta temporal 503 y reintento, error de carga/reintento, lista vacía,
respuesta 401/fin de sesión, recarga y viewport de escritorio/móvil. Los
eventos de puntero se enviaron mediante automatización del navegador; no se
certificó un dispositivo móvil físico ni una pérdida de red física. El test de
API Node comprueba que una decisión propaga un rechazo de red para que la UI
mantenga la publicación y ofrezca reintento.

| CA oficial | Evidencia para el recorrido US4.10 | Resultado y límite |
|---|---|---|
| CA-01 — Acceso al explorador | Permisos backend de US4.9; Auth Emulator en navegador y perfil/API mockeados. | Parcial: navegación Buyer verificada; permisos sin sesión/rol indebido están en tests backend, no se repitió UI de esos roles. |
| CA-02 — Información y fotografías | Publicación/exploración en Firestore Emulator; fixture de navegador con campos y varias fotos, cambio de galería. | Pasa con mocks para UI; Azure Blob no se descargó y navegador no leyó Firestore. |
| CA-03 — Creación del match | Backend publica y registra LIKE; botón/doble clic y confirmación de UI con API interceptada. | Pasa con Firestore Emulator en backend y mocks en UI; no se requiere pantalla US5. |
| CA-04 — Aviso al Vendedor | GET de avisos backend verifica Comprador/vivienda para el propietario. | Pasa con Firestore Emulator; pantalla visual de avisos US5 no verificada. |
| CA-05 — Descarte persistente | PASS, ausencia de match/aviso y exclusión tras re-login en Firestore Emulator; tecla izquierda en navegador. | Pasa con Firestore Emulator y mock UI. |
| CA-06 — Independencia entre Compradores | El test integrado registra dos Compradores y confirma dos matches distintos sobre una publicación. | Pasa con Firestore Emulator. |
| CA-07 — Continuidad y fin de la exploración | El backend consulta cursor/fin; BuyerHome avanza al siguiente elemento y muestra lista vacía en prueba de navegador. | Pasa en API/fixture; el listado de navegador no procede de Firestore. |
| CA-08 — Fallos y reintentos | Retry de backend idempotente tras re-login; UI con 503 mock, fallo de carga, 401 y test Node de rechazo de red. | Parcial: retry backend y tratamiento de errores pasan; no se provocó pérdida física de conexión en navegador. |

Todas las persistencias descritas como reales son del emulador local, no de
servicios de producción. Azure Blob se mockea tanto en el test de publicación
como en las fixtures de navegador.

## Archivos de implementación

- `backend/accounts/authentication.py`: autorización y request.user verificado.
- `backend/accounts/repository.py`: escritura transaccional y consultas Firestore.
- `backend/accounts/pagination.py`: validación y cursores compartidos.
- `backend/accounts/notification_service.py` y `notification_views.py`: consulta privada de avisos.
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

## Continuidad US 7.4: consulta de notificaciones

El endpoint GET acepta BUYER y SELLER, pero los resultados siempre se filtran
por el UID del perfil autenticado. `uid` y `recipient_uid` no son parámetros
permitidos; el cursor firmado queda asociado al UID, por lo que tampoco se puede
reutilizar desde otra cuenta. La operación es solo lectura y conserva el orden
descendente estable por fecha/ID.

La suite pasó 172 tests con Auth/Firestore Emulator y mocks de Azure Blob.
`FirestoreDecisionTests.test_private_notices_include_match_buyer_home_and_stable_pagination`
verifica el interés US4 al propietario correcto, mensaje, fecha, orden, cursor y
aislamiento entre vendedores. `test_pass_creates_only_decision_and_no_notice`
verifica que PASS no crea aviso. `test_buyer_and_seller_can_read_only_their_own_notifications`
siembra avisos locales aislados para BUYER, SELLER y una tercera cuenta, prueba
selección privada, parámetros manipulados y que leer no altera decisiones ni
matches. `FirebaseFlowTests.test_real_registration_login_publication_like_logout_and_relogin`
comprueba Auth real del emulador, aviso US4, revocación al salir y conservación
del aviso tras volver a iniciar sesión. No se usó Firebase/Azure de producción.

La UI está cubierta con 25 tests Node y navegador con Auth Emulator y API
interceptada; esos mocks verifican estados, reintentos, actualización,
paginación sin IDs repetidos, fecha/hora y viewports 1280×900/390×844. Lint y
build finalizan con advertencias preexistentes; no se probó hardware móvil.

**Límite de alcance:** no hay endpoint ni productor de la confirmación US5 en
este repositorio. La API puede leer una notificación BUYER ya persistida, pero
la generación de ese aviso no se atribuye ni se considera verificada por US7.4.

# US4/US5.8: exploración, candidaturas, matches y avisos

La implementación original de US4 fue revisada por US5.8: un LIKE crea ahora
una candidatura pendiente; el Vendedor propietario acepta/rechaza y solo
ACCEPT crea match y aviso privado para el Comprador. Las evidencias antiguas de
US4 que asumían match inmediato se conservan como histórico y quedan superadas
por la sección US5.8 al final de este documento.
La implementación conserva **Firebase Auth y Firestore**, sin sesiones/cookies
Django, SQLite, ORM ni migraciones SQL.

## Estado funcional y contratos

| US | Resultado implementado |
|---|---|
| 4.4 | GET `/api/inmuebles/explorar`, solo BUYER. Publicaciones completas, pendientes del Comprador; fotografías completas en el orden existente; paginación por fecha e ID. |
| 4.5 | POST `/api/inmuebles/{id}/decision`, solo BUYER. LIKE crea candidatura PENDING; PASS solo decisión. |
| 4.6 | `swipes`, `matches` y `notifications`; la transición ACCEPT crea match/aviso en un commit atómico. |
| 4.7 | Avisos de confirmación al Comprador; consulta paginada y privada de avisos de ambos roles. |
| 5.8 | GET de matches/candidatos y POST de aceptación/rechazo, filtrados por rol y propiedad, idempotentes y transaccionales. |

Un LIKE no es un match confirmado ni produce aviso. Distintos Compradores
pueden crear candidaturas/matches independientes sobre la misma vivienda.

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
| `swipes/{key}` | `buyer_uid`, `seller_uid`, `buyer_name`, `listing_id`, `value`, `created_at`; LIKE añade `seller_decision` y, al decidir, `seller_decided_at` |
| `matches/{key}` | `buyer_uid`, `seller_uid`, `listing_id`, `decision_id=key`, `created_at`; solo ACCEPT |
| `notifications/buyer-match-{key}` | aviso de confirmación para el Comprador, con match, identidad y vivienda |

Las fechas nuevas son timestamps UTC fijados por el reloj del backend durante
la operación; nunca proceden del cliente. El nombre del Comprador es una instantánea del nombre vigente en Auth al dar
LIKE; el título es una instantánea del anuncio al aceptar. La propiedad se
verifica con `listings/{listing_id}.seller_uid`.

Firestore impone la unicidad del **path del documento** y la precondición de
inexistencia de `create()`. No tiene CHECK, FK ni UNIQUE sobre campos arbitrarios.
La validación de decisiones, correspondencia del origen, claves canónicas y
transiciones son garantías del **servicio transaccional**,
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

`repository.record_decision` persiste LIKE como candidatura PENDING. La
transición separada `repository.transition_seller_decision` actualiza el estado
y, para ACCEPT, crea match/aviso en el mismo commit. Si falla una escritura de
esa transición, conserva la candidatura sin match ni aviso. REJECT no los crea.

Un reintento de LIKE devuelve el mismo estado actual; los reintentos de ACCEPT
o REJECT no cambian IDs/fechas ni duplican datos. La transición opuesta devuelve
409. Un registro incoherente devuelve 500 y no se repara silenciosamente.

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
`notifications(recipient_uid ASC, created_at DESC, __name__ DESC)`,
`swipes(seller_uid, value, seller_decision, created_at DESC, __name__ DESC)` y
`matches(buyer_uid|seller_uid, created_at DESC, __name__ DESC)`.
El archivo [firebase.json](../backend/firebase.json) permite desplegar solo
índices. Los comandos están en el README. No se han desplegado índices remotos.
El emulador no certifica el requisito de índices de producción.

## Verificación US 4.9 (histórica)

Esta ejecución es anterior a US5.8; las semánticas de match y aviso de CA-03/04
que siguen quedan sustituidas por la evidencia actual al final del documento.

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
| CA-03 — Creación del match | En esa versión el LIKE creaba el match inmediatamente. | **Supersedido por US5.8:** ahora requiere ACCEPT del Vendedor. |
| CA-04 — Aviso al Vendedor | En esa versión el LIKE generaba aviso al propietario. | **Supersedido por US5.8:** al aceptar se genera aviso para el Comprador. |
| CA-05 — Descarte persistente | `test_pass_creates_only_decision_and_no_notice`, `test_explore_excludes_only_own_decisions_and_preserves_all_photos`, `test_empty_and_exact_limit_pages_have_no_next_cursor`: PASS persiste sin match/aviso y excluye la vivienda para ese comprador. | Pasa en API/Firestore Emulator; control «No me interesa» de UI no verificado. |
| CA-06 — Independencia entre Compradores | `test_two_buyers_create_independent_matches_with_same_home`: Compradores distintos mantienen decisiones y matches propios. | Pasa con Firestore Emulator. |
| CA-07 — Continuidad y fin de la exploración | `test_pagination_ties_previous_page_decisions_and_last_page`, `test_scan_multiple_batches_of_decided_homes_without_skip_or_n_plus_one`, `test_empty_and_exact_limit_pages_have_no_next_cursor`: cursor continúa con pendientes y responde lista vacía al final. | Parcial (solo API): tarjeta siguiente y mensaje de fin en UI no verificados. |
| CA-08 — Fallos y reintentos | `test_each_staged_write_failure_rolls_back_entire_operation`, `test_rejected_commit_does_not_persist_any_staged_document`, `test_same_decision_retries_return_identical_records`, `test_simultaneous_identical_likes_converge_to_same_pending_candidate`, `test_internal_failures_are_safe_for_both_endpoints`: rollback, estado final y retry idempotente. | Parcial (solo backend): mensajes/control de reintento de UI no verificados. |

La suite completa también ejecuta el flujo de Auth con Auth Emulator; el test
de rol específico de CA-01 inyecta identidad/perfil y no prueba Auth.

No se ejecutaron Azure Blob ni Firestore de producción, no se desplegaron los
índices remotos ni se lanzó CI remoto. La persistencia real verificada aquí es
la del Firestore Emulator; las pruebas de rollback usan Firestore Emulator con
fallos de escritura inyectados. No hay linter/formatter Python configurado.

## Verificación integrada US 4.10 (histórica, anterior a US5.8)

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
| CA-03 — Creación del match | El comportamiento de esa versión confirmaba LIKE sin aceptación. | **Supersedido:** consultar CA-02/CA-04 de US5.8 abajo. |
| CA-04 — Aviso al Vendedor | El aviso de esa versión se creaba para el propietario al recibir LIKE. | **Supersedido:** el aviso actual se crea al aceptar y se dirige al Comprador. |
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

## Continuidad US 7.4: consulta de notificaciones (histórica)

El endpoint GET acepta BUYER y SELLER, pero los resultados siempre se filtran
por el UID del perfil autenticado. `uid` y `recipient_uid` no son parámetros
permitidos; el cursor firmado queda asociado al UID, por lo que tampoco se puede
reutilizar desde otra cuenta. La operación es solo lectura y conserva el orden
descendente estable por fecha/ID.

La ejecución de US7.4 probó lectura propia de avisos para BUYER y SELLER,
paginación, aislamiento, revocación y re-login con Auth/Firestore Emulator y
Azure Blob mock. Su afirmación histórica de aviso al propietario al recibir LIKE
queda supersedida: en el contrato actual el aviso se produce para el Comprador
tras la aceptación.

La UI está cubierta con 25 tests Node y navegador con Auth Emulator y API
interceptada; esos mocks verifican estados, reintentos, actualización,
paginación sin IDs repetidos, fecha/hora y viewports 1280×900/390×844. Lint y
build finalizan con advertencias preexistentes; no se probó hardware móvil.

La UI y su verificación histórica pertenecen a US7.4. US5.8 no añade una
pantalla de candidatos/matches del Vendedor ni de matches del Comprador.

## US5.8: APIs, permisos y transiciones del match

Validación ejecutada con el comando de este proyecto, usando Auth y Firestore
Emulator en loopback y Azure Blob mockeado. Resultado final: **182 tests pasan,
sin omisiones**; `manage.py check` no detectó incidencias. La primera ejecución
detectó timestamps no serializables al generar el cursor de candidatos; se
normalizaron en el servicio y la suite completa se repitió correctamente.

| CA | Prueba automatizada y método | Resultado y límites |
|---|---|---|
| CA-01 — Consulta de matches del Comprador | `test_accept_and_reject_are_persistent_idempotent_and_independent`, `test_two_buyers_create_independent_matches_with_same_home` y el flujo Auth real consultan GET `/api/matches` como BUYER. | **Pasa con Firestore Emulator**; no hay UI de matches. |
| CA-02 — Interés mutuo obligatorio | `test_like_creates_one_pending_candidate_without_confirming_a_match` verifica que LIKE no escribe match y que la lista del Comprador está vacía antes de ACCEPT. | **Pasa con Firestore Emulator.** |
| CA-03 — Consulta de candidatos del Vendedor | `test_candidates_and_matches_are_scoped_by_verified_owner_and_role` y `test_match_and_candidate_lists_paginate_and_return_empty_distinctly` verifican titularidad, comprador/vivienda y cursor. | **Pasa con Firestore Emulator**; permisos usan perfil mockeado y el flujo integrado usa Auth Emulator. |
| CA-04 — Confirmación del match | `test_accept_and_reject_are_persistent_idempotent_and_independent`, `test_two_buyers_create_independent_matches_with_same_home` y `FirebaseFlowTests.test_published_multi_photo_listings_survive_full_buyer_flow` comprueban las listas de ambos roles. | **Pasa con Firestore Emulator.** |
| CA-05 — Rechazo de candidatura | `test_accept_and_reject_are_persistent_idempotent_and_independent` comprueba desaparición de pendientes y ausencia de match/aviso. | **Pasa con Firestore Emulator.** |
| CA-06 — Privacidad e independencia | `test_candidates_and_matches_are_scoped_by_verified_owner_and_role` comprueba 403/404 para rol/propietario ajenos y estado final; `test_two_buyers_create_independent_matches_with_same_home` verifica dos matches para la misma vivienda. | **Pasa con Firestore Emulator**; autorización unitaria usa Auth mockeado. |
| CA-07 — Persistencia y ausencia de duplicados | `test_accept_and_reject_are_persistent_idempotent_and_independent` repite ACCEPT/REJECT y compara IDs y fechas persistidos; el flujo conserva estado al re-login. | **Pasa con Firestore/Auth Emulator.** |
| CA-08 — Listas vacías y errores | `MatchApiTests.test_invalid_payloads_identifiers_and_query_are_rejected`, `test_simultaneous_accept_and_reject_have_one_atomic_winner` y `test_accept_creation_failures_roll_back_decision_match_and_notice`. | **Pasa con mocks y emulador:** carrera real con barrera/hilos, fallo inyectado y verificación del estado final. |

Suposiciones y límites: el ID de candidatura es la clave canónica buyer-vivienda;
un reintento de LIKE devuelve el estado actual y no revierte la decisión del
Vendedor. Registros históricos LIKE+match sin estado se tratan como aceptados;
no se migraron datos externos. El aviso se crea para el Comprador al aceptar.
No se desplegaron/verificaron índices de producción ni se usaron servicios
reales; no se implementaron pantallas de candidatos o matches.

La interfaz BuyerHome se ajustó para distinguir PENDING, ACCEPT y REJECT y
evitar mostrar un éxito de match antes de la aceptación. Frontend: 25 tests pasan;
lint y build pasan, con warnings de lint ya existentes. No hubo validación
visual de esta interfaz en navegador/hardware físico para US5.8.

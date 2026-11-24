# US9.4–9.6: selección definitiva (backend)

Implementación aditiva sobre Django HTTP en Render, Firebase Auth y Firestore
Standard. No hay ORM, sesiones Django, Cloud Functions, chat, pagos ni adjudicación
por plazas. `people` conserva el significado US3 y nunca se decrementa.

## Identidad y permisos

Todas las rutas requieren `Authorization: Bearer <Firebase ID token>` verificado
por Admin SDK, incluida revocación US6. `request.user.uid` y el rol del perfil
consultado en servidor son las únicas fuentes de permisos. Las cookies no
autentican; CSRF de sesión no aplica. Los IDs del cuerpo no acreditan identidad.
El propietario se revalida contra `listings.seller_uid` dentro de cada transacción;
la propuesta también debe pertenecer a la cuenta consultante. La selección usa
el comprador del match original, nunca uno enviado por el cliente.

## Contrato HTTP

Respuestas y errores siguen `JsonResponse`: errores `{"error":"mensaje seguro"}`,
validación de edición `{"errors":{...}}`. Las consultas llevan `Cache-Control`
privado sin caché. Los cuerpos de mutación son objetos JSON, sin campos adicionales.

| Método | Ruta | Rol / cuerpo | Resultado |
|---|---|---|---|
| GET | `/api/propuestas` | BUYER/SELLER; `limit`, `cursor` | `items`, `next_cursor`, historial propio completo. |
| POST | `/api/propuestas` | SELLER; `listing_id`, `match_id`, `request_id` | 201 nueva; 200 repetición idéntica. |
| GET | `/api/propuestas/{id}` | BUYER destinatario / SELLER propietario | Propuesta, vivienda con condiciones actuales y vendedor `{id,name}`. |
| POST | `/api/propuestas/{id}/aceptar` | BUYER; `{}` | 200 ACCEPTED y cierre atómico. |
| POST | `/api/propuestas/{id}/rechazar` | BUYER; `{}` | 200 REJECTED. |
| POST | `/api/propuestas/{id}/cancelar` | SELLER; `{}` | 200 CANCELLED. |
| PATCH | `/api/inmuebles/{id}` | SELLER; todos los campos canónicos de US3, sin fotos | 200 vivienda editada. |
| PUT | `/api/inmuebles/{id}/disponibilidad` | SELLER; `{"availability":"ACTIVE"}` o PAUSED | 200 `{id,availability}`. |

Ejemplo de creación:

```json
{"listing_id":"home-123","match_id":"match-confirmado","request_id":"uuid-generado-por-consumidor"}
```

La respuesta de propuesta incluye `id`, `listing_id`, `match_id`, `request_id`,
`status`, `created_at`, `resolved_at`, `resolved_by`. Fechas UTC del servidor;
los dos últimos campos son null en PENDING. No se serializa el documento interno
de coordinación. El detalle añade `listing` con los campos US3, `availability`
y `closure_reason`, y `seller` con identificación permitida por US5.

El PATCH incorpora un contrato nuevo porque no había operaciones de edición:
requiere exactamente `title`, `street`, `city`, `postal_code`, `description`,
`price`, `surface`, `bedrooms`, `bathrooms`, `people`, `shared_accommodation`.
Reutiliza la validación US3 (incluidos Sí/No para `shared_accommodation`), conserva
las fotos y solo modifica los campos editables. No es una carga de fotos nueva.

400: datos/JSON/cursores inválidos. 401: token ausente, inválido o revocado.
403: rol incorrecto. 404: recurso inexistente o ajeno para un rol autorizado.
409: match no confirmado, anuncio cerrado, otra propuesta pendiente, cambio de
contenido de una clave usada, resolución incompatible o edición/disponibilidad
bloqueada. 405: método no admitido. 500: fallo interno, sin detalles sensibles.
Las lecturas de historial US5 conservan sus filtros y códigos previos.

`request_id` es una cadena no vacía de hasta 128 caracteres y válida como ID
Firestore. La clave se vincula al UID del vendedor y al contenido exacto
`listing_id,match_id,request_id`. Repetirla, previa autorización, devuelve la
propuesta original incluso resuelta (200); cambiar contenido produce 409.
Después de rechazo/cancelación se necesita una clave nueva. Repetir exactamente
una resolución autorizada devuelve 200 con el resultado persistido; contradecirla
produce 409. ACCEPTED es definitivo.

## Persistencia e integridad

- `selection_proposals/{SHA256(JSON([seller_uid,request_id]))}`: referencias a
  vivienda, match y comprador, vendedor, clave, estado y fechas/autores.
- `selection_requests/{misma-clave}`: contenido original de la solicitud.
- `listing_selections/{listing_id}`: `pending_proposal_id`,
  `accepted_proposal_id`, `selected_buyer_uid`, `selected_match_id`.
  Las referencias a la selección solo viven en estos documentos privados.
- `listings`: nuevos campos públicos no identificativos `availability`,
  `closure_reason`, `closed_at`. No se cambia `published` al cerrar.
- `selection_notification_events/{id-determinista}`: lotes privados con vivienda,
  título, destinatarios elegibles al cierre, estado de procesamiento y fechas.

Solo un control por vivienda permite reservar el estado PENDING o ACCEPTED;
no se comprueba unicidad con consulta y escritura independiente. Las lecturas
preceden a todas las escrituras y el callback no llama proveedores externos.
Los timestamps nuevos usan `SERVER_TIMESTAMP`; se relee el resultado persistido.
Se reutiliza el patrón de reintentos acotados para abortos/contención de US4/5.

Se permite proponer en ACTIVE o PAUSED y se conserva la disponibilidad mientras
está PENDING. El rechazo/cancelación solo libera el control. Aceptar conserva
los matches, fija la selección y escribe CLOSED con «Alquiler acordado» en el
mismo commit. Editar o cambiar disponibilidad consulta el control y la vivienda
en transacción; ni una selección pendiente ni una aceptada pueden eludirse.

Exploración y opciones de filtro excluyen CLOSED/PAUSED. Crear intereses lee la
vivienda en transacción y requiere ACTIVE; las confirmaciones nuevas comprueban
que no esté CLOSED. Los reintentos idénticos de operaciones previas se conservan.
El mismo documento de vivienda serializa cierre frente a intereses y matches:
un nuevo interés que precede al cierre entra en el conjunto de avisos, y uno
posterior se rechaza. US5 mantiene sus estados, historial, filtros y cursores;
ambos roles reciben `listing.availability` y `listing.closure_reason`.
Las candidaturas del comprador en otras viviendas no se modifican.

## Avisos US7

Se reutiliza `notifications` y su consulta por destinatario, fecha/ID y cursor.
La creación avisa al comprador; aceptación/rechazo al vendedor; cancelación al
comprador. El cierre avisa una vez a cada otro comprador con candidatura
PENDING (también registros antiguos sin estado) o match CONFIRMED de esa vivienda.
Se deduplica por UID y se excluye al elegido. Los avisos de cierre solo incluyen
tipo, texto, destinatario, vivienda/título y fecha: no llevan comprador elegido,
match, propuesta ni referencia privada de selección.

Hasta 100 destinatarios de cierre, todos los avisos se escriben en la misma
transacción que la operación, con ID SHA256 determinista por evento/tipo/UID.
Un fallo de preparación o persistencia revierte la transacción completa. Si se
pierde la respuesta después del commit, repetir recupera el resultado persistido.

Con más de 100 destinatarios, la transacción de aceptación persiste el aviso al
vendedor y eventos duraderos en lotes de hasta 100 UID; el conjunto de destinatarios
se congela al cierre, deduplicado y sin el elegido. Un fallo al persistir un evento
revierte la aceptación. El procesador crea los avisos de cada lote y lo marca
completado en una sola transacción. Entregas repetidas o procesadores concurrentes
no duplican avisos; un fallo conserva pendientes los lotes no completados.
La API intenta procesar hasta diez lotes después del commit. Un fallo de entrega
no revierte un cierre ya confirmado: queda registrado y se puede recuperar.

El proyecto no tenía un procesador asíncrono US7. Se incorpora un comando Django
sin servicios externos nuevos, para recuperación y ejecución periódica operativa:

```powershell
.\.venv\Scripts\python.exe -B manage.py process_selection_notifications --limit 100
```

`--limit` es el máximo de lotes por ejecución (1–1000). Repetir hasta obtener
`Lotes procesados: 0`. Antes de producción, programar su ejecución periódica con
la configuración Firebase del backend; esta tarea no configura ni despliega un
planificador remoto. Los documentos procesados se conservan como registro.
Cada transacción sigue sujeta a las cuotas y límites generales de Firestore;
no se descartan destinatarios ni se confirma un cierre sin avisos o eventos.

## Compatibilidad, índices y acceso directo

La ausencia de `availability` significa ACTIVE si `published` es true, PAUSED
en otro caso. Control inexistente significa sin propuesta/selección. No se añade
un filtro Firestore por campos nuevos que pudiera excluir documentos antiguos;
exploración mantiene su consulta indexada por publicación y filtra disponibilidad
en servidor. No se requiere backfill US9. Los estados terminales se conservan.

`firestore.indexes.json` añade índices de `selection_proposals` para cada uno de
`seller_uid` y `buyer_uid`, con `created_at DESC, __name__ DESC`. El comando de
publicación de índices sigue siendo el del README; no se ha desplegado nada.
Los emuladores no certifican que los índices compuestos estén habilitados en
producción: comprobarlo antes del despliegue.

La inspección de `frontend/src` no encontró accesos directos Firestore. El cliente
se autentica contra Auth y consume la API; el servidor Admin omite las Rules y
por eso impone los permisos anteriores. Las reglas locales versionadas
`tests/firestore.rules` deniegan todas las lecturas/escrituras de clientes,
incluidas las colecciones nuevas. Se conserva ese cierre total. La documentación
de infraestructura declara las reglas de producción cerradas; no se inspeccionó
ni modificó el proyecto remoto. No usar reglas permisivas en producción.

## Verificación

Suite: `manage.py test accounts properties`; los emuladores se ejecutan con el
comando del README. Las pruebas nuevas están en `properties/test_proposals.py`.
Cubren API, autenticación/roles, recursos ajenos, creación y tres resoluciones,
idempotencia y conflictos, estados antiguos, ACTIVE/PAUSED, bloqueo de gestión,
concurrencia de creaciones y aceptación/cancelación, cierre/interés/confirmación,
rollback de avisos/eventos, recuperación entre lotes sin duplicación, paginación,
persistencia tras nuevo cliente y nuevo login,
avisos privados y conservación de otras viviendas. US9 usa Firestore real emulado;
su prueba de reautenticación usa también Auth Emulator sin simular ID tokens.
La creación comprueba además el perfil BUYER destinatario en la transacción.
Las pruebas REST directas usan un ID token de Auth Emulator contra las Rules.
Azure sigue simulado por la suite existente y US9 no lo modifica.

Los resultados finales de la ejecución se registran en el README del backend.


Verificación US9 (16/11/2026): **228 tests correctos, sin omisiones**, suite
completa `accounts properties` con Auth Emulator y Firestore Emulator Standard
en loopback (`demo-swipehome-us4`), Python 3.13 y Java 21. Incluye 17 pruebas US9
nuevas: permisos y contratos, estados y bloqueos, idempotencia, concurrencia,
rollback de avisos/eventos, recuperación tras fallo entre lotes, privacidad,
historial, otras viviendas, autenticación real emulada y denegación REST por Rules.
Azure se mantiene simulado por las pruebas existentes. `manage.py check`,
`makemigrations --check --dry-run`, `pip check`, sintaxis Python/JSON y
`git diff --check` correctos. No se han usado servicios de producción ni se han
realizado despliegues, commits o push. Los índices compuestos deben publicarse y
comprobarse en producción: el emulador no certifica su disponibilidad. También
queda por configurar allí la ejecución periódica del comando de recuperación.

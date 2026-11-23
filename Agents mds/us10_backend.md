# US10.4–10.6: Gestión de anuncios propios (backend)

Implementación aditiva sobre Django HTTP en Render, Firebase Auth y Firestore Standard.
Reutiliza el stack de US3/US4/US9 sin modificar contratos existentes.

## Identidad y permisos

Todas las rutas requieren `Authorization: Bearer <Firebase ID token>` y rol `SELLER`.
El propietario se revalida contra `listings.seller_uid` dentro de cada transacción.
Los IDs del cuerpo no acreditan identidad ni propiedad.

## Contrato HTTP

| Método | Ruta | Función |
|---|---|---|
| `GET` | `/api/inmuebles/mios` | Consultar publicaciones propias (CA-01, CA-07). |
| `GET` | `/api/inmuebles/{id}/gestion` | Detalle de un anuncio propio para gestionarlo (CA-01, CA-07). |
| `PATCH` | `/api/inmuebles/{id}` | Modificar datos y fotografías con control de versión (CA-02, CA-03, CA-07, CA-08). |
| `POST` | `/api/inmuebles/{id}/pausar` | Pausar un anuncio activo (CA-04). |
| `POST` | `/api/inmuebles/{id}/reactivar` | Reactivar un anuncio pausado (CA-04). |
| `POST` | `/api/inmuebles/{id}/retirar` | Cerrar manualmente el anuncio (CA-05). |

> [!NOTE]
> La ruta `PATCH /api/inmuebles/{id}` acepta `application/json` (solo campos editables) y
> `multipart/form-data` (campos + fotografías nuevas). Para PATCH multipart, Django no
> rellena `request.POST/FILES` automáticamente; la vista usa `MultiPartParser` directamente.

### Respuesta de listado (`GET /api/inmuebles/mios`)

```json
{
  "items": [{
    "id": "...", "title": "...", "availability": "ACTIVE",
    "closure_reason": null,
    "version": 2,
    "has_pending_proposal": false,
    "can_edit": true, "can_pause": true, "can_reactivate": false, "can_withdraw": true,
    "actions": ["edit", "pause", "withdraw"],
    ...
  }]
}
```

### Control de versión

Toda mutación de un anuncio existente debe enviar `"version": N`. Las escrituras
que cambian el anuncio incrementan `version`; si la versión almacenada no coincide,
se devuelve `409`.

Repetir una transición idéntica con la versión inmediatamente anterior (por ejemplo,
reintentar una pausa tras perder la respuesta) devuelve `200` con el estado persistido.
Las peticiones más antiguas o las transiciones incompatibles devuelven `409`.

## Estados y transiciones

```
ACTIVE  --pausar-->   PAUSED
PAUSED  --reactivar-> ACTIVE
ACTIVE  --retirar-->  CLOSED (closure_reason: WITHDRAWN)
PAUSED  --retirar-->  CLOSED (closure_reason: WITHDRAWN)
CLOSED  → no se reabre desde esta US
```

Motivos de cierre persistidos:
- `WITHDRAWN`: retirada manual por el propietario (esta US).
- `RENTED` / `"Alquiler acordado"`: cierre por selección aceptada (US9).

## Reglas de negocio

- Se puede editar un anuncio ACTIVE o PAUSED.
- Los anuncios CLOSED se devuelven en el listado (solo lectura); editar → 409.
- Mientras existe una propuesta pendiente (`listing_selections.pending_proposal_id`),
  ninguna operación de edición ni cambio de disponibilidad está permitida → 409.
- Pausar impide nuevos swipes (explorador excluye PAUSED/CLOSED); conserva candidatos y matches.
- Reactivar no elimina decisiones anteriores de Compradores.
- Retirar genera avisos `LISTING_CLOSED` para candidatos PENDING y CONFIRMED (US7).
  Los avisos usan el mensaje "La vivienda ya no está disponible: Retirada por el propietario."
- Ninguna edición puede dejar el anuncio sin al menos una fotografía válida.
- No se permite cambiar `id` ni `seller_uid` (propietario) en el body.
- La edición de fotos conserva las URLs existentes indicadas en `existing_photos` / `retained_photos`
  y añade las nuevas subidas. Las fotos eliminadas se limpian de Azure Blob Storage con
  recuperación ante fallos (solo log de warning en error de limpieza).

## Persistencia

Campos nuevos en `listings`:
- `availability` (string): `"ACTIVE"` | `"PAUSED"` | `"CLOSED"`.
- `closure_reason` (string | null): `"WITHDRAWN"` | `"Alquiler acordado"` / `null`.
- `version` (int, empieza en 1): incrementa en cada escritura exitosa.
- `updated_at` (timestamp): fecha de la última modificación.

Los documentos existentes sin `availability` siguen siendo válidos:
`listing_availability(data)` devuelve `"ACTIVE"` si `published` es `True`, `"PAUSED"` si no.
Los documentos sin `version` se tratan como versión `1`.

La función `create_listing` ya establece `availability="ACTIVE"`, `version=1` y `updated_at`
en los anuncios nuevos.

## Respuestas de error

- `400`: datos inválidos, fotografía sin formato correcto, intento de cambiar id/propietario.
- `401`: token ausente, inválido o revocado.
- `403`: rol distinto de SELLER.
- `404`: recurso inexistente o ajeno.
- `409`: estado incompatible (cerrado, pendiente, versión desactualizada).
- `500`: error interno, sin detalles sensibles.

## Tests implementados

**ManagementHttpTests** (sin servicios externos, siempre pasan):
- `test_authentication_and_role_requirements`: 401 sin sesión, 403 con rol incorrecto para los 6 endpoints.
- `test_invalid_document_ids_and_not_found`: IDs inválidos → 404; recurso ajeno → 404.
- `test_patch_validation_cannot_change_id_or_owner`: 400 al intentar cambiar `id` o `seller_uid`/`owner`/`propietario`.
- `test_patch_validation_photos_and_version`: fotos vacías → 400; versión inválida → 400; VersionConflict → 409; RuntimeError → 500 sin secretos.

**ManagementFirestoreTests** (requieren `FIRESTORE_EMULATOR_HOST`):
- `test_ca01_my_listings_query_isolation_and_actions`: listado, aislamiento de propietarios, detalle, acciones correctas, 404 por propietario ajeno.
- `test_ca02_ca03_edit_listing_data_and_photos`: edición de datos, retiro de foto, persistencia, foto ajena → 400, versión desactualizada → 409.
- `test_ca04_pause_and_reactivate`: pausa, idempotencia, exclusión del explorador, swipe bloqueado (409), reactivación, idempotencia, visibilidad restaurada.
- `test_ca05_withdraw_listing_and_notifications`: retirada, idempotencia, reapertura bloqueada (409), pausa bloqueada (409), edición bloqueada (409), avisos correctos, historial conservado.
- `test_ca06_pending_selection_proposal_blocks_edition_and_availability`: propuesta pendiente bloquea edición, pausa y retirada (409); respuesta de gestión marca `has_pending_proposal: true`, `can_edit: false`, `actions: []`.
- `test_ca09_multipart_photo_edition_and_cleanup`: edición multipart PATCH con foto nueva + foto existente conservada; versión incrementada; URLs en la respuesta.

## Verificación US10.4–10.6

Suite completa **10/10 tests** con Auth+Firestore Emulator, sin omisiones.
Tests de US9 (proposals) siguen pasando: **17/17 OK**.

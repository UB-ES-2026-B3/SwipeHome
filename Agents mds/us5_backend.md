# US 5: Confirmación y visualización de matches y candidaturas

Estado comprobado el 10 de noviembre de 2026. Siguiendo las pautas de `Agents mds`,
el backend de las US 5.4–5.7 (incluyendo US 5.7.1) está implementado con **Firebase Auth y Firestore**,
conservando la arquitectura, colecciones y autenticación Bearer por token del proyecto.

## Estado funcional y contratos

| US | Endpoint | Rol | Resultado implementado |
|---|---|---|---|
| 5.4 | GET `/api/matches` | BUYER, SELLER | Para BUYER: devuelve exclusivamente sus matches `CONFIRMED` con datos de la vivienda (`listing_item`). Para SELLER: devuelve matches `CONFIRMED` con datos del comprador y vivienda. Filtro opcional `inmueble`. Paginación por cursor firmado sobre `confirmed_at DESC, __name__ DESC`. |
| 5.4 | GET `/api/candidatos` | SELLER | Devuelve exclusivamente candidaturas `PENDING` de viviendas del propietario autenticado, con datos del comprador y vivienda. Filtro opcional `inmueble`. Paginación estable sobre `created_at DESC, __name__ DESC`. Un BUYER recibe 403. |
| 5.5 | POST `/api/matches/{id}/decision-vendedor` | SELLER | Decisión del propietario sobre candidatura pendiente. `decision`: `LIKE` (pasa a `CONFIRMED`, fija `confirmed_at` y `decided_at`) o `PASS` (pasa a `REJECTED`, fija `decided_at`). No crea nuevo registro. Idempotente (200 ante misma decisión) y conflicto (409 ante decisión contraria). Solo el propietario puede decidir (404 si es ajeno o no existe). |
| 5.6 | Persistencia y estados | Ambos | Reutiliza la colección `matches`. Estados: `PENDING`, `CONFIRMED`, `REJECTED`. Preserva unicidad determinista `key = SHA256(JSON([buyer_uid, listing_id]))`. Actualizaciones atómicas en transacción Firestore. Registros previos sin estado se tratan como `PENDING`. |
| 5.7 / 5.7.1 | POST `/api/inmuebles/{id}/decision` | BUYER | LIKE crea swipe, match con estado `PENDING` y aviso de interés al propietario (`type: INTEREST`, mensaje adaptado). La respuesta incluye `status: "PENDING"`. Repetir LIKE devuelve el match sin duplicar ni alterar su estado si el vendedor ya decidió. PASS solo crea swipe. |

## Estados del Match

| Estado | Significado | ¿En «Mis matches» del Comprador? | ¿En «Matches» del Vendedor? | ¿En «Candidatos» del Vendedor? |
|---|---|---|---|---|
| `PENDING` | El Comprador mostró interés; el Vendedor aún no ha decidido. | No | No | Sí |
| `CONFIRMED` | Comprador y Vendedor mostraron interés mutuo. | Sí | Sí | No |
| `REJECTED` | El Vendedor rechazó la candidatura. | No | No | No |

## Arquitectura y Autenticación

- `accounts.authentication.firebase_role` soporta múltiples roles (e.g. `@firebase_role("BUYER", "SELLER")`) manteniendo compatibilidad estricta con llamadas univaluadas.
- La identidad proviene siempre del Bearer token verificado contra Firebase Auth y las revocaciones US6; el rol se resuelve del perfil en Firestore (`request.user`).
- El filtro `inmueble` valida la relación con el usuario: si un SELLER intenta consultar un inmueble ajeno o un BUYER un inmueble con el que no interactuó, se devuelve 403. IDs malformados devuelven 400.
- Paginación basada en cursores firmados con `DJANGO_SECRET_KEY`, usando nanosegundos y sin OFFSET. Para matches se indexa por `confirmed_at DESC`; para candidatos por `created_at DESC`. Confirmar o rechazar candidatos en una página no produce saltos ni duplicados al solicitar la siguiente página.

## Verificación

- **170 pruebas totales**:
  - Sin emuladores: **138 correctas y 32 integraciones omitidas**.
  - Con emuladores locales (Auth 9099 y Firestore 8080 en loopback, proyecto `demo-swipehome-us4`): **170 correctas, sin omisiones** (`Ran 170 tests... OK`).
- Incluyen:
  - Pruebas unitarias de autorización, parámetros, contratos y respuestas (`test_matches.py`).
  - Pruebas de integración con emulador real (`test_firestore_matches.py`): ciclo completo de LIKE Comprador -> PENDING -> decisión Vendedor -> CONFIRMED/REJECTED, idempotencia, colisiones concurrentes (hilos con `Barrier`), privacidad entre vendedores y estabilidad de cursores entre páginas.
- Comprobaciones Django: `manage.py check` (0 issues), `makemigrations --check --dry-run` (sin cambios pendientes), diff limpio.

## Archivos de implementación

- `backend/accounts/authentication.py`: soporte multi-rol en `@firebase_role`.
- `backend/accounts/pagination.py`: soporte de `allowed_fields` y `timestamp_field` en cursores.
- `backend/accounts/repository.py`: `record_seller_decision`, `get_candidates`, `get_confirmed_matches`, `get_listing` y actualización de `record_decision` con estado `PENDING`.
- `backend/properties/match_service.py`: lógica de negocio, verificación de propiedad y formateo de resultados.
- `backend/properties/match_views.py`: controladores HTTP para `/api/matches`, `/api/candidatos` y `/api/matches/{id}/decision-vendedor`.
- `backend/properties/discovery_service.py`: inclusión de `status` en el match devuelto al Comprador.
- `backend/config/urls.py`: mapeo de rutas.
- `backend/firestore.indexes.json`: índices compuestos para consultas de matches y candidatos.
- `backend/properties/test_matches.py` y `backend/properties/test_firestore_matches.py`: suites de pruebas.
- `frontend/src/pages/BuyerHome.jsx`: feedback ajustado a «Interés enviado».

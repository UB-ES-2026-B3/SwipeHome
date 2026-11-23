# Cobertura funcional de SwipeHome

La matriz toma los CA de US5 documentados en [US4/US5.8](<../Agents mds/us4_backend.md>), los recorridos de US5.9 y US8.6 del [README de backend](../backend/README.md), y los CA de US9.7 y US9.8 de [resultado.md](../resultado.md).

**Antes de esta ampliación.** US5.8 tenía pruebas de API y carreras reales en Firestore. US5.9 y US8.6 combinaban integración de backend con comprobaciones históricas de navegador con API simulada. US9.7 tenía nueve integraciones HTTP. US9.8 ya tenía cuatro E2E con los emuladores. Faltaban componentes montados, recorridos con backend real para matches y filtros, y pruebas de almacenamiento real que acompañaran esos flujos.

Las evidencias nuevas están en [componentes](../frontend/component/flows.spec.mjs), [integración](../backend/properties/workflow_integration.py), [escenarios E2E](../backend/properties/workflow_e2e.py) y [pasos de navegador](../frontend/e2e/workflows.mjs). En las tablas, «Auth y Firestore» son sus emuladores locales. «Azurite» es Blob Storage emulado. Las verificaciones de componentes usan Chrome real con dependencias simuladas.

## US5.8 — Candidaturas y matches

| CA | Test y ubicación | Tipo / resultado | Servicios y límites |
|---|---|---|---|
| CA-01. Consultar matches propios | [`test_accept_and_reject_are_persistent_idempotent_and_independent`](../backend/properties/test_firestore.py), [`test_interest_confirmation_and_rejection`](../backend/properties/workflow_e2e.py). | Integración y E2E · PASS CON EMULADORES | Firestore en API y Auth/Firestore/Azurite en navegador. |
| CA-02. Interés mutuo | [`test_like_creates_one_pending_candidate_without_confirming_a_match`](../backend/properties/test_firestore.py), [US 5.8 interés pendiente](../frontend/component/flows.spec.mjs). El E2E consulta «Mis matches» antes de confirmar. | Integración y E2E · PASS CON EMULADORES. Componente · PASS CON MOCKS | Auth simulado en el caso de repositorio y real en el E2E. |
| CA-03. Candidatos del propietario | [`test_candidates_and_matches_are_scoped_by_verified_owner_and_role`](../backend/properties/test_firestore.py), [`test_interest_confirmation_and_rejection`](../backend/properties/workflow_e2e.py). | Integración y E2E · PASS CON EMULADORES | El propietario ve comprador y vivienda. El otro Vendedor ve el vacío. |
| CA-04. Confirmar | [`test_publication_azurite_photos_survive_confirmed_match`](../backend/properties/workflow_integration.py) compara URLs, contenido y el mismo match en ambas cuentas. E2E de matches. | Integración y E2E · PASS CON EMULADORES | Auth, Firestore y Azurite. |
| CA-05. Rechazar | [`test_interest_confirmation_and_rejection`](../backend/properties/workflow_e2e.py) recupera el rechazo después de una desconexión y comprueba los documentos. | E2E · PASS CON EMULADORES | Se provoca desconexión de Chrome. Firestore conserva el rechazo sin match. |
| CA-06. Independencia y privacidad | [`test_two_buyers_create_independent_matches_with_same_home`](../backend/properties/test_firestore.py) y E2E de matches con dos Compradores y dos Vendedores. | Integración y E2E · PASS CON EMULADORES | Auth simulado en el caso de dos matches y emulado en navegador. |
| CA-07. Persistencia e idempotencia | [`test_accept_and_reject_are_persistent_idempotent_and_independent`](../backend/properties/test_firestore.py) comprueba IDs y fechas. El E2E recarga la lista del Comprador. | Integración y E2E · PASS CON EMULADORES | La operación equivalente se verifica por API. |
| CA-08. Vacíos, errores y atomicidad | [`MatchApiTests`](../backend/properties/test_discovery.py), [`test_simultaneous_accept_and_reject_have_one_atomic_winner`, `test_accept_creation_failures_roll_back_decision_match_and_notice`](../backend/properties/test_firestore.py) y [US 5.9 candidaturas paginadas](../frontend/component/flows.spec.mjs). | Unitario/componente · PASS CON MOCKS. Integración · PASS CON EMULADORES | Fallo de escritura inyectado y estado final real. |

## US5.9 — Recorrido y presentación de matches

| CA | Test y ubicación | Tipo / resultado | Servicios y límites |
|---|---|---|---|
| CA-01. Lista del Comprador | [`test_interest_confirmation_and_rejection`](../backend/properties/workflow_e2e.py) consulta lista vacía y la recarga después de confirmar. [US 5.9 matches privados](../frontend/component/flows.spec.mjs) cubre cursor y disponibilidad. | E2E · PASS CON EMULADORES. Componente · PASS CON MOCKS | Chrome, Auth y Firestore. |
| CA-02. Mostrar interés pendiente | El mismo E2E muestra interés enviado y lista sin matches antes de ACCEPT. [US 5.8 interés pendiente](../frontend/component/flows.spec.mjs) cubre confirmación incoherente y retry. | E2E · PASS CON EMULADORES. Componente · PASS CON MOCKS | El componente simula el 2xx incoherente. |
| CA-03. Candidatura y vivienda | E2E de matches muestra ambos candidatos en dos viviendas. [US 5.9 candidaturas paginadas](../frontend/component/flows.spec.mjs) verifica cursor y conservación de los resultados. | E2E · PASS CON EMULADORES. Componente · PASS CON MOCKS | Una foto se carga desde Azurite en el explorador. |
| CA-04. Aceptación en ambas listas | E2E de matches y [`test_published_multi_photo_listings_survive_full_buyer_flow`](../backend/properties/test_firestore.py). | E2E e integración · PASS CON EMULADORES | Azure simulado en el caso histórico, Azurite en el E2E. |
| CA-05. Rechazo y desaparición | E2E de matches rechaza con teclado después de un fallo de red, confirma el vacío y comprueba que el Comprador rechazado carece de match. | E2E · PASS CON EMULADORES | Desconexión controlada en el navegador. |
| CA-06. Cuentas y viviendas independientes | E2E de matches verifica otro Vendedor, dos Compradores y sus vistas. | E2E · PASS CON EMULADORES | Contextos de Chrome separados. |
| CA-07. Recarga, re-login y duplicados | E2E de matches recarga. La integración [`test_published_multi_photo_listings_survive_full_buyer_flow`](../backend/properties/test_firestore.py) vuelve a iniciar sesión y repite ACCEPT conservando ID. | E2E e integración · PASS CON EMULADORES | El nuevo inicio de sesión de matches se prueba por API. |
| CA-08. Vacíos, errores y reintento | E2E de matches verifica vacío y desconexión. [US 5.9 candidaturas paginadas](../frontend/component/flows.spec.mjs) provoca conflicto y fallo al refrescar. [`MatchApiTests`](../backend/properties/test_discovery.py) comprueba permisos y validación. | E2E · PASS CON EMULADORES. Componente/API aislada · PASS CON MOCKS | El 503 del componente es simulado. Teclado y ancho móvil de 390 px en Chrome. |

## US8.6 — Filtros privados

| CA | Test y ubicación | Tipo / resultado | Servicios y límites |
|---|---|---|---|
| CA-01. Acceso | [`test_preferences_profile_explorer_and_private_reset`](../backend/properties/workflow_e2e.py) abre filtros en explorador y perfil. [`BuyerPreferencesApiTests`](../backend/properties/test_discovery.py) verifica rol. | E2E · PASS CON EMULADORES. API aislada · PASS CON MOCKS | Auth/Firestore reales en emuladores. |
| CA-02. Selección de criterios | [US 8.6 validación accesible](../frontend/component/flows.spec.mjs) comprueba rangos y payload. [`BuyerPreferencesApiTests`](../backend/properties/test_discovery.py) cubre decimales, enteros y alojamiento compartido. | Componente/API aislada · PASS CON MOCKS | El navegador integrado aplica el caso de precio. |
| CA-03. Aplicación | E2E de preferencias cambia la vivienda mostrada. [`test_preferences_invalidate_cursor_and_survive_new_auth_session`](../backend/properties/workflow_integration.py) rechaza el cursor anterior. | E2E e integración · PASS CON EMULADORES | Firestore conserva filtros privados. |
| CA-04. Conservación | E2E de preferencias abre perfil tras guardar en explorador y recarga. La integración usa un inicio de sesión nuevo. | E2E e integración · PASS CON EMULADORES | Auth y Firestore. |
| CA-05. Restablecimiento | E2E de preferencias vuelve a ver viviendas y comprueba directamente que se conserva el PASS anterior. | E2E · PASS CON EMULADORES | Una segunda cuenta conserva sus propios ajustes. |
| CA-06. Sin coincidencias | E2E de preferencias llega al vacío y abre los filtros para restablecer. | E2E · PASS CON EMULADORES | Chrome a 390 px. |
| CA-07. Valores inválidos | E2E verifica el error y `aria-invalid`. [US 8.6 validación accesible](../frontend/component/flows.spec.mjs) comprueba asociación del error y ausencia de escritura. | E2E · PASS CON EMULADORES. Componente · PASS CON MOCKS | El backend valida payloads en la suite aislada. |
| CA-08. Aislamiento entre cuentas | E2E de preferencias compara dos sesiones. [`test_preferences_invalidate_cursor_and_survive_new_auth_session`](../backend/properties/workflow_integration.py) comprueba cuentas y rol SELLER. | E2E e integración · PASS CON EMULADORES | Contextos de navegador separados. |
| CA-09. Fallos y reintento | E2E pierde red al guardar y vuelve a aplicar. [US 8.6 integración de filtros con el explorador](../frontend/component/flows.spec.mjs) retiene bloqueos hasta refrescar. [`test_buyer_preferences_filter_isolation_reset_and_failed_write_are_persistent`](../backend/properties/test_firestore.py) contrasta el estado final. | E2E/integración · PASS CON EMULADORES. Componente · PASS CON MOCKS | Escritura fallida inyectada en la integración. |

## US9.7 — Permisos, concurrencia e integridad

| CA | Test y ubicación | Tipo / resultado | Servicios y límites |
|---|---|---|---|
| CA-01. Match confirmado | [`test_proposal_requires_a_confirmed_match_for_that_home`](../backend/properties/test_selection.py). | Integración · PASS CON EMULADORES | HTTP y Auth/Firestore. Comprueba candidaturas inválidas. |
| CA-02. Consulta y respuesta | [`test_only_the_owner_and_recipient_can_access_or_update_the_proposal`](../backend/properties/test_selection.py) y [E2E de aceptación y rechazo](../backend/properties/selection_e2e.py). | Integración y E2E · PASS CON EMULADORES | Chrome consulta las condiciones vigentes. |
| CA-03. Confirmación definitiva | [`test_acceptance_closes_only_its_home_and_notifies_affected_candidates_privately`](../backend/properties/test_selection.py) y [`test_two_homes_keep_independent_proposal_status`](../backend/properties/workflow_e2e.py). | Integración y E2E · PASS CON EMULADORES | Firestore comprueba el cierre y conserva las otras viviendas. |
| CA-04. Rechazo y cancelación | [`test_reject_cancel_and_delayed_retries_keep_separate_intents_and_notices`](../backend/properties/test_selection.py) y E2E de rechazo/cancelación. | Integración y E2E · PASS CON EMULADORES | Se conserva historial de intenciones. |
| CA-05. Exclusividad | [`test_concurrent_incompatible_proposals_and_repeated_acceptance_have_one_winner`](../backend/properties/test_selection.py), [US 9.7 conflicto de exclusividad](../frontend/component/flows.spec.mjs) y E2E de dos viviendas. | Integración y E2E · PASS CON EMULADORES. Componente · PASS CON MOCKS | Barrera HTTP real en integración. |
| CA-06. Disponibilidad | [`test_acceptance_closes_only_its_home_and_notifies_affected_candidates_privately`](../backend/properties/test_selection.py) y E2E aceptación/dos viviendas. | Integración y E2E · PASS CON EMULADORES | Explorer y matches muestran el cierre. |
| CA-07. Avisos | Casos de [aceptación, rechazo y cancelación](../backend/properties/test_selection.py) comprueban destinatario y ausencia de duplicados. | Integración · PASS CON EMULADORES | Avisos en Firestore y consulta privada HTTP. |
| CA-08. Privacidad | [`test_pending_proposal_on_another_home_stays_private_after_acceptance`](../backend/properties/workflow_integration.py) y E2E de dos viviendas. | Integración y E2E · PASS CON EMULADORES | Se compara el estado de matches y candidaturas ajenos. |
| CA-09. Idempotencia | [`test_reject_cancel_and_delayed_retries_keep_separate_intents_and_notices`](../backend/properties/test_selection.py) y E2E de fallos. | Integración y E2E · PASS CON EMULADORES | Se inyecta pérdida de respuesta tras commit en el E2E. |
| CA-10. Rollback y recuperación | [`test_firestore_rejects_commits_without_partial_proposals_or_closures`, `test_notification_failure_rolls_back_acceptance_and_retry_writes_each_notice_once`](../backend/properties/test_selection.py). | Integración · PASS CON EMULADORES y MOCKS | Firestore real en emulador. Fallos de escritura y aviso controlados. |

## US9.8 — Selección definitiva en navegador

Los cuatro métodos están en [selection_e2e.py](../backend/properties/selection_e2e.py), con pasos en [selection.mjs](../frontend/e2e/selection.mjs). Se comparte la misma cabecera de Vite y fixtures con los E2E anteriores.

| CA | Test y comportamiento | Tipo / resultado | Servicios y límites |
|---|---|---|---|
| CA-01. Envío y recepción | `test_acceptance_availability_privacy_and_new_session` envía desde matches y el comprador abre el aviso con el mismo ID. | E2E · PASS CON EMULADORES | Los matches iniciales se preparan por HTTP. |
| CA-02. Consulta y respuesta | Aceptación y `test_rejection_keeps_home_open_and_allows_another_buyer`. El Comprador ve condiciones y vendedor actualizados y responde por teclado. | E2E · PASS CON EMULADORES | Cambios de condiciones preparados en Auth y Firestore. |
| CA-03. Cierre y dos cuentas | Aceptación comprueba estado en las dos pantallas y selección definitiva almacenada. | E2E · PASS CON EMULADORES | Chrome y Django con Auth/Firestore. |
| CA-04. Rechazo y cancelación | Rechazo y `test_cancellation_invalidates_stale_buyer_and_allows_another_proposal`, con nuevo envío y anuncio aún visible. | E2E · PASS CON EMULADORES | Casos independientes. |
| CA-05. Exclusividad | Aceptación usa una segunda sesión del Vendedor desactualizada y contrasta el 409. | E2E · PASS CON EMULADORES | Carreras simultáneas cubiertas por US9.7. |
| CA-06. Disponibilidad al recargar | Aceptación comprueba explorador, matches y recarga como otro Comprador. | E2E · PASS CON EMULADORES | Dos tamaños de viewport en Chrome. |
| CA-07. Avisos y privacidad | Aceptación, rechazo y cancelación consultan avisos. Los otros candidatos reciben solo datos de la vivienda. | E2E · PASS CON EMULADORES | Avisos internos de la aplicación. |
| CA-08. Permisos | Aceptación y rechazo abren una URL ajena y verifican 404 y ausencia de acciones. | E2E · PASS CON EMULADORES | Contextos separados. |
| CA-09. Persistencia y reintentos | Aceptación vuelve a iniciar sesión. `test_browser_retries_network_failure_and_committed_responses_without_duplicates` conserva la clave tras recarga. | E2E · PASS CON EMULADORES | El 503 se inyecta después del commit. |
| CA-10. Fallos, carga y pantallas obsoletas | E2E de fallos y cancelación. [US 9.8 una propuesta obsoleta](../frontend/component/flows.spec.mjs) fuerza conflicto y fallo de la consulta posterior. | E2E · PASS CON EMULADORES y MOCKS de transporte. Componente · PASS CON MOCKS | Estado final real en Firestore, 503 controlado y red desconectada en Chrome. |

**Fuera de esta cobertura.** Hardware móvil e índices remotos quedan **NO VERIFICADO**. Para las pruebas de componente, persistencia y Azure son **NO APLICA** porque el nivel prueba los estados del DOM y el contrato con sus dependencias.

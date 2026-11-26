# Revisión de US 3.4, 3.5 y 3.6

He revisado la carpeta `Agents mds` y el código de publicación, validación, autenticación y persistencia. **Las tres US son coherentes en su objetivo, pero necesitan concretar el contrato de entrada y la recuperación ante fallos antes de poder considerarse completamente verificables.**

Tomo los límites de imágenes que acabas de proporcionar como requisitos de esta revisión: **1–10 imágenes, máximo 5 MB y formatos JPEG, PNG y WebP**. Los documentos anteriores los mantenían pendientes de ratificación.

La revisión es estática: no he modificado archivos ni ejecutado pruebas.

## 1. Análisis de completitud y lógica

### 1.1. Lagunas y ambigüedades

| Tema | Hallazgo | Propuesta para cerrar el criterio |
|---|---|---|
| Límite de 5 MB | «Máximo» incluye exactamente el límite, pero falta definir su unidad. El código utiliza 5.242.880 bytes, equivalente a 5 MiB. | Elegir **5.000.000 bytes** o **5.242.880 bytes** y usar la misma cifra en frontend, API y pruebas. |
| Tamaño total | Diez imágenes pueden sumar 50 MB o 50 MiB, más campos y envoltorio multipart. | Fijar un límite total de petición que permita ese caso y coordinarlo con servidor y proxy. |
| Timeout | No se especifica qué ocurre si la conexión termina durante la subida o después del guardado. | Definir plazos y distinguir fallo confirmado de resultado desconocido. Incorporar recuperación e idempotencia. |
| Contrato multipart | Faltan nombres canónicos de campos, campo de fotografías y tratamiento de campos repetidos. | Documentar un contrato único; rechazar valores escalares repetidos o contradictorios. |
| Textos | No se fijan longitudes máximas ni tratamiento de caracteres de control. | Acordar límites por campo y reglas de normalización. Escapar los textos al mostrarlos. |
| Precio y superficie | Faltan máximos, precisión, formato decimal y política ante más decimales. | Definir límites y si se rechaza o redondea. Recomiendo rechazar precisión no admitida para evitar cambios silenciosos. |
| Números especiales | «Número mayor que cero» debe excluir `NaN`, infinito y valores fuera del rango de almacenamiento. | Exigir números finitos y representables. Concretar si se admite notación científica. |
| Sí/No | Falta representación técnica en multipart. Ausencia y «No» son casos distintos. | Elegir valores canónicos y convertirlos a booleano después de validarlos. |
| Personas | No está claro si representa plazas ofertadas o capacidad total. | Aclarar su significado. No deducir alojamiento compartido a partir de ese número. |
| Imagen válida | La extensión, MIME declarado y firma inicial no garantizan que una imagen pueda decodificarse. | Exigir validación estructural y decodificación, con límites de recursos. |
| Dimensiones y animación | Una imagen pequeña en bytes puede exigir mucha memoria; PNG/WebP pueden contener animación. | Acordar máximos de dimensiones/píxeles y política sobre animaciones. |
| Orden | Falta concretar cómo se representa y persiste. | Usar una lista ordenada o posiciones explícitas; no depender del orden de finalización de las subidas. |
| Fecha de publicación | Puede confundirse con el inicio del intento. | Generarla en servidor al confirmar la publicación; separar `created_at` y `published_at` si existe un estado intermedio. |
| Errores | No hay formato estable de respuesta ni identificación de la foto inválida. | Devolver errores por campo y posición de imagen, con códigos estables y mensajes comprensibles. |

**Una imagen inválida debe rechazar el conjunto completo.** No debe descartarse silenciosamente y publicarse el resto: US 3.6 exige rechazar si alguna incumple las reglas.

### 1.2. Contradicciones con el contexto del proyecto

1. **Autenticación:** el código actual utiliza Firebase Auth mediante `Authorization: Bearer`, aunque parte de la documentación histórica habla de cookies y sesiones. En estas US, «sesión válida» debe referirse a identidad autenticada mediante el mecanismo vigente. El vendedor procede del token verificado y el rol del perfil consultado por el servidor.

2. **Almacenamiento:** las fotografías de anuncios se guardan en Azure Blob Storage; la API y el repositorio tienen pruebas con Azure simulado. No se debe afirmar que este informe haya probado una subida real a Azure.

3. **Disco local:** no es una solución persistente para el despliegue gratuito actual en Render: los archivos se pierden al reiniciar, redesplegar o suspenderse el servicio. [Documentación de Render](https://render.com/docs/free).

### 1.3. Hallazgos concretos del código

| Severidad | Hallazgo | Consecuencia |
|---|---|---|
| Alta | `validate_photos` comprueba patrones de bytes, sin decodificar la imagen. | Puede aceptar contenido que no sea una imagen válida, incumpliendo US 3.6. |
| Crítica | Si `reference.create()` guarda en Firestore pero se pierde la confirmación, el manejador de excepción borra las fotos. | Puede quedar un anuncio publicado con referencias rotas. |
| Alta | El archivo se añade a la lista de limpieza después de terminar `upload_from_file`. | Una subida completada remotamente cuya confirmación se pierde puede dejar un archivo huérfano. |
| Alta | Si falla un borrado compensatorio, solo se registra un error. | No existe recuperación persistente que garantice su eliminación posterior. |
| Alta | La respuesta incluye `firestore.SERVER_TIMESTAMP` dentro de `listing`. | El marcador no es un timestamp JSON serializable; puede fallar la respuesta después de haber guardado el anuncio. |
| Media | Se aceptan varios alias y se utiliza el primero encontrado. | Valores contradictorios o fotografías en distintos campos pueden quedar ignorados. |
| Media | Los tests usan como JPEG válido una secuencia artificial de bytes. | Pueden pasar aunque no se cumpla la validación real de imágenes. |

Referencias: [validación](C:/Users/Ordinador/Desktop/4tocarrera/Software/SwipeHome/backend/properties/validation.py), [persistencia](C:/Users/Ordinador/Desktop/4tocarrera/Software/SwipeHome/backend/accounts/repository.py), [vista](C:/Users/Ordinador/Desktop/4tocarrera/Software/SwipeHome/backend/properties/views.py) y [tests](C:/Users/Ordinador/Desktop/4tocarrera/Software/SwipeHome/backend/properties/tests.py).

## 2. Estrategia de rollback y transaccionalidad

### 2.1. Garantía que debe ofrecerse

**Una transacción de Firestore no engloba el almacenamiento de archivos.** La solución apropiada es combinar:

- Atomicidad de los cambios dentro de Firestore.
- Archivos privados e identificados por operación.
- Publicación visible únicamente al completar todos los guardados.
- Compensaciones persistentes, idempotentes y recuperables.

Esto ofrece **publicación atómica desde la perspectiva del usuario y limpieza eventual de archivos**, sin prometer una transacción ACID distribuida entre ambos sistemas.

La limpieza inmediata no puede garantizarse si el almacenamiento está caído. Conviene reformular el criterio:

> Ante un fallo confirmado, el anuncio no queda publicado. Los archivos creados se eliminan; si el borrado falla, queda registrada una tarea persistente de limpieza con reintentos.

### 2.2. Flujo técnico recomendado

1. **Autenticar y autorizar.** Obtener el UID verificado y comprobar `SELLER` desde una fuente controlada por el servidor.

2. **Validar toda la solicitud.** Comprobar campos, cantidad, tamaño y contenido de todas las imágenes antes de escribir archivos definitivos.

3. **Registrar una operación persistente.** Generar `operation_id`, identificador del anuncio y claves de los archivos. Guardar el manifiesto previsto antes de subirlos, junto con el propietario y el estado `UPLOADING`.

4. **Subir archivos privados.** Utilizar nombres generados e inmutables. Registrar tamaño, tipo detectado, posición y, cuando proceda, versión del objeto. Una pérdida de confirmación debe poder investigarse por su clave conocida.

5. **Confirmar en Firestore.** Una vez comprobadas todas las imágenes, ejecutar una transacción corta que:
   - Compruebe el estado vigente de la operación.
   - Cree el anuncio con todos sus datos y referencias ordenadas.
   - Establezca `PUBLISHED` y fecha de publicación.
   - Marque la operación como completada.

6. **Responder `201`.** Devolver un cuerpo mínimo serializable, por ejemplo `{"id": "..."}`.

Las subidas y borrados deben quedar fuera de la función transaccional: Firestore puede ejecutarla varias veces por concurrencia. [Documentación de transacciones](https://firebase.google.com/docs/firestore/manage-data/transactions).

### 2.3. Tratamiento de fallos

| Punto de fallo | Actuación |
|---|---|
| Validación | `400`, sin anuncio ni archivos definitivos. |
| Subida de una imagen | No publicar; iniciar compensación de todos los objetos de esa operación. |
| Fallo confirmado de escritura final | Marcar la operación para limpieza y eliminar sus archivos. |
| Timeout de escritura final | Consultar el estado persistido antes de decidir. **No borrar archivos a ciegas.** |
| Caída del proceso | Un reconciliador recupera operaciones incompletas desde el manifiesto persistente. |
| Fallo de borrado | Conservar la tarea pendiente y reintentar. |
| Pérdida de respuesta tras el commit | El reintento devuelve el identificador ya creado. |

El reconciliador debe reclamar la operación mediante una transición transaccional a `CLEANING`. La publicación solo podrá completarse desde un estado autorizado; así se evita que un proceso publique mientras otro elimina sus imágenes.

La limpieza debe afectar exclusivamente a objetos de esa operación. Si se utilizan versiones de objetos, el borrado debe comprobar la versión para evitar eliminar contenido distinto.

### 2.4. Idempotencia y representación de datos

Propongo una clave de idempotencia asociada al usuario:

- Misma clave y mismo contenido: recuperar la misma operación y anuncio.
- Misma clave y contenido diferente: rechazar el conflicto.
- Dos solicitudes simultáneas: una única operación obtiene el derecho a publicar.

Es una ampliación propuesta; actualmente no está garantizada por las US.

Para el precio, **almacenar céntimos como entero** es adecuado si se acuerda un máximo y dos decimales. El código ya utiliza esa representación. Personas y alojamiento compartido deben permanecer como campos independientes.

La elección del proveedor de imágenes sigue pendiente de resolver dentro de la restricción económica del proyecto.

## 3. Casos de prueba críticos: límites y seguridad

**P0:** bloquean la aceptación. **P1:** necesarios para completar la robustez. Los resultados que dependen de decisiones pendientes deben incorporarse al contrato antes de automatizarlos.

### 3.1. Autenticación, permisos y propiedad

| Prioridad | Caso | Resultado esperado |
|---|---|---|
| P0 | Token ausente, malformado, manipulado o caducado | `401`; sin persistencia. |
| P0 | Usuario `BUYER` autenticado | `403`; sin archivos ni anuncio. |
| P0 | Token válido y perfil inexistente o rol no permitido | Rechazo controlado; nunca publicar. |
| P0 | Enviar `seller_uid`, propietario o rol de otro usuario | No altera identidad ni permisos. |
| P0 | Dos vendedores publicando simultáneamente | Cada anuncio y sus imágenes pertenecen al vendedor correcto. |
| P1 | Servicio de verificación o lectura del perfil indisponible | Error interno controlado; no confundirlo con credenciales inválidas. |
| P1 | Escritura directa desde un cliente en Firestore/Storage | No permite saltarse la autorización o establecer `PUBLISHED`. |

### 3.2. Campos y límites

| Prioridad | Caso | Resultado esperado |
|---|---|---|
| P0 | Omitir cada campo obligatorio individualmente | `400`, error del campo, ninguna publicación. |
| P0 | Texto vacío, espacios, tabulaciones o saltos de línea | Rechazo cuando su contenido efectivo esté vacío. |
| P0 | Precio/superficie: cero, negativos, `NaN`, infinito o texto | `400`. |
| P0 | Dormitorios `0`; baños/personas `1` | Aceptados. |
| P0 | Dormitorios negativos; baños/personas `0`; enteros fraccionarios | `400`. |
| P0 | Compartido ausente o valor arbitrario | `400`; no aplicar «No» por defecto. |
| P0 | Precio `0.01` y `950.50` | Persistencia y lectura exactas, sin pérdida de céntimos. |
| P1 | Valores enormes, exceso de decimales, coma decimal y notación científica | Resultado conforme al contrato, sin truncamientos ni `500`. |
| P1 | Campos repetidos, alias contradictorios y campos desconocidos | Política explícita y determinista. |
| P1 | Texto con HTML/script, consultas o caracteres de control | Sin ejecución, inyección ni exposición de información interna. |

### 3.3. Fotografías

| Prioridad | Caso | Resultado esperado |
|---|---|---|
| P0 | 0, 1, 10 y 11 imágenes | Rechazo con 0/11; aceptación con 1/10 válidas. |
| P0 | Tamaño límite −1 byte, exacto y +1 byte | Aceptar los dos primeros; rechazar el tercero. |
| P0 | JPEG, PNG y WebP reales | Aceptados y recuperables. |
| P0 | Archivo vacío o truncado | `400`. |
| P0 | Texto o ejecutable con extensión y MIME de imagen | `400`. |
| P0 | Cabeceras válidas y cuerpo imposible de decodificar | `400`; detecta la carencia actual. |
| P0 | Nueve imágenes válidas y una inválida | Rechazar toda la publicación. |
| P0 | Subidas terminan en orden distinto al enviado | Se conserva el orden original. |
| P1 | Imagen comprimida pequeña con dimensiones desmesuradas | Rechazo controlado antes de agotar recursos. |
| P1 | Nombres iguales, rutas `../`, nombres muy largos | Claves generadas; sin sobrescritura ni traversal. |
| P1 | EXIF con ubicación, orientación y archivos animados | Tratamiento conforme a la política acordada. |
| P1 | Petición con varios campos de fotografías | No eludir el máximo de diez ni ignorar archivos silenciosamente. |

La validación debe controlar memoria y píxeles además del tamaño comprimido. Pillow documenta las protecciones frente a bombas de descompresión; su configuración debe acompañar a la decodificación. [Seguridad de Pillow](https://pillow.readthedocs.io/en/stable/handbook/security.html).

### 3.4. Fallos, concurrencia y recuperación

| Prioridad | Fallo provocado | Resultado esperado |
|---|---|---|
| P0 | Falla la primera, intermedia o última subida | Ningún anuncio publicado; limpieza recuperable. |
| P0 | Storage guarda, pero se pierde su confirmación | Objeto localizable y conciliado mediante el manifiesto. |
| P0 | Firestore confirma, pero se pierde su respuesta | No borrar imágenes del anuncio confirmado. |
| P0 | Caída del proceso tras cada etapa | Recuperación sin publicación parcial. |
| P0 | Falla el borrado compensatorio | Tarea persistente y reintento posterior. |
| P0 | Limpieza y publicación ejecutándose a la vez | Transiciones excluyentes; no publicar referencias borradas. |
| P0 | Respuesta perdida y reintento concurrente | Una publicación si se adopta idempotencia. |
| P0 | Serialización posterior al guardado | Respuesta serializable; ningún marcador interno en JSON. |
| P1 | Diez imágenes al máximo con conexión lenta y varias solicitudes | Límites y timeouts controlados; sin consumo ilimitado. |
| P1 | Reinicio o redespliegue | Los anuncios publicados mantienen sus imágenes. |
| P1 | Excepciones con información sensible | Respuesta genérica; sin tokens, credenciales ni trazas. |

Para certificar estas US, combinaría pruebas unitarias de validación, integración con imágenes reales y fallos de confirmación simulados, y pruebas de recuperación tras reiniciar el proceso. **Los mocks actuales del repositorio no demuestran por sí solos persistencia, rollback ni limpieza de archivos.**

## QA US 4.9 — APIs e integridad de decisiones y matches (10 noviembre 2026)

Se ejecutó desde `backend/` el comando de `emulators:exec` del README con Auth
y Firestore Emulator para `demo-swipehome-us4`: **166 tests correctos, cero
omisiones**, en 17,435 s. Los tests Firestore generan colecciones aleatorias por
caso; las solicitudes concurrentes usan barreras, hilos y clientes HTTP
independientes. No se usaron servicios ni credenciales de producción. Azure
Blob está fuera de estas transacciones y se mockea en el test de flujo completo.

Los CA oficiales sustituyen cualquier agrupación anterior:

| CA oficial | Pruebas que lo cubren en esta US | Resultado |
|---|---|---|
| CA-01 — Acceso al explorador | `test_all_three_endpoints_enforce_roles_without_persisting_changes`, `test_authentication_and_buyer_permissions_for_both_endpoints`, `test_private_notices_include_match_buyer_home_and_stable_pagination`. | **Parcial (solo API):** endpoint de exploración y permisos de decisiones verificados; acceso al inicio/ruta de explorador en la interfaz no verificado. El test integrado de roles usa verifier/perfil mockeados. |
| CA-02 — Información y fotografías | `test_explore_excludes_only_own_decisions_and_preserves_all_photos`, `test_all_public_fields_and_ordered_photos_without_internal_data`. | **Parcial (solo API):** datos públicos y orden de URLs verificados en Firestore Emulator; no se verificó tarjeta ni recorrido de fotografías en UI, ni descarga desde Azure. |
| CA-03 — Creación del match | `test_like_has_exactly_one_consistent_decision_match_and_notice`, `test_same_decision_retries_return_identical_records`. | **Pasa en API/persistencia local:** un LIKE crea la relación correcta y el retry devuelve el mismo match; gesto/botón de interfaz no verificado. |
| CA-04 — Aviso al Vendedor | `test_private_notices_include_match_buyer_home_and_stable_pagination`. | **Pasa con Firestore Emulator:** comprador y vivienda son identificables y se filtran por vendedor; presentación visual no verificada. |
| CA-05 — Descarte persistente | `test_pass_creates_only_decision_and_no_notice`, `test_explore_excludes_only_own_decisions_and_preserves_all_photos`, `test_empty_and_exact_limit_pages_have_no_next_cursor`. | **Pasa en API/persistencia local:** PASS excluye la vivienda para ese comprador; control de descarte en UI no verificado. |
| CA-06 — Independencia entre Compradores | `test_two_buyers_match_same_home_without_reserving_or_hiding_it`. | **Pasa con Firestore Emulator:** decisiones y matches separados permiten a ambos interesarse. |
| CA-07 — Continuidad y fin de la exploración | `test_pagination_ties_previous_page_decisions_and_last_page`, `test_scan_multiple_batches_of_decided_homes_without_skip_or_n_plus_one`, `test_empty_and_exact_limit_pages_have_no_next_cursor`. | **Parcial (solo API):** cursor devuelve viviendas pendientes y API expresa el fin como `items: []`, `next_cursor: null`; tarjeta siguiente y mensaje de fin en UI no verificados. |
| CA-08 — Fallos y reintentos | `test_each_staged_write_failure_rolls_back_entire_operation`, `test_rejected_commit_does_not_persist_any_staged_document`, `test_same_decision_retries_return_identical_records`, `test_simultaneous_identical_likes_converge_to_same_match_and_notice`, `test_internal_failures_are_safe_for_both_endpoints`. | **Parcial (solo backend):** errores, rollback, estado final e idempotencia pasan; aviso de fallo/carga y acción de reintento visible en UI no verificados. |

`test_all_three_endpoints_enforce_roles_without_persisting_changes` se añadió
para reforzar el control de permisos API de CA-01. No se añadieron tests de
interfaz ni cambios en el código de aplicación: las partes faltantes dependen
de la UI y quedan fuera de esta US backend. La suite medida fue de 166 tests;
esta reasignación documental no requirió repetirla.

Límites: no se probaron Firestore ni Auth de producción, no se desplegaron
índices remotos y no se probó Azure Blob real. El rollback se verifica en
Firestore Emulator con fallos inyectados, no demuestra atomicidad distribuida
con proveedores remotos. Navegación, tarjeta/carrusel, aviso de fin y reintento
visible pertenecen a la interfaz y quedan fuera de verificación de esta US.

## QA US 4.10 — recorrido completo del explorador (10 noviembre 2026)

Se corrigió BuyerHome para usar la API vigente (paginación por cursor y POST
`/api/inmuebles/{id}/decision` con `{decision}`), mantener la confirmación y
permitir retry solo tras validar la respuesta. Se añadió el test de integración
`test_published_multi_photo_listings_survive_full_buyer_flow`; la ejecución
exacta de emuladores pasó **167 tests** con Auth/Firestore Emulator y Azure Blob
mockeado. Frontend: `npm test` pasó 20 tests, lint y build terminaron
correctamente; lint conserva advertencias existentes.

La comprobación de navegador usó Auth Emulator real y respuestas API
interceptadas con fixtures; no se conectó el navegador a Firestore. Se usaron
imágenes SVG de fixture. La publicación/persistencia real descrita abajo es
del test backend con Firestore Emulator, no Firestore/Azure de producción.

| CA oficial US4 | Evidencia vinculada a US4.10 | Resultado |
|---|---|---|
| CA-01 — Acceso al explorador | Auth Emulator para la sesión Buyer; navegación BuyerHome en navegador con `/api/auth/me` interceptado. Tests de roles/sesión de US4.9 verifican permisos API y ausencia de escrituras indebidas. | **Parcial:** UI Buyer comprobada con perfil mock; permisos API pasan en tests backend, pero esta ejecución no probó la ruta UI con cada rol. |
| CA-02 — Información y fotografías | Publicación US3 por API de dos anuncios, cada uno con dos fotos en orden; GET de exploración serializa datos/fotos. Navegador fixture muestra campos, cambia foto y mantiene el contador. | **Pasa con mocks para UI:** Firestore Emulator para datos/URLs; Azure Blob mock, sin descarga real. |
| CA-03 — Creación del match | Backend LIKE devuelve match persistido para Comprador/anuncio; BuyerHome confirma LIKE desde botón y avanza. Se comprobó doble clic con 503 y retry en fixture. | **Pasa:** creación real en Firestore Emulator; interacciones y confirmación de UI con API mock. |
| CA-04 — Aviso al Vendedor | El test integrado consulta GET `/api/notificaciones` con sesión del propietario y verifica comprador/anuncio del match. | **Pasa con Firestore Emulator:** no se validó una pantalla visual de avisos US5. |
| CA-05 — Descarte persistente | PASS persiste sin match/aviso, el explorador lo excluye después de volver a iniciar sesión; BuyerHome usa flecha izquierda y muestra confirmación. | **Pasa:** persistencia/emisión API con Firestore Emulator; UI con mock. |
| CA-06 — Independencia entre Compradores | El test registra dos Compradores y permite un match distinto de cada uno con la misma vivienda. | **Pasa con Firestore Emulator.** |
| CA-07 — Continuidad y fin de la exploración | Paginación por cursor y lista vacía API; la UI avanza al siguiente elemento y representa estado sin viviendas con fixture. | **Pasa con mocks en UI** y emulador para el contrato backend. |
| CA-08 — Fallos y reintentos | Retry idempotente backend después de re-login; navegador recibe 503 y 500 mockeados, conserva tarjeta y reintenta; 401 conduce al acceso público. Test Node verifica rechazo de red en `decideProperty`. | **Parcial:** reintento/idempotencia backend y manejo de errores probados; no se provocó una pérdida física de conexión en navegador. |

También se comprobaron cambios de foto y desplazamiento vertical sin decisión,
PASS por teclado, gesto horizontal mediante eventos de puntero automatizados y
vista en viewport 1280×900/390×844 (tarjeta móvil 343 px). No se certificó
hardware móvil físico. La ruta de creación de match no depende de la existencia
de la pantalla US5; el test backend y la confirmación de BuyerHome no navegan a
ella.

## QA US 6.8 — API e integridad del perfil y la sesión (10 noviembre 2026)

Se añadieron pruebas de integración que ejecutan solicitudes HTTP contra Django
con Auth y Firestore Emulator en loopback. La suite pedida pasó **171 tests**,
sin omisiones. También pasaron los **22 tests frontend**, `npm run lint` y
`npm run build`; lint terminó con advertencias no bloqueantes en `App.jsx`,
`SellerHome.jsx`, `AuthContext.jsx`, `NotificationsPage.jsx` y `BuyerHome.jsx`.
No se modificaron dependencias ni se probaron servicios de producción.

| CA oficial US6 | Evidencia | Resultado |
|---|---|---|
| CA-01 — Consulta del perfil propio | `ProfileSessionIntegrationTests.test_buyer_and_seller_read_and_update_only_their_current_profile`; navegador muestra la cuenta Buyer tras login real en Auth Emulator y GET de perfil interceptado. | **Pasa con emuladores/mocks:** GET real para Buyer y Seller; presentación UI con API mock. |
| CA-02 — Actualización de datos | Integración PATCH con ambos roles, nombre/email normalizados, lectura posterior con token actual y re-login. Browser guarda el formulario, muestra confirmación y recarga desde fixture. | **Pasa con Auth Emulator** para persistencia del proveedor; **pasa con mocks** para recorrido UI. |
| CA-03 — Datos inválidos o email duplicado | `ProfileTests.test_identity_role_unknown_fields_empty_and_types`, `test_duplicate_maps_to_conflict`, carrera HTTP simultánea `test_concurrent_profile_email_updates_have_one_winner_without_partial_write`; browser comprueba error de nombre sin enviar y conserva entrada después de 500. | **Pasa:** 400/409; solicitudes concurrentes dan 200/409 y el perfil perdedor queda intacto. |
| CA-04 — Cambio de contraseña | `ProfileTests.test_password_validation_current_check_and_continuity`, `PasswordServiceTests.test_wrong_password_or_uid_never_changes_password`, `EmailRaceIntegrationTests.test_password_change_continuity_with_real_emulator_tokens`; browser prueba los campos y confirmación con API interceptada. | **Pasa con Auth Emulator:** la nueva contraseña autentica, la anterior se rechaza, la sesión continúa con custom token; respuesta sin contraseña ni hash. |
| CA-05 — Acceso exclusivo al perfil propio | Identidad derivada del Bearer; `test_identity_role_unknown_fields_empty_and_types` rechaza `uid`, `id` y `role`; `test_requires_authentication` comprueba acceso anónimo. | **Pasa:** no se admite selector de otra cuenta y no se cambia identidad/rol. |
| CA-06 — Persistencia y continuidad de sesión | Integración comprueba perfil tras PATCH con el mismo token y después de nuevo login; cambio de contraseña consulta `/me` con el custom token; reload de browser usa fixture actualizado. | **Pasa con Auth Emulator** para persistencia/continuidad; persistencia visible del navegador con mock. |
| CA-07 — Fallos durante la actualización | `ProfileSessionIntegrationTests.test_injected_profile_write_failure_leaves_auth_profile_unchanged` inyecta excepción antes de `auth.update_user` y verifica nombre/email finales; carrera verifica también el estado perdedor. Browser retiene los datos tras 500 y permite retry. | **Pasa:** error genérico, sin cambios parciales en el fallo inyectado; respuestas y retry visual con mock. Un resultado remoto ambiguo tras aceptación no es reversible/garantizable. |
| CA-08 — Cierre de sesión | `ProfileSessionIntegrationTests.test_logout_revokes_old_token_idempotently_without_affecting_other_account`: Firestore guarda solo `{revoked:true}`, el token anterior da 401 en `/api/auth/me`, repetir logout da 204 y la otra cuenta sigue autenticada. Browser vuelve a `/` y protege `/mi-perfil`. | **Pasa con emuladores** para revocación/API; **pasa con mocks** para navegación. |
| CA-09 — Fallos y reintentos al cerrar sesión | `LogoutTests.test_storage_failure_is_500_not_success`, tests Node de error 500/red que mantienen Firebase SDK, y browser con 500 seguido de 204. | **Pasa:** no se muestra éxito antes de confirmar; retry disponible y completa la salida. |

Adaptación explícita: la arquitectura vigente es Firebase Bearer, no sesión
Django por cookie. GET logout devuelve 405. Una solicitud que solo incluye una
cookie y ningún Bearer no crea revocación; no existe CSRF Django para este
contrato. POST logout anónimo devuelve 204 como no-op idempotente, no como
autenticación ni cambio persistido. La prueba de navegador usó Auth Emulator
real y respuestas API interceptadas; no acredita persistencia de esa sesión en
Firestore. La inyección de fallo se hace antes de la escritura; no se promete
rollback ante una respuesta remota perdida después de que Auth haya aceptado el
cambio.

## QA US 6.9 — recorrido completo de perfil y logout (10 noviembre 2026)

Se corrigió el aviso global de autenticación: un error de logout ahora ofrece
«Reintentar cierre de sesión», que vuelve a ejecutar la misma operación en lugar
de mostrar solo un botón de cerrar aviso. Auth Emulator gestionó cuentas
sintéticas Buyer/Seller. Las APIs de perfil, contraseña y logout se interceptaron
en navegador; por tanto, los resultados visuales no prueban persistencia de UI
en Firestore. Persistencia de cuenta, credenciales nuevas, revocación y
aislamiento entre cuentas cuentan con evidencia backend de US6.8: 171 tests con
Auth/Firestore Emulators.

| CA oficial US6 | Evidencia US6.9 | Resultado |
|---|---|---|
| CA-01 — Consulta del perfil propio | Buyer y Seller iniciaron sesión con Auth Emulator y abrieron `/mi-perfil`; fixture API mostró nombre/email y rol correspondientes. | **Pasa con mocks de API** (Auth de emulador). |
| CA-02 — Actualización de datos | Buyer canceló cambios; Buyer/Seller guardaron nombre con Enter y recibieron confirmación; recarga mostró el valor actualizado del fixture. | **Pasa con mocks**; persistencia backend confirmada aparte con Auth Emulator en US6.8. |
| CA-03 — Datos inválidos o email duplicado | Nombre inválido no generó PATCH; email duplicado 409 mostró el mensaje. API de US6.8 prueba validaciones y email concurrente real en Auth Emulator. | **Pasa:** UI con mocks y contrato backend con emulador. |
| CA-04 — Cambio de contraseña | Confirmación distinta mostró error sin petición; error de contraseña actual, inputs `type=password`, borrado de campos y sesión continuada tras éxito. US6.8 prueba cambio real: nueva contraseña aceptada y anterior rechazada en Auth Emulator. | **Pasa con mocks en UI** y Auth Emulator en backend. |
| CA-05 — Acceso exclusivo al perfil propio | Browser verifica que el perfil corresponde al rol autenticado; API rechaza selectores `uid/id/role` y ausencia de sesión en `ProfileTests`. | **Pasa en API con emulador; UI parcial** (sin intentar suplantar cuenta desde frontend). |
| CA-06 — Persistencia y continuidad de sesión | Cambios visibles tras recarga de fixture; actualizar contraseña no cerró la sesión visible. US6.8 verifica datos Auth tras PATCH/re-login y continuidad por custom token. | **Pasa con mocks en UI** y Auth Emulator para persistencia/backend. |
| CA-07 — Fallos durante la actualización | Error 500 de PATCH conserva entrada y permite reintentar; test backend inyecta fallo previo a `auth.update_user` y verifica nombre/email sin cambios parciales. | **Pasa con mocks en UI** y emulador para el estado final backend. |
| CA-08 — Cierre de sesión | Logout 204 regresó a `/`; volver atrás y abrir `/mi-perfil` redirigió a la página pública; Buyer pudo autenticarse de nuevo. Token viejo/revocación verificados en test backend US6.8. | **Pasa con API mockeada**; revocación real en Auth/Firestore Emulator. |
| CA-09 — Fallos y reintentos al cerrar sesión | Primer logout 500 mantuvo sesión y formulario pendiente sin enviar PATCH; aviso ofreció retry explícito. Segundo 204 limpió Auth local y navegó a `/`. | **Pasa con mocks de API y Auth Emulator.** |

El estado de carga se observó mientras el PATCH quedaba pendiente: botón
«Guardando…» deshabilitado, y un segundo click programático no generó otro
PATCH. Contraste de layout: Buyer en 390×844 y Seller en 1280×900; teclado
Enter envió formularios. Son viewports emulados en navegador de escritorio, no
certificación de dispositivos móviles físicos.

`npm test`: 22 tests pasan; `npm run lint` y `npm run build` finalizan. Lint
mantiene advertencias existentes. No se modificaron dependencias ni se probaron
servicios de producción.

## US 7.4 — recepción y consulta de notificaciones

Se corrigió la consulta para que BUYER y SELLER puedan obtener únicamente
avisos destinados a su UID verificado. La vista rechaza parámetros de identidad,
usa el contrato `items/next_cursor`, orden descendente estable, e implementa
refresco/paginación sin IDs duplicados. La pantalla muestra mensaje y fecha/hora
local, estado vacío, carga y errores diferenciados, con retry inicial y tras
fallo de actualización; una actualización fallida conserva la lista.

### Evidencia por criterio

| Criterio | Prueba/comprobación | Resultado |
|---|---|---|
| CA-01 — Acceso a avisos propios | `FirestoreDecisionTests.test_buyer_and_seller_can_read_only_their_own_notifications` consulta como BUYER/SELLER con Firestore Emulator; pantalla `/notificaciones` autenticada en navegador. | Pasa con emuladores en API; pasa con mocks de API en UI. |
| CA-02 — Mensaje, fecha y hora | `test_private_notices_include_match_buyer_home_and_stable_pagination` verifica aviso generado al propietario; fixture buyer verifica mensaje/fecha; navegador comprueba presentación de fecha y hora local. | Pasa con Firestore Emulator y mocks de UI. |
| CA-03 — Orden y actualización | Prueba de backend fija fechas iguales y valida desempate por ID/cursor; navegador prueba refresco y paginación con solapamiento. | Pasa con emuladores y mocks de API; sin duplicados. |
| CA-04 — Privacidad | Avisos fixture para tres cuentas; consulta BUYER/SELLER devuelve exclusivamente el recipient propio; `uid` y `recipient_uid` manipulados y cursor de otra cuenta se rechazan. | Pasa con Firestore Emulator y tests API. |
| CA-05 — Conservación | `FirebaseFlowTests.test_real_registration_login_publication_like_logout_and_relogin`: Auth Emulator, aviso SELLER, logout/revocación, nuevo login y reconsulta en Firestore Emulator. | Pasa con emuladores locales; no es Firebase de producción. |
| CA-06 — Vacío, fallo y retry | `NotificationApiTests` cubre vacío; navegador fuerza carga, 500 inicial y retry, 500 al actualizar conservando datos y retry exitoso. | Vacío pasa; fallos/retry pasan con mocks. |
| Interés US4 al propietario | `test_private_notices_include_match_buyer_home_and_stable_pagination` y flujo integrado de Auth/Firestore Emulator tras LIKE. | Pasa con emuladores. |
| PASS no crea aviso; consultar no altera matches | `test_pass_creates_only_decision_and_no_notice`; test de lectura compara estado de `swipes/matches` antes/después. | Pasa con Firestore Emulator. |
| Confirmación US5 crea aviso BUYER | Inspección de rutas/vistas/servicios del árbol: no existe endpoint/productor US5 de confirmación. La API puede leer una notificación BUYER ya persistida, pero no se puede generar este evento en la implementación presente. | **No verificado** (productor ausente, no se inventó ni amplió US5). |
| Sesión y responsive | Ruta protegida probada sin sesión; navegador emulado en 1280×900 y 390×844, sin desbordamiento horizontal. | Pasa con Auth Emulator/API mockeada; no probado en móvil físico. |

Validación: `npx.cmd --yes --package firebase-tools@15.34.1 firebase
emulators:exec --project demo-swipehome-us4 --only auth,firestore --config
tests/firebase.json ".venv\Scripts\python.exe -B manage.py test accounts
properties --verbosity 2"` — 172 tests; Azure Blob mockeado.
Frontend: `npm test` — 25 tests; `npm run lint` y `npm run build` finalizan.
Lint reporta advertencias no bloqueantes de proyecto. No se usaron servicios ni
credenciales reales y no se modificaron dependencias.


---

# Entrega US8 backend, soporte US8.2 y pruebas US8.5 — 15/11/2026

Este apartado registra la implementación actual; conserva el historial anterior.
No se han modificado archivos del frontend, desplegado, creado commits ni publicado cambios.
Git estaba limpio al comenzar. No se localizaron AGENTS.md aplicables en el repo
ni en sus directorios ascendentes; se consultó la carpeta real `Agents mds`, README,
contratos Firebase/US4/US5/US6, publicación US3, perfil, tests, CI, repositorio e índices.

## Implementación y archivos

- `backend/properties/preferences.py`: diez campos opcionales, validación estricta,
  canonización, huella y comparaciones exactas con campos US3.
- `backend/properties/preference_views.py`, `backend/config/urls.py`: GET/PUT/DELETE
  `/api/exploracion/filtros` y GET `/api/inmuebles/opciones-filtro`, solo BUYER.
- `backend/accounts/repository.py`: colección duradera `search_preferences/{uid}`,
  sustitución atómica mediante un set, catálogo de localidades publicadas completas,
  filtrado dentro del recorrido paginado antes de formar la página. Decisiones
  propias consultadas por lotes solo para candidatos que superan los filtros.
- `backend/properties/discovery_service.py`: lectura única de configuración por
  petición y cursores Django firmados ligados a comprador, propósito y huella canónica.
- `backend/properties/test_preferences.py` y `test_firestore_preferences.py`:
  14 métodos nuevos de prueba con múltiples subcasos, integración real Firestore.
- `backend/properties/test_discovery.py`: fixture de la nueva lectura de preferencias;
  conserva el contrato y comprobaciones US4.
- `backend/properties/test_firestore.py`: corrección de las dos expectativas,
  PENDING explícito y persistencia de preferencias tras logout/login real.
- `backend/properties/test_firestore_matches.py`: cobertura diferenciada de confirmación
  CONFIRMED, conservando el aviso INTEREST original según el código vigente.
- `backend/README.md`, `Agents mds/us8_backend.md` y contextos de proyecto,
  infraestructura, backend, pautas, US4 y US5 actualizados. Este `resultado.md`
  conserva decisiones, evidencia, comandos y límites de esta entrega.

No hay campos nuevos en anuncios, migraciones SQL, dependencias versionadas nuevas,
consultas que necesiten índices adicionales ni cambios de configuración CI.
`manage.py test accounts properties` descubre automáticamente los nuevos módulos.

## Causa comprobada de los dos fallos

`accounts.repository._write_decision` crea un match `status=PENDING` y un aviso
`type=INTEREST` con texto «Tienes un nuevo candidato interesado en tu vivienda.».
`_write_seller_decision` requiere la decisión del propietario para pasar a
CONFIRMED/REJECTED. Los dos tests de `test_firestore.py` aún esperaban el antiguo
«Tienes un nuevo match.» tras el LIKE del comprador. Se corrigieron únicamente
esas expectativas y se añadieron comprobaciones explícitas de PENDING; se mantienen
comprador/vivienda/match_id, destinatario privado y paginación estable.

El test `FirestoreMatchesTests.test_seller_confirms_candidate_and_mutuality`
verifica CONFIRMED y visibilidad mutua; ahora comprueba además que el aviso
original sigue siendo INTEREST, con mensaje, match y propietario correctos.
Evidencia relevante: el flujo actual US5 no escribe notificaciones al confirmar;
no existe productor de aviso de confirmación BUYER. No se ha creado ese productor
fuera del alcance ni falseado su cobertura; queda documentado este límite del
contrato existente. No se hicieron sustituciones globales de textos ni se
modificó el mensaje de producción para adaptar los tests.

## Decisiones técnicas y discrepancias resueltas

Firebase Auth + Firestore es la arquitectura real (`DATABASES={}`, sin middleware
de sesiones/CSRF). Se reutiliza `firebase_role`, `request.user`, comprobación de
revocación Firebase y revocaciones US6. Bearer inválido -> 401; rol -> 403;
infraestructura -> 500 seguro. US8.2 se adapta a este contrato sin autenticación
paralela ni desactivación de protecciones. Selectores de identidad se rechazan.

Mapeo: city/postal_code/bedrooms sin renombrar anuncios; min/max_price contra
price_cents, min/max_area contra surface_hundredths, min_bathrooms contra bathrooms,
people_offered contra people, is_shared contra shared_accommodation. US3 **ya**
limita surface a dos decimales (`_decimal` por defecto); se respeta esa regla.
Preferencias guardan cadenas decimales canónicas de dos posiciones y se comparan
como enteros exactos de centésimas. No hay float ni redondeo de entradas excesivas.
Los textos se recortan como US3; código postal sigue siendo cadena sin patrón
territorial impuesto. null, false y 0 mantienen significados separados.

PUT reemplaza todo, validando antes de escribir; `{}` y DELETE restablecen.
DELETE idempotente responde 200 y configuración completa con nulls; usa un solo
set atómico, sin borrar antes ni afectar decisiones/matches. GET inicial no escribe.
Un fallo antes de commit conserva la configuración; tras un commit remoto con
respuesta perdida GET permite reconciliar (no se promete rollback distribuido).

Cursores: salt de exploración + SHA256 del JSON canónico, payload con UID/fecha/ID,
misma integridad Django existente. Configuraciones equivalentes mantienen cursores
compatibles; cambios incompatibles los rechazan con 400. Restablecer equivale a
configuración vacía, no a un contador de versión; un cursor previo vacío sigue
siendo compatible. Sin cursor empieza por la primera página. Toda petición usa
una única instantánea de filtros para resultados y cursor. Fotografías/serialización
US4 se conservan. No se filtra una página ya recortada.

Se reutiliza consulta indexada de publicados US4 y se termina de filtrar por lotes
Python, según el acuerdo documentado de infraestructura. Sin matches puede ser
necesario agotar publicados; no se carga todo en memoria ni hay N+1. El catálogo
de ciudades sí recorre todos los publicados para validar integridad y formar la
lista completa, independiente de página/filtros/decisiones, única y ordenada.

## Trazabilidad US8.5

Abreviaturas: V = `PreferenceValidationTests`, A = `PreferenceApiTests`,
F = `FirestorePreferenceTests`, B = `FirebaseFlowTests`, M = `FirestoreMatchesTests`.
Los nombres completos de método están en los módulos indicados arriba.

| Criterio solicitado | Cobertura automatizada ejecutada |
|---|---|
| 1. Permisos y credenciales de todos los endpoints | A.test_permissions_every_endpoint_and_credential_failure; verificadores Auth existentes. |
| 2. Identidad verificada y selectores ajenos | A.test_identity_queries_unknown_fields_and_invalid_json; DiscoveryApiTests.test_request_user_is_overwritten_from_verified_token. |
| 3. GET inicial, PUT completo/omitidos/null/vacío, DELETE repetido | F.test_initial_replace_omitted_null_empty_and_delete_idempotence; V.test_empty_null_and_canonical_equivalence. |
| 4. Cada filtro, AND y todos juntos | V.test_individual_filters_and_all_filters_and_boundaries; F.test_filters_individually_and_together_with_exact_boundaries; F.test_and_combinations_empty_matches_and_options_independent_of_filters. |
| 5. Precio: límites, 0, aislados, iguales e inversos | V.test_decimal_limits_precision_and_ranges y pruebas individuales V/F; mínimo 0 en F.test_tied_pagination_multiple_batches_and_configuration_bound_cursors. |
| 6. Céntimos justo dentro/fuera y exceso de precisión | V.test_decimal_limits_precision_and_ranges; V/F filtros individuales con price_cents 95049/95050/95051. |
| 7. Superficie positiva, límites, aislados, iguales e inversos | V.test_decimal_limits_precision_and_ranges; V/F filtros con surface_hundredths 6549/6550/6551. |
| 8. Estudio/null/exacto, baños mínimos, personas exactas | V.test_individual_filters_and_all_filters_and_boundaries; F.test_filters_individually_and_together_with_exact_boundaries. |
| 9. Localidad/postal separados/AND/normalización/formato US3 | V.test_empty_null_and_canonical_equivalence; V/F filtros; F.test_and_combinations_empty_matches_and_options_independent_of_filters (incluye AB 01). |
| 10. true/false/null y personas independientes | V filtros; F filtros; F sustitución con nulls explícitos. |
| 11. Tipos, booleanos, JSON y no finitos | V.test_all_invalid_types_and_nonfinite_values; A.test_identity_queries_unknown_fields_and_invalid_json. |
| 12. LIKE/PASS propios y decisiones de otros | F.test_decisions_other_buyers_reset_and_isolation; regresiones US4. |
| 13. Compradores independientes y nuevo login | F.test_decisions_other_buyers_reset_and_isolation; B.test_real_registration_login_publication_like_logout_and_relogin (Auth y Firestore reales emulados). |
| 14. Reset conserva decisiones/matches y exclusiones | F.test_decisions_other_buyers_reset_and_isolation. |
| 15. Empates, múltiples lotes, sin saltos/duplicados | F.test_tied_pagination_multiple_batches_and_configuration_bound_cursors: 65 descartes, seis coincidencias y páginas de dos. |
| 16. Cursores manipulados, ajenos y configuración incompatible | Mismo test F, incluyendo equivalencia canónica y reinicio tras cambio/reset; pruebas previas de propósito/nanosegundos US4. |
| 17. Validación y fallo anterior al commit sin perder documento | F.test_validation_and_rejected_commit_preserve_entire_document: WriteBatch.commit rechazado antes de petición remota; documento real emulado intacto. |
| 18. Guardado seguido de fallo de exploración, retry | F.test_saved_preferences_survive_explore_failure_and_retry; A.test_read_write_failures_and_successful_save_then_explore_failure. |
| 19. Cero coincidencias y errores separados de 401 | F combinaciones; A permisos/fallos internos, respuesta 200 vacía con next_cursor null. |
| 20. Localidades completas, únicas, ordenadas y fuente | F.test_and_combinations_empty_matches_and_options_independent_of_filters: duplicados, borradores, incompletos y vacíos. |
| 21. Dos avisos corregidos y diferencia PENDING/CONFIRMED | Dos métodos originales de test_firestore.py y M.test_seller_confirms_candidate_and_mutuality, con límite explícito del productor de avisos US5. |

Los tests nuevos Firestore usan proyecto `demo-swipehome-us4` en loopback,
colecciones únicas y limpieza de sus documentos; mocks de fallos complementan
persistencia real local. Azure permanece simulado como en las regresiones previas.
Ningún test se eliminó ni se convirtió en omitido para ocultar fallos.

## Comandos ejecutados y resultados reales

Desde `backend`, Python 3.13 del venv; Node v24.15.0 y Java 21.0.2:

1. `.venv/Scripts/python.exe -B manage.py test properties.test_discovery properties.test_matches --verbosity 0`:
   primer intento bloqueado por `ModuleNotFoundError: azure`; tras instalar los
   requisitos **ya fijados** con `.venv/Scripts/python.exe -m pip install -r requirements.txt`,
   **26 tests OK**. No se actualizaron archivos de dependencias.
2. `.venv/Scripts/python.exe -B manage.py test properties.test_preferences properties.test_discovery properties.test_matches --verbosity 0`:
   **33 tests OK**.
3. `npx.cmd --yes --package firebase-tools@15.34.1 firebase emulators:exec --project demo-swipehome-us4 --only auth,firestore --config tests/firebase.json ".venv\Scripts\python.exe -B manage.py test properties.test_preferences properties.test_firestore_preferences properties.test_discovery properties.test_firestore properties.test_firestore_matches --verbosity 1"`:
   **66 tests OK**, sin omisiones, 62.124 s.
4. `npx.cmd --yes --package firebase-tools@15.34.1 firebase emulators:exec --project demo-swipehome-us4 --only auth,firestore --config tests/firebase.json ".venv\Scripts\python.exe -B manage.py test accounts properties --verbosity 2"`:
   primer arranque rechazado por puerto 8080 aún ocupado por Java huérfano del
   emulador demo anterior. Se comprobó su comando/proyecto y se detuvo solo ese PID.
   Reintento: **211 tests OK, sin omisiones, 44.498 s**, salida 0. Incluye las mejoras
   finales de comparación exacta y lecturas por lote, US3, US4, US5 y perfil/autenticación.
5. `.venv/Scripts/python.exe -B manage.py check`: cero incidencias.
6. `.venv/Scripts/python.exe -B manage.py makemigrations --check --dry-run`: sin cambios.
7. `.venv/Scripts/python.exe -m pip check`: sin requisitos rotos.
8. `git diff --check`: sin errores.

El repositorio no configura lint/formatter Python, por lo que no se inventó un
comando adicional ni se añadieron herramientas. La configuración CI usa Python
3.12; se ejecutó su misma suite/comando adaptando únicamente el ejecutable local
al venv Windows. No se atribuye ejecución remota de CI a estos resultados.

## Pendientes y límites

- Implementado el backend US8 y el soporte de servidor de US8.2. No se declara
  completada toda US8.2: siguen pendientes interfaz, bloqueo de envíos/swipes,
  descarte de respuestas tardías, indicación de filtros activos, acciones y mensajes.
- El contrato US8.2 documenta GET preferencias -> PUT/DELETE confirmado -> descartar
  cursor -> explorar sin cursor; un fallo posterior solo exige reintentar explorar.
- Estado vacío para UI: «No hay viviendas pendientes que coincidan con tus filtros.
  Prueba a ampliar tus criterios de búsqueda.» Acciones de frontend: «Modificar
  filtros» y «Restablecer filtros». La API conserva su sobre US4.
- Confirmación US5 no produce aviso BUYER en el código actual. Su generación no se
  declara verificada ni se añade fuera de alcance; se preserva el aviso INTEREST.
- No hay comprobaciones de producción, despliegue de índices, Azure real ni UI.
  El emulador no verifica que un índice esté desplegado en producción.
- Búsquedas restrictivas pueden recorrer todo el conjunto publicado por lotes;
  catálogo de ciudades lee publicaciones completas. No hay motor de búsqueda nuevo.


### Verificación final posterior a la revisión de representación decimal

Se cerró un caso extremo: una entrada decimal larga cuya forma canónica con
`.00` excediera 100 caracteres ya no puede guardarse y fallar después al leerse.
Se comprueba ida y vuelta de una configuración de gran magnitud y rechazo del
límite excedido en `test_empty_null_and_canonical_equivalence`.

- `.venv/Scripts/python.exe -B manage.py test properties.test_preferences --verbosity 0`:
  **7 tests OK**, 0.046 s.
- Repetición del mismo comando completo con Auth y Firestore Emulator y
  `manage.py test accounts properties --verbosity 2`: **211 tests OK, sin omisiones,
  67.937 s**, salida 0. Este es el resultado del código final.
- Revisión de UTF-8, sintaxis Python de los cuatro módulos nuevos y existencia de
  las referencias locales principales US8: correcta.
- `git diff --check` y `manage.py check` finales: correctos.

El cierre de Firebase CLI en Windows dejó procesos Java residuales escuchando en
8080; se identificaron por comando exacto del emulador/proyecto demo y se cerraron
sin tocar procesos ajenos. No se usaron servicios de producción.


---

# Revisión técnica de US10.4–US10.6 — 23 de noviembre de 2026

## Veredicto

| Alcance | Veredicto | Condición pendiente |
|---|---|---|
| US10 | **Parcial** | La gestión básica está implementada. Faltan garantías de concurrencia en el contrato público y recuperación de fotografías. |
| US10.4 — Consulta y edición | **Parcial** | Funcionan consulta privada y edición canónica. Una escritura sin versión puede solapar cambios y la compensación puede invalidar una edición confirmada. |
| US10.5 — Disponibilidad | **Parcial** | Pausa, reactivación y retirada existen y se integran con exploración y avisos. Hay incompatibilidades en la transición ACTIVE → reactivar y en el tratamiento de reintentos. |
| US10.6 — Integridad | **Parcial** | Firestore coordina los cambios protegidos y la selección definitiva. Sigue abierta la recuperación Firestore–Azure y existe una ruta de disponibilidad sin precondición. |

## Contexto y contrato comprobados

- HEAD `f2dd79c`. El estado inicial solo mostraba `firebase_api.json` sin seguimiento. Se preservó y no se leyó su contenido. La búsqueda de `AGENTS.md` en el repositorio y la comprobación de sus directorios candidatos superiores no localizaron instrucciones aplicables. Documentación consultada en `Agents mds`: `skills.md`, `project_context.md` (US3), `backend_context.md`, `infra_context.md`, `firebase_auth_migration.md`, y contratos de US4, US5, US8, US9 y US10. El README del backend documenta publicación, pruebas, US7.4 y selección definitiva.
- Django sirve la API HTTP con `DATABASES = {}` (`backend/config/settings.py:56`). Firebase Auth verifica el Bearer y las revocaciones. El decorador construye `request.user` con UID verificado y rol del perfil Firestore (`backend/accounts/authentication.py:26–60,101–134`). Firestore Admin SDK persiste usuarios, anuncios, decisiones, matches, avisos, propuestas y controles. Azure Blob almacena las fotos y Firestore guarda sus URLs ordenadas (`backend/accounts/repository.py:83–149,1342–1401`, `backend/accounts/azure_storage.py:47–92`). La inicialización Firebase del cliente usa Auth (`frontend/src/firebase.js:2`). La búsqueda en `frontend/src` no encontró SDK de Firestore/Storage. Se localizó una regla deny-all versionada para las pruebas (`backend/tests/firestore.rules:1–6`), no una verificación de reglas desplegadas. Admin SDK y el cliente Azure dependen de la validación del servidor. Las URLs de fotos se entregan como referencias de lectura y las escrituras pasan por el backend. La política efectiva del contenedor Azure queda fuera de la evidencia local.
- Las seis rutas propuestas coinciden con `backend/config/urls.py:48–53` (bloque final) y `Agents mds/us10_backend.md:12–26`. GET listado devuelve `items` y alias `properties`. Detalle devuelve fotos, acciones y versión. PATCH admite JSON con campos y URLs retenidas, o multipart con altas de archivos y `existing_photos`/`retained_photos`. Las retenidas van primero en el orden indicado y las nuevas después en orden de carga. PATCH devuelve 200, representación del anuncio, versión, disponibilidad, motivo y fecha. Los POST devuelven ID, disponibilidad, versión y motivo en retirada. La confirmación visual de retirada pertenece al frontend. El contrato backend no define un campo de confirmación.
- `version` se recibe en el cuerpo JSON o multipart de PATCH y en JSON en los POST. El documento US10 la describe como opcional, aunque el criterio de esta revisión exige que las escrituras incluyan versión. Con una versión suministrada y una escritura efectiva, se compara dentro de la transacción. Los POST comprueban antes el estado objetivo y pueden devolver 200 sin validar vigencia de esa versión. US9 mantiene además PUT `/api/inmuebles/{id}/disponibilidad`, con ACTIVE/PAUSED sin versión de entrada o salida (`backend/properties/proposal_views.py:115–126`). El PATCH anterior de US9 comparte la ruta y queda servido por la vista US10.
- **Selección definitiva es US9** (`Agents mds/us9_backend.md:1`, `backend/README.md:791` en el bloque US9). Está implementada y usa `listing_selections` como control transaccional, propuestas privadas y aceptaciones por BUYER. La aceptación persiste CLOSED/RENTED. Dar de alta una propuesta admite viviendas activas y pausadas. US5 admite gestionar candidaturas de un anuncio pausado y el código bloquea decisiones nuevas del vendedor sobre candidatos pendientes si el inmueble está CLOSED (`backend/accounts/repository.py:641–702`). La pausa no introduce un bloqueo general. US4 usa ambos POST de decisión sobre el mismo repositorio, US8 aplica preferencias antes de excluir LIKE/PASS y US7 lee avisos privados por destinatario.

## Defectos por impacto

1. **Alta — F1 — US10.4.6/13, US10.5.1–4, US10.6.3/4. Escrituras sin precondición y PATCH basado en una lectura previa.** `backend/properties/management_views.py:42–59,95–155,221–254`, `backend/accounts/repository.py:1102–1117,1266–1267,1291–1292,1318–1319,1373–1401`. Esperado: dos cambios basados en los mismos datos no se pisan. Observado en código: la versión omitida desactiva la comparación y PATCH escribe también los campos omitidos, reconstruidos antes de la transacción. Dos PATCH parciales sin versión que lean v1 pueden revertir mutuamente título y precio. El PUT legado también puede cambiar disponibilidad a partir de una vista antigua, incluso cuando otro cliente utiliza las rutas versionadas. Corrección mínima: acordar la evolución de ambos contratos, exigir una precondición válida para mutaciones y aplicar solo campos enviados o construir el parcial a partir del snapshot transaccional.
2. **Alta — F2 — US10.4.13, US10.6.7/10. Compensación destructiva con commit incierto.** `backend/accounts/repository.py:1342–1364,1403–1412`. Escenario: Firestore confirma referencias nuevas y la respuesta del commit se pierde. Esperado: las fotos referenciadas siguen utilizables mientras se reconcilia el resultado. Observado en código: cualquier excepción de la transacción ejecuta borrado de blobs recién subidos, sin comprobar si el commit se materializó. El anuncio puede quedar apuntando a archivos borrados. La publicación US3 ya distingue confirmación incierta en `repository.py:131–149`. Corrección mínima: reconciliar con una identidad de operación y referencias persistentes antes de compensar. Con resultado desconocido, conservar y registrar trabajo recuperable.
3. **Alta — F3 — US10.4.13, US10.6.7/10. Limpieza sin recuperación ejecutable.** `backend/accounts/repository.py:249–301,1346–1364,1403–1412`. Si el proceso termina tras subir un archivo o después del commit y antes del borrado, no queda trabajo registrado. Ante fallo de borrado, `photo_cleanup` se escribe después y también puede fallar. La búsqueda de `photo_cleanup` y sus productores no encontró consumidor. Si falla la construcción del cliente siguiente a las subidas o la obtención de un blob después de subir otro, esos fallos quedan fuera del bloque que compensa. Esperado: un reinicio permite limpiar huérfanos y retiradas sin borrar objetos referenciados. Corrección mínima: preparar registro durable antes de subir, registrar las retiradas en la misma transacción que cambia referencias y consumir ambos trabajos con reconciliación, reintentos e idempotencia.
4. **Media — F4 — US10.4.4, US10.5.5/7/8. El estado actual se usa como identidad del reintento.** `backend/accounts/repository.py:1253–1320`. Esperado: reactivar un ACTIVE sin reactivación previa es incompatible y el reenvío genuino de una reactivación completada recupera su resultado. Observado en código: incluso un ACTIVE inicial v1 devuelve 200 para reactivar v1. Pausar con cualquier versión sobre PAUSED y retirar con cualquier versión sobre WITHDRAWN devuelven 200. Ejemplo: pausa v1 → reactiva v2 → pausa v3. Una nueva llegada de la primera solicitud v1 devuelve el PAUSED v4 como si correspondiera a aquella acción. Si el estado objetivo difiere, una petición antigua con versión entra en conflicto. Con propuesta pendiente, los casos sin escritura devuelven 200 antes de comprobar el control, aunque las acciones anunciadas estén vacías. La prohibición de cambios efectivos sí se aplica. El documento US10 describe idempotencia por estado para algunos casos y no fija cómo reconocer la misma operación ni la prioridad de un no-op frente a una propuesta pendiente. Corrección mínima: concretar esas reglas y vincular el reintento a la operación confirmada mediante una identidad persistida o un contrato equivalente.
5. **Media — F5 — US10.4.6/12, US10.6.3. Entradas inválidas inconsistentes.** `backend/properties/management_views.py:42–59,122–130,157–209`. Esperado: versión positiva estricta y cuerpo válido, con 400 para datos inválidos. Observado en código: JSON `true` pasa como 1, `"0"` pasa el filtro de la cadena, el POST acepta null y omite la versión para un cuerpo no JSON. Una cadena Unicode como `"²"` cumple `isdigit()` pero falla en `int()` y cae en el 500 genérico. Un multipart sin boundary puede disparar `MultiPartParserError` y acabar en 500. JSON rellena el canónico antes de validar sus aliases US3 y un alias nuevo puede entrar en conflicto con el valor anterior. Multipart filtra aliases antes de validar y puede devolver éxito sin aplicarlos. Los nombres canónicos documentados sí funcionan. Corrección mínima: validar versión con una única función, mapear errores de parseo a 400 y acordar el tratamiento uniforme de aliases.
6. **Media — F6 — US10.4.9/10, US10.6.7/10. Validación de referencias antiguas y borrado por URL.** `backend/accounts/repository.py:261–274,1377–1391`. La pertenencia de una URL enviada se verifica contra el anuncio actual y rechaza referencias ajenas que no estaban en ese documento. Sin embargo, para datos previos basta una lista no vacía, incluso con una cadena vacía almacenada. Al quitar una referencia preexistente, el borrado deduce el nombre por fragmento de path o por los últimos segmentos aunque su host no sea el del contenedor. Una referencia histórica externa con el mismo sufijo puede provocar el intento de borrado de otro blob. No se constató que existan referencias cruzadas reales. Esperado: conservar una referencia utilizable y borrar solo blobs verificados del anuncio. Corrección mínima: validar referencias almacenadas y vincular el borrado a un identificador de blob del contenedor con propiedad comprobada.
7. **Baja — F7 — US10.4.11/12. La respuesta puede reflejar otra escritura.** `backend/accounts/repository.py:1393–1412`, `backend/properties/management_views.py:248–265`. La nueva versión se escribe en la transacción, pero la respuesta relee el anuncio después de la limpieza. Si otra operación confirma primero, puede devolver el contenido y versión posteriores. Si falla esa lectura, devuelve 500 pese a que la edición quedó confirmada. Esperado: resultado identificable de la edición confirmada. Corrección mínima: asociar la respuesta al resultado de esa operación.

## Trazabilidad por criterio

Las referencias abreviadas R, V, M y P corresponden a `backend/accounts/repository.py`, `backend/properties/management_views.py`, `backend/properties/test_management.py` y `backend/properties/test_proposals.py`. Las observaciones de las matrices combinan inspección estática y los casos de la suite indicados. Los mocks de Azure verifican llamadas y referencias, y las transacciones de la suite emulada verifican persistencia cuando ese caso existe.

### US10.4

| Nº | Estado | Evidencia y límite |
|---|---|---|
| 1 | CUMPLE | V:64–305, seis decoradores SELLER. M:53 verifica 401/403 en las seis rutas. La verificación inválida y revocada se prueba también en autenticación compartida. |
| 2 | CUMPLE | V:67–305 usa UID del servidor. R:921–927 comprueba propietario. M:86 comprueba intentos de cambio. |
| 3 | CUMPLE | R:1167–1239 filtra `published` y dueño e incluye disponibilidad, motivo y acciones. M:204 cubre aislamiento. |
| 4 | PARCIAL | R:1174–1187,1253–1320,1370–1375. M:395 cubre bloqueo de edición, pausa y retirada. No-ops anteriores al bloqueo, F4. |
| 5 | CUMPLE | R:1192–1218,1242–1250. M:204 y 239. El array conserva su orden. |
| 6 | PARCIAL | V:136–246 reutiliza `validate_property`; M:239 verifica edición parcial canónica. F1 y F5. No hay prueba exhaustiva de todos los campos y formatos. |
| 7 | CUMPLE | V:112–130,169–186 y `validation.py:10–26,81–107`. Identidad se valida o descarta, y los internos no pasan al conjunto editable. M:86. La versión del cuerpo solo es precondición. |
| 8 | CUMPLE | R:1367–1401 lee propiedad, control y estado en la misma transacción. M:395 verifica el bloqueo secuencial. Carrera específica US10 sin prueba dedicada. |
| 9 | PARCIAL | R:1377–1384, M:271–281 rechaza URL ajena. El borrado de referencias históricas carece de la validación referida en F6. |
| 10 | PARCIAL | R:1377–1401 guarda orden y rechaza la lista vacía. M:103,239,433. La comprobación de referencias previas es insuficiente para datos históricos dañados, F6. |
| 11 | PARCIAL | V:248–265 y M:239 comprueban 200, datos y v2. La relectura concurrente puede devolver otra versión, F7. |
| 12 | PARCIAL | V:23–38 y autenticación común. M:53–149 cubre códigos habituales. F5 produce casos inválidos fuera de contrato. Con payload válido, la propiedad ajena se verifica con 404. La validación de body puede devolver 400 antes de esa comprobación. |
| 13 | PARCIAL | M:281–291 verifica 409 obsoleto enviado expresamente. R:1373–1375 evita sobrescritura bajo esa precondición. F1–F3 dejan vías sin protección o efectos en archivos. |

### US10.5

| Nº | Estado | Evidencia y límite |
|---|---|---|
| 1 | CUMPLE | V:266–305, R:921–927,1253–1308. M:53 comprueba sesión/rol, M:73 mapea 404 y la propiedad de cada mutación usa el mismo control transaccional. |
| 2 | CUMPLE | R:1253–1275, M:293 confirma ACTIVE → PAUSED. |
| 3 | CUMPLE | R:1278–1300, M:293 confirma PAUSED → ACTIVE. |
| 4 | CUMPLE | R:1303–1332 permite ACTIVE y PAUSED sin propuesta y escribe CLOSED/WITHDRAWN. M:336 ejecuta retirada desde ACTIVE. |
| 5 | PARCIAL | R:1264,1289,1316 protege cambios efectivos. M:395 verifica pausa y retirada. Prioridad del no-op no definida, F4. |
| 6 | CUMPLE | R:1262,1287,1312–1315 bloquea reapertura/retirada sobre RENTED. P:96 ejecuta cierre por aceptación, M:336 comprueba cierre manual irreversible. RETIRAR sobre RENTED inspeccionado estáticamente. |
| 7 | PARCIAL | M:293,336 verifica reenvíos y avisos sin duplicar. R:1260,1285,1312–1315 confunde coincidencia de estado con identidad, F4. |
| 8 | NO CUMPLE | R:1285 devuelve 200 al reactivar un ACTIVE inicial. Los conflictos sobre CLOSED sí aparecen en M:336. |
| 9 | CUMPLE | R:544–587 combina publicación íntegra, ACTIVE, filtros y decisiones. M:293 y `test_firestore_preferences.py` prueban piezas. La combinación filtros + decisiones + ciclo de reactivación no tiene caso dedicado identificado. |
| 10 | CUMPLE | R:467–520 lee disponibilidad dentro de la transacción. M:308–318 prueba swipe bloqueado. Ambos endpoints de decisión usan `record_decision`. |
| 11 | CUMPLE | R:511–520 bloquea nuevas decisiones en PAUSED/CLOSED. Los reenvíos previos no crean intereses nuevos. P:185 prueba carrera de interés con cierre US9, no con retirada manual. |
| 12 | CUMPLE | R:1280–1299 solo actualiza estado, fecha y versión. R:579–587 sigue excluyendo el swipe previo. No se identificó test integral del ciclo con LIKE y PASS previos. |
| 13 | CUMPLE | R:1320–1336 congela pendientes/confirmados, escribe avisos US7 o eventos duraderos. M:336 verifica destinatarios y mensaje. |
| 14 | CUMPLE | R:941–955,1121–1163,1312–1336 usa conjunto, claves y entrega transaccional. M:336 repite retirada. P:282 prueba recuperación por lotes en US9 con el procesador compartido. Falta prueba específica con fallo y retirada por lotes. |
| 15 | CUMPLE | R:1324–1332 no borra documentos. M:389–393 conserva swipes y matches. Fotos intactas por inspección del conjunto de escritura. |

### US10.6

| Nº | Estado | Evidencia y límite |
|---|---|---|
| 1 | CUMPLE | R:83–106,1050–1056,1268–1330,1394–1401, timestamps del servidor y versión creciente. P:96 y M:239,293,336. Datos históricos pueden derivar campos al leer. |
| 2 | CUMPLE | R:900–910,1209,1218 conserva estado explícito y deriva ACTIVE de `published` cuando falta. P:96 y fixtures M cubren convivencia básica. No se inspeccionaron datos remotos. |
| 3 | PARCIAL | R:1373–1401,1266–1329 compara dentro de transacción cuando se aporta versión. R:1102–1117 y omisión documentada eluden la comparación, F1. |
| 4 | PARCIAL | Con dos escrituras efectivas que aporten la misma versión, la lectura transaccional del mismo documento protege contra sobrescritura. No hay prueba simultánea US10 específica. Omisión y efectos externos F1–F3. |
| 5 | CUMPLE | R:958–997,1025–1062,1255–1329,1367–1401 comparten lecturas de anuncio/control y escrituras conflictivas. M:395 prueba el bloqueo; P:175/185 prueba carreras de selección adyacentes. No se ejecutó una carrera dedicada de alta de propuesta contra cada mutación US10. |
| 6 | CUMPLE | R:1050–1056,1174–1187,1222–1250. P:96 comprueba aceptación, M:204 comprueba consulta y acciones. Visibilidad del RENTED para su dueño sustentada por el serializador y `published` conservado. |
| 7 | NO CUMPLE | R:1403–1412 y F2/F3. El rechazo confirmado antes del commit conserva las referencias anteriores, pero el resultado incierto puede romper las referencias que quedaron confirmadas. No hay evidencia real Azure para ese fallo. |
| 8 | CUMPLE | V:209–215 y `backend/properties/validation.py:110–159` reutilizan US3. M:433 cubre subida válida con Azure simulado y la suite US3 cubre validación de bytes, tamaño y formatos. |
| 9 | CUMPLE | R:1403–1410 borra retiradas después de recibir confirmación. La limpieza de nuevas fotos en commit incierto es el defecto F2. |
| 10 | NO CUMPLE | R:249–301,1342–1412. Compensación inmediata parcial y cola sin consumidor ni registro previo a las ventanas de caída. F2, F3 y F6. |
| 11 | CUMPLE | R:1269–1332. M:293,336 y P:96. El conjunto de escrituras no elimina fotos ni relaciones. |
| 12 | CUMPLE | R:900–910,1209,1218. Compatibilidad en lectura y evolución aditiva sin migración destructiva ni backfill repetible. Garantía estática para documentos ajustados al esquema anterior. |

### Criterios de la historia principal

| Criterio | Estado | Relación y evidencia |
|---|---|---|
| CA-01 | CUMPLE | US10.4.1–5. M:204, filtro por propietario y disponibilidad. |
| CA-02 | PARCIAL | US10.4.6–8/11/13. M:239, persistencia canónica. F1, F5 y F7. |
| CA-03 | PARCIAL | US10.4.9–10, US10.6.8–10. Retenidas ordenadas, altas al final, pertenencia y mínimo estructural. F2, F3 y F6. |
| CA-04 | PARCIAL | US10.5.2–3/7–12. Exploración y decisiones preservadas. F4 y falta de caso integral con preferencias durante el ciclo. |
| CA-05 | CUMPLE | US10.5.4/6/10–11/13–15. M:336 comprueba resultado, avisos e historial. Carrera de retirada sustentada por lectura transaccional común. |
| CA-06 | PARCIAL | US10.4.8, US10.5.5, US10.6.5–6. Cierre RENTED y cambios efectivos bloqueados. F4 para respuestas sin cambio con propuesta pendiente. |
| CA-07 | CUMPLE | US10.4.1–2/7, US10.5.1. Auth común y propiedad validada por recurso. |
| CA-08 | PARCIAL | US10.4.6/12–13, US10.6.3–4. 409 con versión explícita, F1 y F5. |
| CA-09 | NO CUMPLE | US10.6.7–12. Persistencia Firestore demostrable, recuperación de archivos incumplida en F2/F3. |

## Pruebas ejecutadas y límites

- `.\.venv\Scripts\python.exe -B -m pip check` → sin requisitos rotos.
- `.\.venv\Scripts\python.exe -B manage.py check` → 0 incidencias.
- `.\.venv\Scripts\python.exe -B manage.py makemigrations --check --dry-run` → sin cambios detectados.
- `git diff --check` → sin errores antes de añadir el informe.
- `.\.venv\Scripts\python.exe -B manage.py test accounts properties --verbosity 1`, retirando las dos variables de host de emulador en el proceso → 249 descubiertas, 177 correctas, 72 omitidas, código 0.
- `npx.cmd --offline --yes --package firebase-tools@15.34.1 firebase emulators:exec --project demo-swipehome-us4 --only auth,firestore --config tests/firebase.json ".venv\Scripts\python.exe -B manage.py test accounts properties --verbosity 1"` → 249 correctas, 0 omitidas, 92,792 s, código 0. Java 21.0.2 y Node 24.15.0. Proyecto demo, loopback, sin cambios en servicios reales.

- `@' … '@ | .\.venv\Scripts\python.exe -B manage.py shell --no-imports` → primer intento de comprobación aislada. La consola interpretó mal dos bloques multilinea aunque salió con código 0. El bloque de reactivación sí se ejecutó con dobles y devolvió ACTIVE v1 para una vivienda inicialmente activa y ACTIVE v4 con propuesta pendiente y petición v1.
- `@' … '@ | .\.venv\Scripts\python.exe -B -` → rerun no interactivo por stdin, sin archivos de prueba ni servicios externos. Con `django.setup()`, `RequestFactory` y `guarded(_extract_version_from_body)`, los JSON `{}`, `{"version":true}`, `{"version":"0"}` y `{"version":"\\u00b2"}` produjeron, respectivamente, `None`, `True`, `0` y HTTP 500. Con `unittest.mock.patch` sobre cliente Azure, referencias y runner transaccional, el runner invocó el callback de `update_listing_full` y lanzó `TimeoutError` al simular pérdida de confirmación. Se observó la nueva URL en los argumentos de `tx.update` y una llamada a `delete_blob()`. Esto verifica la rama de compensación del código, sin afirmar que se haya provocado una pérdida de confirmación en Firestore real.

La suite contiene 10 casos directos de gestión y 17 de selección definitiva. Comprueba además Auth, US3, US4, US5, US7 y US8. Los logs de errores simulados son parte de varios casos de fallo. La prueba M:433, pese a su nombre, comprueba la subida simulada, URL y versión, sin demostrar borrado recuperable. Las pruebas US9 de rollback de avisos, lotes y carreras son evidencia directa del mecanismo compartido y de los escenarios que ejecutan. Un mock de Azure no demuestra que un objeto exista, se pueda leer o se recupere después de perder la respuesta de un commit.

## Riesgos y correcciones priorizadas

1. **P1:** cerrar la precondición de versión en PATCH, acciones y PUT legado. Verificar con Firestore Emulator ediciones simultáneas, edición contra pausa y propuesta contra cada mutación. Verificar también aceptación contra operaciones incompatibles.
2. **P1:** persistir preparación, confirmación y limpieza de fotografías con reconciliación. Probar fallo de cada subida, rechazo y confirmación incierta de Firestore, caída entre commit y borrado y reinicio del consumidor, usando Azure aislado o un emulador de Blob y dobles controlados para pérdida de respuesta.
3. **P2:** concretar la semántica de reintentos y propuesta pendiente, diferenciar transición incompatible, reenvío genuino y solicitud antigua tras transiciones intermedias. Normalizar errores de versión, parseo y aliases.
4. **P2:** validar el origen de referencias antiguas y ligar respuesta/versiones a la operación confirmada. Probar fotos ajenas, la última válida y orden en ambos formatos admitidos.
5. **Verificación de integración:** probar retirada manual contra nuevo interés, aviso por lotes con destinatarios solapados y fallo/reanudación, y reactivación conservando filtros y LIKE/PASS. Existe comando `manage.py process_selection_notifications --limit 100` para recuperación de avisos, documentado en US9. No se verificó su programación operativa ni el despliegue efectivo de índices, reglas o configuración Azure. Son comprobaciones externas pendientes, no evidencia de un defecto en la entrega transaccional local.

**Recomendación opcional.** El listado filtra propietarios en Django después de recorrer la colección entera (R:1222–1229). Llevar ese filtro a Firestore reduciría lecturas y coste conforme crezca el número de publicaciones. La respuesta actual se limita al propietario y el filtrado en servidor no constituye por sí mismo una exposición de otros anuncios.

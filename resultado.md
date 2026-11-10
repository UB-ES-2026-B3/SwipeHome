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

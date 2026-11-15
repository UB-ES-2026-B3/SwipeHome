# US8: preferencias de búsqueda, soporte de US8.2 y pruebas US8.5

Implementación backend, 15 de noviembre de 2026. Firebase Auth verificado +
Firestore, sin ORM ni sesiones por cookies. Referencias: [US4](us4_backend.md),
[US5](us5_backend.md), [US6](us6_backend.md) y [README backend](../backend/README.md).
Los criterios de interfaz de US8.2 siguen pendientes; este trabajo no los implementa.

## Contrato HTTP y autorización

Todas las rutas requieren `Authorization: Bearer <ID token Firebase>` y rol BUYER.
`firebase_role` verifica Auth con `check_revoked=True`, revocaciones persistidas
por US6 y perfil vigente; construye `request.user`. Nunca se selecciona una
cuenta desde el cuerpo o parámetros. Cookies solas no autentican. CSRF de
sesiones Django no aplica a este contrato; no se añade `csrf_exempt` ni un
mecanismo de autenticación paralelo.

| Método y ruta | Respuesta correcta |
|---|---|
| GET `/api/exploracion/filtros` | 200, objeto canónico completo de preferencias propias. Sin documento: todos los campos null. No escribe. |
| PUT `/api/exploracion/filtros` | `application/json`, 200 con objeto canónico confirmado. Sustituye completamente: omitido equivale a null; `{}` restablece. |
| DELETE `/api/exploracion/filtros` | 200 con objeto completo de nulls. Idempotente incluso sin documento. |
| GET `/api/inmuebles/opciones-filtro` | 200, `{"cities":["Barcelona","Madrid"]}`. |
| GET `/api/inmuebles/explorar?limit=20&cursor=...` | 200, contrato US4 `{"items":[...],"next_cursor":null}`. |

Preferencias y opciones rechazan cualquier query; explorar solo admite los
parámetros US4 `limit/cursor` (20 por defecto, máximo 50). Los campos desconocidos
del PUT, incluidos selectores de cuenta y rol, producen errores por campo.

Errores: 400 `{"errors":{"max_price":"..."}}` para validación PUT (clave `body`
para objeto/JSON/content-type inválidos); 400 `{"error":"..."}` para parámetros
y cursores inválidos, igual que US4. 401 con `WWW-Authenticate: Bearer` para
credenciales ausentes/inválidas/caducadas/revocadas; 403 para rol distinto de
BUYER o perfil ausente; 405 para método no admitido; 500 `{"error":"..."}` seguro
ante fallos de infraestructura. Un fallo de red, Firestore o verificación no se
convierte en 401. Respuestas sin caché (`never_cache`).

Ejemplo PUT (los omitidos quedan null):

```http
PUT /api/exploracion/filtros
Authorization: Bearer <ID token>
Content-Type: application/json

{"city":" Barcelona ","min_price":"0","max_price":"950.50","bedrooms":0,"is_shared":false}
```

Respuesta 200:

```json
{"city":"Barcelona","postal_code":null,"min_price":"0.00","max_price":"950.50","min_area":null,"max_area":null,"bedrooms":0,"min_bathrooms":null,"people_offered":null,"is_shared":false}
```

GET inicial, PUT `{}` y DELETE devuelven las mismas diez claves con valores null.
PUT inválido no escribe ninguno de los campos, aunque otros fueran válidos.

## Campos y mapeo exacto a US3

Todos opcionales, combinados con AND y comprobaciones explícitas de null.

| Preferencia | Campo existente del anuncio | Regla |
|---|---|---|
| city | city | Cadena exacta tras `strip()`, conserva mayúsculas y acentos, como US3. |
| postal_code | postal_code | Cadena exacta tras `strip()`, sin patrón territorial nuevo; conserva ceros, letras y espacios interiores. |
| min_price / max_price | price, persistido como price_cents | Euros en cadena decimal, mínimo >= 0, máximo > 0, hasta dos decimales. |
| min_area / max_area | surface, persistido como surface_hundredths | m² > 0, hasta dos decimales conforme a la regla **ya existente** de US3. |
| bedrooms | bedrooms | Entero exacto >= 0; 0 es estudio. |
| min_bathrooms | bathrooms | Entero mínimo >= 1. |
| people_offered | people | Entero exacto >= 1; personas a las que se ofrece el alquiler. |
| is_shared | shared_accommodation | Booleano exacto; false restringe, null no restringe. |

`properties.validation.validate_property` llama `_decimal` con su valor por
defecto `max_decimal_places=2` tanto para `price` como para `surface`;
`create_listing`/`listing_item` utilizan centésimas. La precisión de superficie
se toma de esa evidencia, no se deduce de la del precio. No se duplican ni se
renombran los campos persistidos de los anuncios.

Los textos vacíos o solo espacios se convierten en null. Los decimales vacíos,
booleanos, números JSON, arrays, objetos, NaN/Infinity, exponentes y signos
negativos no son cadenas decimales admitidas. Se admite `+` inicial y espacios
exteriores; máximo 100 caracteres tanto de entrada decimal como de representación canónica. Los enteros no aceptan
booleanos ni cadenas numéricas y respetan el rango de entero Firestore de 64 bits.
No se deducen personas de dormitorios ni de alojamiento compartido.

La configuración canónica persiste decimales como cadenas con dos decimales
(por ejemplo `"65.5"` -> `"65.50"`) y nulls explícitos. Se validan con Decimal,
sin float binario; las comparaciones transforman la cadena canónica en enteros
exactos de centésimas. Más de dos decimales se rechazan **sin redondeo**.
Los límites son inclusivos, pueden estar aislados o ser iguales; mínimo > máximo
produce error del campo máximo. No se exige que un filtro tenga coincidencias.

## Persistencia, atomicidad y restablecimiento

`accounts.repository` conserva el único acceso nuevo a Firestore:
`search_preferences/{uid verificado}`. Una lectura recupera las preferencias;
un único `DocumentReference.set` sin merge sustituye atómicamente el documento.
No hay borrado previo ni escritura campo a campo. DELETE escribe la configuración
sin restricciones en ese mismo documento y devuelve la confirmación canónica.
Persistencia independiente del token, logout, navegador y proceso Django.

Un fallo antes del commit deja íntegro el documento anterior. La API no responde
éxito ante fallo. Si se pierde la respuesta tras un commit remoto aceptado, el
resultado puede ser incierto: GET permite reconciliar y PUT/DELETE se pueden
repetir. No se promete revertir un commit ya aceptado. No se tocan decisiones,
matches, notificaciones, perfiles ni anuncios al guardar/restablecer/consultar.

## Exploración y cursores

Una petición lee **una vez** la configuración y usa esa misma instantánea para
filtrar y firmar el cursor. Mantiene `published_listing` de US3/US4 (completa,
publicada, fotos válidas), orden `created_at DESC, __name__ DESC` y serialización
`listing_item`, incluidas todas las fotos en su orden. Consulta lotes acotados,
filtra antes de formar la página y sigue hasta `limit+1` coincidencias o agotar
candidatos. Las decisiones propias se cargan con `get_all` por lote de viviendas
elegibles; no se leen decisiones de las descartadas por filtros ni hay N+1.
LIKE y PASS propios excluyen; los de otros compradores no excluyen.

El cursor público apunta al último resultado entregado, nunca al último
candidato descartado o al resultado adicional. Reutiliza `accounts.pagination`
y la firma Django: salt de propósito `properties.explore.v1` más SHA256 del
JSON canónico ordenado; payload con UID y fecha/ID. Se vincula así a propósito,
comprador y configuración íntegra, sin aceptar una huella enviada por el cliente.
Manipulación, otro comprador o configuración incompatible -> 400 de parámetros
US4. Los cursores antiguos anteriores a US8 también se invalidan.

Omitidos, null y textos vacíos equivalen; decimales `0`/`0.00` equivalen, pero
false y 0 conservan su significado distinto de null. Repetir PUT equivalente
mantiene compatibles los cursores. Restablecer produce la huella de la
configuración vacía: invalida los de configuraciones restrictivas; un cursor
previo de una configuración idéntica vacía sigue siendo compatible. Sin cursor,
cambiar/restablecer siempre empieza por la primera página del orden vigente.
No se introduce una versión ni un campo de respuesta adicional innecesarios.

No hay índices nuevos: se reutiliza `published + created_at + __name__` de US4.
Se termina de filtrar en Python por lotes conforme al acuerdo de infraestructura,
sin cargar todo el catálogo en memoria ni multiplicar índices por combinación.
Una búsqueda muy restrictiva o vacía puede necesitar recorrer todos los publicados
hasta agotar candidatos; es el límite del diseño actual. El emulador no certifica
la existencia o el despliegue del índice en producción. No se ha desplegado nada.

## Fuente de localidades

La fuente es `listings` con `published=True` y validación `published_listing`
completa US3/US4. Se recorre esa fuente completa para formar el catálogo, se
normaliza city con `strip()`, se eliminan duplicados/vacíos y se ordena por el
orden lexicográfico estable de Python. No depende de filtros, página, decisiones
ni comprador; devuelve solo cadenas públicas, sin propietarios u otros datos.
No existe un catálogo maestro independiente. Esta consulta de opciones necesita
leer los publicados para descartar documentos incompletos; no se hace en cada
página de exploración y no se añade caché con invalidación nueva.

## Integración US8.2 (solo soporte backend)

1. Abrir filtros: GET preferencias (misma cuenta/configuración desde explorador y perfil).
2. Guardar PUT completo o restablecer DELETE; esperar 200 y usar la respuesta canónica confirmada.
3. Descartar cursor anterior y tarjetas anteriores.
4. GET explorador **sin cursor**, con las preferencias persistidas.
5. Si la exploración falla después del guardado, reintentar esa consulta. No mostrar
   que falló el guardado ni revertirlo: son dos operaciones independientes.

Pendiente de frontend: impedir envíos repetidos, bloquear swipes de tarjetas
anteriores durante recarga, descartar respuestas tardías, mostrar filtros activos,
confirmación y errores; navegación desde perfil/explorador y estado vacío con
acciones «Modificar filtros» y «Restablecer filtros». No se implementó ni verificó UI.

Texto de estado vacío requerido:

> No hay viviendas pendientes que coincidan con tus filtros. Prueba a ampliar tus criterios de búsqueda.

La API conserva 200 `{"items":[],"next_cursor":null}`, sin introducir texto de UI.

## US8.5 y regresión de avisos

`test_preferences.py` cubre validación/canonización, cada criterio y combinación,
tipos/rangos/precisión, permisos de los cinco métodos/rutas, credenciales, identidad,
JSON y fallos internos. `test_firestore_preferences.py` utiliza colecciones únicas,
Firestore Emulator real y limpieza por caso: sustitución, persistencia, AND,
límites exactos, aislamiento, reset sin alterar decisiones/matches, localidades,
paginación con empates y 65 descartes antes de las coincidencias, cursores ligados
a configuración, fallo inyectado antes de commit y guardado seguido de fallo de
exploración con reintento. `FirebaseFlowTests` verifica preferencias tras logout
real y nuevo ID token de Auth Emulator. La suite CI ya descubre estos módulos en
`manage.py test accounts properties`; no necesita cambios de CI.

Los dos fallos de `test_firestore.py` eran expectativas anteriores a US5:
`_write_decision` crea aviso `INTEREST` y match `PENDING`. Se corrige solo esas
expectativas al mensaje «Tienes un nuevo candidato interesado en tu vivienda.»
y se comprueba PENDING, manteniendo relaciones, privacidad y paginación.
`test_seller_confirms_candidate_and_mutuality` conserva la prueba de CONFIRMED y
añade que el aviso original sigue siendo INTEREST. **US5 actual no produce una
notificación de confirmación para BUYER**: `_write_seller_decision` actualiza el
match, no escribe notificaciones. Esa ausencia no se corrige inventando un aviso
ni sustituyendo globalmente los textos; los avisos históricos se conservan.

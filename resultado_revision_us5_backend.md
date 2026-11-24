# Revisión del backend de US5

Fecha: 14 de noviembre de 2026. Repositorio: SwipeHome. Rama: feature/us5-Confirmacion-visualizacion-matches-backend. Commit revisado: a650aac. Alcance: US 5.4, 5.5, 5.6 y 5.7.1, exclusivamente backend.

## Veredicto

| US | Veredicto | Motivos |
|---|---|---|
| 5.4 | **Cumple parcialmente** | Las consultas nuevas filtran estados y cuentas, validan parámetros y paginan correctamente en los casos ejecutados. Faltan el nombre del vendedor requerido por la pantalla del comprador y la recuperación de candidaturas del esquema anterior. La propiedad se toma de una copia en el match, con el riesgo descrito en H4. |
| 5.5 | **Cumple parcialmente** | Las transiciones ordinarias, ID original, fechas, idempotencia, conflicto, aislamiento por candidatura, rollback y concurrencia funcionan. La comprobación del LIKE de origen es insuficiente y se confía en un propietario potencialmente desactualizado. No existe protección CSRF literal; véase D1 sobre el contrato Bearer. |
| 5.6 | **Cumple parcialmente** | Reutiliza matches, conserva la clave canónica y actualiza estado/fechas atómicamente. La persistencia tras nueva sesión y reinicio real está comprobada. Falta una evolución efectiva de los registros antiguos para que puedan consultarse como pendientes; las relaciones del origen no se validan completamente. |
| 5.7.1 | **Cumple parcialmente** | El endpoint canónico crea LIKE + PENDING + aviso INTEREST atómicamente; PASS, reintentos en los tres estados, concurrencia y exclusión del explorador funcionan. La documentación de US4 sigue siendo contradictoria y existe una ruta antigua pública que elude ese flujo. La conservación de CSRF literal no se cumple en este stack. |

**Resultado global:** el flujo principal nuevo funciona con datos coherentes y las 170 pruebas versionadas pasan, pero no procede dar estas historias por completamente verificadas y conformes por los hallazgos siguientes. Las pruebas adicionales de reproducción que terminan en OK comprueban en varios casos el comportamiento defectuoso observado; no significan que ese comportamiento cumpla el requisito.

## Fuentes y arquitectura

Se comprobaron la raíz Git y sus antecesores accesibles, y se buscaron AGENTS.md también entre archivos ocultos: no se localizaron instrucciones con ese nombre aplicables. Se consultaron README raíz/backend y los documentos de Agents mds: project_context, backend_context, infra_context, skills, firebase_auth_migration, frontend_context, us4_backend, us5_backend y us6_backend. Git estaba limpio al inicio.

La US5 completa y los criterios originales se obtuvieron mediante lectura del repositorio conectado en GitHub:

- [US5 principal, CA-01 a CA-08](https://github.com/UB-ES-2026-B3/SwipeHome/issues/4).
- [US5.4](https://github.com/UB-ES-2026-B3/SwipeHome/issues/65), [US5.5](https://github.com/UB-ES-2026-B3/SwipeHome/issues/66), [US5.6](https://github.com/UB-ES-2026-B3/SwipeHome/issues/67), [US5.7.1](https://github.com/UB-ES-2026-B3/SwipeHome/issues/69).
- Datos que requieren las pantallas: [US5.1](https://github.com/UB-ES-2026-B3/SwipeHome/issues/62) y [US5.2](https://github.com/UB-ES-2026-B3/SwipeHome/issues/63).

No se revisaron chat, reserva, adjudicación, notificaciones de otras historias ni el comportamiento visual del frontend.

El motor configurado es **Firestore**, con Firebase Auth; Django tiene DATABASES vacío. Se usaron Firestore Emulator v1.22.0 y Auth Emulator del CLI 15.34.1, proyecto demo-swipehome-us4, únicamente loopback. No se sustituyó el motor por SQLite ni por una base simulada. El emulador no equivale al servicio de producción y no certifica índices remotos.

Flujos inspeccionados:

- config/urls.py:29 -> properties/match_views.py:25 -> properties/match_service.py:36 -> accounts/repository.py:647, para matches.
- config/urls.py:30 -> properties/match_views.py:40 -> properties/match_service.py:108 -> accounts/repository.py:613, para candidatos.
- config/urls.py:31 -> properties/match_views.py:55 -> properties/match_service.py:152 -> accounts/repository.py:503 y :539, para la decisión del vendedor.
- config/urls.py:26 -> properties/discovery_views.py:33 -> properties/discovery_service.py:14 -> accounts/repository.py:338 y :385, para decisiones US4.
- accounts/authentication.py:26 verifica Bearer, revocación Firebase y revocación persistida; :66 construye request.user con rol del perfil del servidor. El cuerpo y los parámetros no eligen identidad.
- properties/serialization.py:35 y properties/match_service.py:70 serializan campos explícitos. Las respuestas inspeccionadas no incluyen email, teléfono, contraseñas, hashes ni tokens.

Las referencias son relativas a la raíz Git; los archivos Python anteriores están bajo backend/ salvo que se indique otra cosa.

## Matriz de criterios de aceptación

Una fila por CA original. El estado cubre solo la parte backend y se valora conjuntamente para las US relacionadas; un caso ordinario correcto no oculta un incumplimiento del mismo criterio.

| US relacionadas | Criterio | Estado | Evidencia | Referencia a ruta:línea o prueba |
|---|---|---|---|---|
| 5.4 | CA-01: consulta de matches del comprador | **No cumple** | Solo devuelve CONFIRMED propios y el inmueble completo en datos normales, pero falta el nombre del vendedor que necesita US5.1. | backend/properties/match_service.py:70; backend/properties/serialization.py:35; test_extra_integrated; H5. |
| 5.4, 5.5, 5.6, 5.7.1 | CA-02: interés mutuo obligatorio | **No cumple** | PENDING/REJECTED quedan fuera del listado, pero la transición acepta como origen un LIKE de otra pareja. | backend/accounts/repository.py:557; test_extra_origin_mismatch; H3. |
| 5.4, 5.7.1 | CA-03: candidatos identificables del propietario | **No cumple** | Los nuevos pendientes identifican comprador/vivienda; un registro realista del esquema US4 anterior queda invisible aunque el reintento devuelve PENDING. | backend/accounts/repository.py:620; test_extra_old_schema; H1. |
| 5.5, 5.6, 5.7.1 | CA-04: confirmación sobre el registro existente | **No cumple** | En el flujo ordinario conserva ID y aparece en ambas listas; falta garantizar que el interés positivo corresponde a ese comprador e inmueble. | backend/accounts/repository.py:557; backend/properties/test_firestore_matches.py:108; H3. |
| 5.5, 5.6 | CA-05: rechazo de la candidatura | **Cumple** | PASS guarda REJECTED y decided_at, sale de candidatos y no aparece en confirmados; conserva otras candidaturas. | backend/accounts/repository.py:573; backend/properties/test_firestore_matches.py:136; test_extra_integrated y recorrido HTTP real. |
| 5.4, 5.5, 5.6 | CA-06: privacidad e independencia | **No cumple** | El aislamiento normal de dos compradores/dos vendedores funciona, pero la autorización/listado usa seller_uid del match sin verificar la propiedad actual cuando existe esa copia. No cambia otras candidaturas. | backend/accounts/repository.py:547; :620; :653; test_extra_ownership; H4. |
| 5.5, 5.6, 5.7.1 | CA-07: persistencia y ausencia de duplicados | **Cumple** | Flujo canónico: ID y fechas estables, reintentos en tres estados, carreras opuestas 200/409 e iguales 200/200; persiste tras logout/login y reinicio WSGI. Este resultado no acredita la compatibilidad histórica ni la ruta heredada. | backend/accounts/repository.py:416; :580; :588; test_extra_independent_connections_concurrency; test_extra_restart; network.py; H1/H2 limitan otras garantías. |
| 5.4, 5.5 | CA-08: listas vacías y errores | **Cumple** | 200 con items vacío/next_cursor null; 400 por entradas inválidas; 404 ajeno/inexistente; 409 contradicción; 500 seguro y rollback ante fallo antes de commit. | backend/properties/match_views.py:29; :45; :65; backend/properties/test_matches.py:82 y :143; test_extra_rollback_and_errors. |

D1 no se presenta como un CA adicional inventado: es una discrepancia explícita de los requisitos técnicos de autenticación/CSRF.

## Hallazgos por impacto

### H1 — Alto: los intereses anteriores a US5 no aparecen en candidatos

**Afecta:** US5.4/5.6; CA-03 y evolución de esquema.

**Ubicación:** backend/accounts/repository.py:620 y :621; fallback en :562 y :416. La forma anterior está acreditada por git show HEAD^:backend/accounts/repository.py: el match solo guardaba buyer_uid, listing_id, decision_id y created_at.

**Reproducción ejecutada:** crear un LIKE en la base del emulador y reemplazar únicamente su documento matches por esos cuatro campos anteriores, manteniendo swipe, aviso, inmueble y fotografías. Repetir POST /api/inmuebles/{id}/decision con LIKE y consultar GET /api/candidatos como propietario.

**Esperado:** mismo ID, estado lógico PENDING y candidatura consultable por el propietario, identificando comprador e inmueble; ninguna conversión automática a CONFIRMED.

**Observado:** el reintento da 200 con status PENDING, pero candidatos da 200 con items vacío. La consulta exige tanto seller_uid como status, ausentes en los documentos anteriores. El fallback que interpreta falta de estado como pendiente solo se aplica al acceso por ID, no a la consulta. No se localizó backfill ni migración de esos campos o de los nombres/títulos necesarios para la pantalla.

La decisión directa sobre el ID antiguo sí funciona y no altera el inmueble/fotos ni el usuario sintético, pero el vendedor no puede descubrirlo desde su lista. La ausencia de migraciones ORM es coherente con Firestore; no soluciona esta incompatibilidad de datos.

**Evidencia:** test_extra_old_schema; extra.log: old schema retry status PENDING candidates {'items': [], 'next_cursor': None}. Es un fallo reproducido de compatibilidad, no una migración ejecutada con éxito.

### H2 — Alto, heredado: sigue publicada una ruta que elude el registro canónico de interés

**Afecta:** integración y garantías de US4/US5.7.1. Es preexistente respecto a este commit; no se atribuye su introducción a US5.

**Ubicación:** backend/config/urls.py:28; backend/properties/views.py:46; backend/accounts/repository.py:196.

**Reproducción ejecutada por HTTP con Auth real del emulador:**

1. Registrar SELLER s1, SELLER s2 y BUYER b1; preparar una vivienda de s1.
2. Con token de s2, POST /api/inmuebles/decidir con {"property_id":"<vivienda>","decision":"LIKE"}.
3. Repetir esa ruta como b1 sobre la misma vivienda.
4. Consultar el explorador canónico de b1 y buscar el match canónico en Firestore.

**Esperado:** un SELLER no puede registrar decisiones BUYER; toda ruta pública de interés aceptada debe conservar las garantías del flujo canónico, o estar retirada.

**Observado:** ambos POST devuelven 200, {"decision":"LIKE","match":false,"duplicate":false}. Solo escriben en decisions; no crean swipe canónico, candidatura ni aviso. La vivienda sigue en /api/inmuebles/explorar para b1. La ruta no comprueba rol, ni participa en la transacción canónica; usa consulta previa y create separado.

El endpoint nuevo /api/inmuebles/{id}/decision sí cumple este aspecto. La coexistencia de un escritor público paralelo contradice la garantía de que el registro de interés se centraliza en record_decision. No se probaron carreras sobre la ruta heredada: su resultado concurrente no se da por verificado.

**Evidencia:** network.py y server.log, dos POST reales 200; mensaje NETWORK legacy SELLER LIKE 200 ... BUYER home remains explorable True.

### H3 — Medio: se acepta un LIKE de otra pareja como origen de una confirmación

**Afecta:** US5.5/5.6; CA-02/04.

**Ubicación:** backend/accounts/repository.py:557 a la comprobación de value en :559.

**Reproducción ejecutada:** crear dos LIKE, de buyer-1/home-1 y buyer-2/other. En la base aislada, cambiar decision_id del primer match al ID del segundo swipe. Como vendedor propietario del primer inmueble, enviar LIKE a decision-vendedor.

**Esperado:** detectar incoherencia y rechazar sin actualizar el match; comprobar buyer_uid, listing_id, clave canónica y relación con decision_id, además del valor LIKE.

**Observado:** 200 CONFIRMED, con fechas nuevas. Solo se comprueba que el documento apuntado exista y que value sea LIKE.

**Alcance del riesgo:** la reproducción requiere datos alterados mediante acceso administrativo al emulador. No se encontró una ruta canónica que permita a un comprador escribir decision_id arbitrario. Por tanto, es un fallo de integridad/validación de origen, no una suplantación externa demostrada. Si falta completamente el swipe, sí se responde 500 seguro y no hay modificación, comprobado en test_extra_rollback_and_errors.

**Evidencia:** test_extra_origin_mismatch, respuesta 200 y estado persistido CONFIRMED.

### H4 — Medio, condicionado a datos incoherentes: se confía en el propietario copiado en el match

**Afecta:** US5.4/5.5/5.6; CA-06.

**Ubicación:** backend/accounts/repository.py:547 y :549; consultas en :620 y :653.

**Reproducción ejecutada:** crear candidatura de una vivienda de seller-1; cambiar listings.seller_uid a seller-2 en la base sintética sin actualizar el match. Consultar candidatos con ambas cuentas y decidir como seller-1.

**Esperado:** si la fuente de propiedad es el inmueble, seller-1 deja de poder consultar/decidir; seller-2 obtiene acceso.

**Observado:** seller-1 conserva una candidatura y puede confirmarla con 200; seller-2 recibe cero candidatos. El vendedor del inmueble solo se consulta si falta seller_uid en el match. Un filtro inmueble explícito verifica la propiedad actual en match_service, de modo que el comportamiento con y sin filtro diverge.

**Alcance:** no se localizó una API actual de transferencia de propietario. La reproducción exige modificar datos administrativos y no demuestra explotación con las APIs ordinarias. Aun así, contradice la regla del README backend:469 que define la propiedad desde listings y afirma que no se duplica.

**Evidencia:** test_extra_ownership, old/new candidates 1/0 y old seller decision 200.

### H5 — Medio: falta el nombre del vendedor para la pantalla del comprador

**Afecta:** US5.4; parte backend de CA-01.

**Ubicación:** backend/properties/match_service.py:70; backend/properties/serialization.py:35.

**Reproducción ejecutada:** confirmar una candidatura válida y consultar GET /api/matches como comprador.

**Esperado:** datos suficientes para la tarjeta de US5.1, incluido el nombre del vendedor. Este requisito procede de la US5 completa y sus pantallas, no de una preferencia de revisión.

**Observado:** cada item contiene únicamente id, status, confirmed_at, created_at y listing. El anuncio incluye título, dirección/localidad, condiciones y fotos, pero ningún nombre del vendedor ni objeto seller. El propio README tampoco define ese dato para este endpoint.

El contrato local documentado se cumple en su forma actual, pero no abastece todos los campos funcionales solicitados. No se propone exponer email ni teléfono.

**Evidencia:** test_extra_integrated y recorrido HTTP network.py, listado de claves de la respuesta. [Requisito de US5.1](https://github.com/UB-ES-2026-B3/SwipeHome/issues/62).

### H6 — Bajo: el contrato de US4 sigue afirmando comportamientos anteriores incompatibles

**Afecta:** requisito documental de US5.7.1.

**Ubicación:** backend/README.md:229, :364 y :469; Agents mds/us4_backend.md:19 y :57; también bloques vigentes de contexto anteriores a US5.

**Reproducción por inspección:** comparar las secciones US4/avisos del README y us4_backend con el flujo HTTP actual y con Agents mds/us5_backend.md.

**Esperado:** distinguir interés enviado/PENDING de match confirmado y documentar el aviso INTEREST, incluidos reintentos que conservan CONFIRMED o REJECTED.

**Observado:** el ejemplo del LIKE incorpora PENDING, pero se sigue diciendo que no existe aceptación del vendedor y se muestra un aviso nuevo type MATCH con mensaje de nuevo match. El código realmente guarda INTEREST y el mensaje de candidato interesado. Además, se afirma que el match no almacena propietario, aunque ahora sí lo hace.

Las pruebas US5 cubren el estado pendiente y un reintento confirmado, pero la documentación US4 no queda adaptada de forma consistente. No se modificó durante esta revisión.

### D1 — Discrepancia de requisitos: no existe protección CSRF Django

**Afecta:** requisito literal de US5.5 y conservación de CSRF de US5.7.1.

**Ubicación:** backend/config/settings.py:28 y :36; backend/accounts/authentication.py:26; backend/README.md:224 y :582.

**Prueba ejecutada:** POST válido de decisión del vendedor mediante Client(enforce_csrf_checks=True), sin cookie ni token CSRF y con Bearer válido: 200. También se ejecutó el flujo por HTTP real sin CSRF.

**Esperado literal del encargo/issues:** protección CSRF exigible en la petición; una petición autenticada sin token CSRF tendría que rechazarse si ese es el mecanismo requerido.

**Observado:** no hay CsrfViewMiddleware ni sesión por cookies. La protección literal no está implementada. Activar enforce_csrf_checks no agrega middleware y por ello no demuestra comprobación CSRF.

**Interpretación:** los documentos vigentes del proyecto describen una adaptación previa a Firebase/Bearer y dicen expresamente que no se usa CSRF Django. Las cookies por sí solas no autentican y el header Bearer se verifica en servidor, de modo que este resultado no prueba una vulnerabilidad CSRF del esquema Bearer. Se registra la diferencia contractual; no se presenta la protección por cookies como cumplida ni se exige cambiar arquitectura durante una revisión.

## Pruebas ejecutadas y resultados

### Preparación y comandos

El intérprete versionado/local .venv no tenía azure-storage-blob instalado. El primer comando:

    .\.venv\Scripts\python.exe -B manage.py test properties.test_discovery properties.test_firestore properties.test_matches properties.test_firestore_matches --verbosity 2

terminó con ModuleNotFoundError: No module named 'azure' antes de ejecutar pruebas. No es un fallo funcional acreditado del código ni del requirements.txt, que sí incluye el paquete.

Se creó un entorno externo al repositorio en:

    C:\Users\Ordinador\AppData\Local\Temp\swipehome-us5-review

En PowerShell, desde backend, la preparación y los controles efectivos fueron:

    python -m venv "$env:TEMP\swipehome-us5-review\venv"
    & "$env:TEMP\swipehome-us5-review\venv\Scripts\python.exe" -m pip install -r requirements.txt
    & "$env:TEMP\swipehome-us5-review\venv\Scripts\python.exe" -B manage.py test properties.test_discovery properties.test_firestore properties.test_matches properties.test_firestore_matches --verbosity 2
    & "$env:TEMP\swipehome-us5-review\venv\Scripts\python.exe" -B manage.py check
    & "$env:TEMP\swipehome-us5-review\venv\Scripts\python.exe" -B manage.py makemigrations --check --dry-run
    & "$env:TEMP\swipehome-us5-review\venv\Scripts\python.exe" -m pip check
    git diff --check

Resultados: subconjunto sin emuladores, 55 descubiertas, 25 ejecutadas correctamente y 30 omitidas por falta de emulador; check sin incidencias; sin migraciones pendientes; dependencias correctas; diff correcto.

Se utilizó el CLI 15.34.1 ya disponible en la caché local de npx, con Node v24.15.0 y Java 21.0.2. Instalación completada con las versiones exactas de requirements.txt; no se cambió .venv del proyecto.

### Suite versionada completa, primero

El equivalente reproducible usando el comando documentado es:

    npx.cmd --yes --package firebase-tools@15.34.1 firebase emulators:exec --project demo-swipehome-us4 --only auth,firestore --config tests/firebase.json "<python-temporal> -B manage.py test accounts properties --verbosity 2"

La ejecución efectiva usó node sobre el lib/bin/firebase.js cacheado y una configuración en TEMP para que los logs no se escribieran en el proyecto:

    node "<cache-npx>\firebase-tools\lib\bin\firebase.js" emulators:exec --project demo-swipehome-us4 --only auth,firestore --config "<TEMP>\firebase.json" "<python-temporal> -B <TEMP>\run_all.py <ruta-backend>"

run_all.py cambia al backend y ejecuta, en orden:

    <python-temporal> -B manage.py test accounts properties --verbosity 2
    <python-temporal> -B <TEMP>\review_extra.py

**Resultado versionado: Ran 170 tests in 17.041s, OK, sin omisiones.** Evidencia guardada fuera del repositorio en suite.log.

Incluye los módulos properties.test_discovery, test_firestore, test_matches, test_firestore_matches y las regresiones de cuentas/avisos/perfiles. Las integraciones de matches simulan verificación del token/perfil, pero utilizan Firestore real emulado. La suite incluye además un flujo con Auth real del emulador; las fotografías de ese flujo simulan Azure.

Casos acreditados por las pruebas existentes:

- LIKE nuevo, PASS, idempotencia, conflicto y unicidad canónica.
- Fallos al preparar cada una de las tres escrituras y rechazo de commit: no persiste un subconjunto nuevo.
- LIKE/LIKE/LIKE simultáneos, PASS simultáneos y LIKE/PASS: convergencia o conflicto, sin duplicación.
- Orígenes incoherentes de US4 y ausencia de match: no se presenta éxito.
- Explorador: exclusión de decisiones propias LIKE/PASS, conservación de fotografías y decisiones ajenas sin retirar la vivienda para otros compradores.
- Roles, tokens ausentes/caducados/revocados, cookies insuficientes, petición con identidad manipulada, JSON/campos inválidos.
- 200 vacío, parámetros inválidos, 500 seguros, paginación y persistencia US4.
- Transiciones US5, ID original, misma decisión 200, contraria 409 y acceso ajeno 404.

Referencia de atomicidad US4: backend/properties/test_firestore.py:130 y :144. Concurrencia US4: :196, :202 y :207. Pruebas US5: backend/properties/test_firestore_matches.py:80, :108, :136, :150, :167, :179, :187 y :215.

La prueba concurrente US5 versionada solo exige que aparezcan algún 200 y algún 409; por sí sola no descarta un tercer 500 ni compara todas las fechas. Se complementó con los controles más estrictos siguientes.

### Ocho comprobaciones temporales adicionales

**Resultado: Ran 8 tests in 10.269s, OK.** Archivo review_extra.py, salida extra.log, ambos en TEMP.

| Comprobación | Resultado y alcance |
|---|---|
| test_extra_integrated | Dos compradores, dos vendedores, tres viviendas; dos confirmados sobre una misma vivienda, rechazo independiente y otra candidatura pendiente. Reintentos LIKE en PENDING/CONFIRMED/REJECTED devuelven mismo ID/estado sin tocar el documento ni duplicar avisos. Explorador excluye los tres estados. Filtros ajenos: 403. Reproduce falta de nombre del vendedor y ausencia de CSRF literal. |
| test_extra_ties_boundary_and_new_confirmation | Cinco candidaturas con created_at idéntico; páginas de tamaño 2. Se confirman ambos elementos de la primera página, incluido el que fija el cursor. Las siguientes páginas devuelven exactamente los otros tres sin duplicados ni saltos. Cuatro confirmados con confirmed_at idéntico respetan ID descendente. Una confirmación nueva anterior al cursor no entra en la continuación y sí al refrescar. |
| test_extra_old_schema | Reproduce H1. Conserva datos de inmueble/fotos y usuario sintético; el acceso directo puede resolver el registro, pero no existe una migración efectiva de consulta. |
| test_extra_origin_mismatch | Reproduce H3 con escritura controlada en la base aislada. |
| test_extra_ownership | Reproduce H4 con cambio administrativo del propietario del inmueble. |
| test_extra_rollback_and_errors | Fallo controlado tras preparar Transaction.update: HTTP 500 genérico, documento idéntico al anterior. Sin swipe de origen: 500 y ningún cambio. Parámetros vacíos/repetidos/desconocidos: 400; sin Bearer: 401; BUYER al decidir: 403; match inexistente: 404. |
| test_extra_independent_connections_concurrency | Dos clientes Firestore/gRPC independientes y dos clientes HTTP Django con barrera. LIKE/PASS: exactamente 409/200, ganador REJECTED, fecha de la respuesta ganadora idéntica a la persistida. LIKE/LIKE: exactamente 200/200, mismo ID, estado y fechas. |
| test_extra_restart | Un proceso Python nuevo abre su propio cliente Firestore y verifica CONFIRMED y decided_at persistidos. Este caso solo demuestra acceso desde proceso nuevo; el reinicio efectivo de Django se cubrió después por HTTP. |

Los casos de concurrencia usan el motor Firestore emulado del proyecto, no una simulación en memoria. Las pruebas temporales no se añadieron a la suite versionada.

### HTTP real, Auth real y reinicio del backend

Se ejecutó network.py con Auth/Firestore Emulator y un servidor WSGI Django temporal en 127.0.0.1:18051, sin mocks de identidad, perfiles ni base de datos. Usó una credencial anónima del proyecto demo, inicializada únicamente en el proceso temporal.

Un primer arranque posterior no pudo reutilizar el puerto 8080 porque seguía ocupado. No se mataron procesos ajenos: se repitió con Firestore 18080, Auth 19099 y puertos auxiliares propios. La segunda configuración usa las reglas cerradas existentes del repositorio.

Comando efectivo, desde TEMP:

    node "<cache-npx>\firebase-tools\lib\bin\firebase.js" emulators:exec --project demo-swipehome-us4 --only auth,firestore --config "<TEMP>\firebase-network.json" "<python-temporal> -B <TEMP>\network.py <ruta-backend>"

**Resultado: salida 0, recorrido completado.** Evidencia en server.log y en la salida NETWORK del comando.

Secuencia comprobada:

1. Registro por API de dos SELLER y dos BUYER; login en Auth Emulator para obtener tokens reales.
2. Cuatro viviendas sintéticas con propietario y fotografías; cuatro LIKE nuevos con 201/PENDING, tres pendientes de un vendedor y uno del otro.
3. Antes de decidir, matches del comprador vacío; intento de decidir por otro vendedor: 404.
4. Confirmación de dos compradores para la misma vivienda; rechazo de otra candidatura del mismo comprador; la tercera vivienda sigue pendiente.
5. Reintentos sobre los tres estados: 200 y mismo match. Persistencia verificada en Firestore.
6. Reproducción de la ruta heredada H2, con SELLER y BUYER.
7. Logout del comprador: 204; token revocado al consultar matches: 401. Nuevo login y nuevo token: misma respuesta que antes.
8. Terminación del proceso WSGI temporal y arranque de otro proceso Django sobre la misma base del emulador. GET /api/matches devuelve idéntico contenido; REJECTED permanece guardado; repetir la confirmación conserva confirmed_at.

Los procesos del servidor temporal se cerraron al terminar. No se reinició ni se accedió a ningún backend de producción. Las fotografías se representaron por URLs sintéticas existentes en los datos de prueba; no se subieron ni borraron blobs.

## Garantías y límites

- **Paginación:** se ejecutaron empates y tres páginas, incluyendo la resolución del último elemento de la primera página. El cursor usa valores fecha/ID y no necesita recuperar el documento que marcó la posición. No se observan desplazamientos tipo OFFSET. Las nuevas confirmaciones situadas antes del cursor aparecen al refrescar; esto es compatible con un recorrido sin instantánea, como documenta backend/README.md:283. No se promete enumerar en una continuación todos los registros insertados después de iniciarla.
- **Unicidad:** efectiva para las escrituras canónicas por clave SHA-256 y create transaccional. Firestore no impone UNIQUE sobre buyer_uid/listing_id ni FK/CHECK sobre documentos arbitrarios. H3 es precisamente un hueco de los controles de servicio. No se certifica integridad ante cualquier escritura Admin.
- **Estado/fechas:** las rutas canónicas nuevas generan PENDING sin decided_at; LIKE vendedor fija CONFIRMED/confirmed_at/decided_at; PASS fija REJECTED/decided_at en el mismo commit. Misma decisión conserva fechas. Los datos malformados escritos por Admin no están protegidos por restricciones del motor.
- **Migración:** no existe ORM activo ni una migración Django US5 pendiente. Se probó la compatibilidad con la forma persistida por el commit anterior, y falla la consulta. No se ha ejecutado un migrador de datos porque no se localizó uno. No se certifica una actualización masiva de una base antigua ni la conservación de datos de producción.
- **Fallos:** se probó fallo local antes del commit del vendedor y fallos/commit rechazado de US4. No se simuló pérdida de respuesta después de que el servicio remoto aceptara el commit. En ese caso el resultado puede existir completo y el reintento es el mecanismo de recuperación; no se promete revertir un commit ya aceptado.
- **Índices:** las combinaciones de filtros/orden están declaradas en backend/firestore.indexes.json para BUYER/SELLER, candidatos y filtro listing_id. Su existencia y habilitación en producción **no se verificaron**. El emulador no las acredita; un despliegue sin índices puede fallar aunque estas pruebas pasen.
- **Privacidad:** respuestas de los flujos ejecutados usan listas explícitas de campos y no contienen contacto/credenciales. H4 requiere datos incoherentes y no se presenta como acceso entre cuentas reproducible con las APIs ordinarias.
- **CSRF:** requisito literal ausente, diferencia documentada en D1. Bearer y revocación sí se verificaron; no se cambió la arquitectura para fabricar conformidad.
- **Cobertura:** las carreras ejecutadas acreditan esos intercalados, no una prueba exhaustiva de todos los posibles. Conexiones independientes se usaron en los dos casos temporales de decisiones del vendedor; las carreras de LIKE de US4 también se ejecutaron en su suite existente con el emulador.

## Evidencia insuficiente separada de los incumplimientos

| Caso | Estado | Motivo y forma de completar |
|---|---|---|
| Índices remotos y carga real de Firestore | No verificado | Solo emuladores; comprobar los índices habilitados del proyecto de despliegue y repetir consultas con las combinaciones de inmueble/rol. No se requiere hacerlo para reproducir H1-H6. |
| Migración masiva de una base anterior | No verificado como operación de migración | No se localizó migrador. Sí hay fallo reproducido con la forma anterior en H1. Una futura solución debe probarse con una copia aislada que contenga usuarios, anuncios, fotos y swipes previos. |
| Transferencia de propietario por API | No verificado / no localizada | H4 se reproduce administrativamente, sin afirmar que hoy exista transferencia pública. Si el propietario es inmutable por diseño, documentar esa garantía y su mantenimiento administrativo. |
| Pérdida de conexión tras commit remoto aceptado | No verificado | Requiere inyección de fallo en transporte después del commit; los fallos previos y los reintentos ordinarios sí se comprobaron. |
| CSRF con sesión Django | No aplicable al mecanismo instalado; requisito literal no satisfecho | El backend no ofrece esa sesión ni su middleware. Las pruebas exigentes ejecutadas muestran que no comprueba CSRF, no que hubiera una petición protegida satisfactoria. |

## Conservación del repositorio

No se modificaron código, pruebas versionadas, documentación existente, índices, configuración ni datos locales del proyecto. No se hicieron commits, push ni despliegues. Los scripts, venv y logs de pruebas se crearon en TEMP; las bases usadas fueron emuladores demo.

Antes de redactar este archivo se repitieron git status --short, git diff --stat y git diff --check: árbol limpio y ningún diff. Comprobación tras guardar el informe: git status --short muestra únicamente ?? resultado_revision_us5_backend.md (desde backend aparece como ../resultado_revision_us5_backend.md); git diff --exit-code, git diff --cached --exit-code y git diff --check terminan con código 0. El único archivo nuevo es **resultado_revision_us5_backend.md**, en la raíz Git de SwipeHome.

# Contexto del proyecto SwipeHome

## Estado actualizado - US1.3, US1.4.1 y persistencia de cuentas

El backend local usa Django 5.2 y SQLite en la rama
`features-US-1.3-implementar-api-registro`. US1.4.1 (US1-4A) crea la sesion
Django al registrar la cuenta y persiste ambas en una transaccion.
Las cookies tienen HttpOnly, Secure y SameSite=Lax; CSRF esta activo.
HTTPS local y los comandos de instalacion y pruebas estan documentados en
[backend/README.md](../backend/README.md). No hay dependencias adicionales.
La identidad y el rol se resuelven desde request.user en el servidor.
US1-5 centraliza la normalizacion del email en el campo de persistencia.
La migracion 0002 audita colisiones antes de modificar datos y añade un CHECK
de email canonico; se mantienen UNIQUE de email y CHECK de rol.
La suite completa pasa 40 pruebas, incluida concurrencia real y HTTPS.
GET /api/auth/me esta implementado: 200 con id/name/email/role desde la sesion,
401 sin autenticacion y 500 generico ante fallo interno, con Cache-Control no-store.
La consulta se verifica con rutas reales y HTTPS local. La integracion de la
interfaz y la comprobacion de recarga real en navegador siguen pendientes.
Los apartados originales siguientes conservan el contexto del backlog;
el estado implementado actual se describe en este bloque y el README backend.


Documentación preparada el 14 de octubre de 2026 a partir de `contexto-proyecto-codex.md`, leído en Descargas. Los apartados extraídos conservan su numeración de origen para facilitar la trazabilidad.

## Estado observado del repositorio

En la revisión inicial, la única documentación versionada es `README.md`. No hay código de aplicación, manifiestos de dependencias, pruebas ni decisiones tecnológicas acreditadas. Las carpetas locales `.codex/` y `.idea/` estaban sin seguimiento antes de esta tarea y se conservan. No se han consultado issues ni GitHub Projects.

Todo el comportamiento funcional descrito a continuación es esperado, no implementado. No se ha elegido stack, arquitectura ni despliegue. Esta tarea únicamente prepara documentación y ramas locales.

Existe una discrepancia pendiente de resolver: el README dice «Somos 6 jóvenes» y la fuente de contexto describe cinco personas (dos backend, dos frontend y una QA). Se conserva el README y se registra la diferencia sin decidir cuál cifra debe prevalecer.

## Organización de la documentación

- Este archivo es la referencia principal del producto, Sprint 0, historias, criterios de aceptación, tareas, validaciones funcionales y decisiones pendientes.
- [backend_context.md](backend_context.md) conserva las reglas transversales de autenticación, contratos HTTP y modelo conceptual.
- [frontend_context.md](frontend_context.md) conserva las rutas y concreta las responsabilidades de interfaz mediante referencias a las US.
- [skills.md](skills.md) contiene pautas de trabajo para agentes y colaboradores; no acredita skills instaladas ni tecnologías elegidas.
- `agent_changelog_local.md` registra esta tarea localmente y está excluido de Git.

No se crean los archivos adicionales propuestos en la fuente: la distribución documental utilizada es la solicitada por el usuario. Los nombres US1-1, US2-1, etc. son referencias documentales, no identificadores de issues.

## 2. Producto y funcionamiento general

Se está desarrollando una página web para el alquiler de pisos o habitaciones. La idea del producto utiliza una dinámica parecida a Tinder para conectar a personas que buscan alojamiento con quienes lo ofrecen.

Hay dos roles, con estas denominaciones actuales:

| Denominación en el producto | Valor técnico | Responsabilidad |
|---|---|---|
| Vendedor | `SELLER` | Publica inmuebles en alquiler y, en futuras funcionalidades, consulta las personas interesadas y selecciona candidatos. |
| Comprador | `BUYER` | Busca alojamiento y, en futuras funcionalidades, expresa interés o descarta anuncios mediante swipes. |

Aunque se habla de Vendedor y Comprador, la actividad del producto es el **alquiler**, no la compraventa. Mantener estos nombres para ser coherentes con el backlog; no cambiarlos unilateralmente en interfaces, documentación o contratos.

La interpretación coherente del flujo futuro es que el Comprador ve los inmuebles, hace swipe a la derecha si le interesan y a la izquierda si no, y el Vendedor consulta las personas interesadas. En la explicación inicial se repitió por error aparente la palabra Vendedor para el usuario que busca pisos. Esta interpretación debe quedar explícita y no emplearse para ampliar el primer sprint.

No están concretados todavía el comportamiento de un match, la elección definitiva del candidato, las conversaciones entre usuarios ni la formalización del alquiler.

## 3. Equipo, metodología y alcance del primer sprint

El equipo tiene seis personas:

- Dos de backend.
- Dos de frontend.
- Una de QA.
- Un devops

Se utiliza un enfoque de trabajo ágil con Scrum y un tablero Kanban, organizado en GitHub Projects mediante historias y sub-tareas o sub-issues.

El primer sprint se denomina **Sprint 0** en el proyecto y abarca:

1. US1: Registro de usuario.
2. US2: Login de usuario.
3. US3: Publicación de inmuebles.

El equipo se refiere a estas historias principales como US épicas. Para la documentación inicial, mantener esta organización: una historia principal que expresa valor para el usuario y sub-tareas técnicas asociadas. No crear historias independientes llamadas Frontend, Backend o Testing. Si el tamaño obliga posteriormente a dividir una épica, hacerlo por funcionalidades que aporten valor de extremo a extremo.

Las funciones futuras —exploración de anuncios, swipes, candidatos, matches, chat, filtros y gestión posterior de anuncios— no forman parte de estas tres historias. La referencia al perfil y al historial en US2 explica el beneficio del acceso; no implica construir esas pantallas dentro de la historia de login.

El producto contempla pisos y habitaciones, pero el formulario actual de US3 describe un inmueble. No se ha cerrado cómo representar una habitación independiente frente al alquiler completo de un piso. Documentar esta decisión como pendiente y no inventar todavía un campo, una entidad o una US para resolverla.

## 4. Forma de documentar historias y tareas

En la reunión con el project manager se acordó que los criterios de aceptación de las historias principales deben ser más generales, centrados en resultados observables para el usuario. Deben seguir siendo verificables.

Las reglas de campos, endpoints, códigos HTTP, cookies, almacenamiento y comprobaciones detalladas pertenecen a las sub-tareas técnicas o a los documentos de contratos y reglas.

Formato de las historias: **Como [rol], quiero [objetivo], para [beneficio]**. Los criterios generales utilizan **Dado / Cuando / Entonces**. Las tareas técnicas tienen título propio, área, descripción y criterios concretos; no necesitan forzar el formato de historia de usuario.

No tiene que existir una correspondencia uno a uno entre criterio general y sub-tarea: varias tareas pueden contribuir a un mismo criterio. Mantener trazabilidad entre cada US, sus CA y las tareas que los cubren.

El material de teoría consultado, `UserStories.pdf`, insiste en escribir historias que aporten valor, aplicar INVEST, conservar la posibilidad de comprobarlas y describir los requisitos técnicos aparte. Este resumen recoge esa orientación; no sustituye el material docente completo ni resume los contenidos del documento de CI/CD, que no se han revisado para esta síntesis.

## 6. US1: Registro de usuario

**Como** persona no registrada, **quiero** crear una cuenta indicando mi nombre, email, contraseña y rol de Vendedor o Comprador, **para** acceder a las funcionalidades correspondientes a mi actividad en la plataforma.

### Criterios generales

- **CA-01 — Creación de cuenta con el rol elegido:** dado que no existe una cuenta con mi email, cuando proporciono los datos requeridos y selecciono un rol, entonces puedo crear mi cuenta con esos datos y ese rol.
- **CA-02 — Acceso después del registro:** dado que el registro se completa, cuando termina la creación de la cuenta, entonces accedo con la sesión iniciada al inicio correspondiente a mi rol.
- **CA-03 — Datos incompletos o incorrectos:** cuando los datos incumplen las reglas, el sistema impide crear la cuenta e indica qué corregir.
- **CA-04 — Email ya registrado:** cuando intento usar un email asociado a una cuenta, el sistema impide crear otra y me informa del motivo.
- **CA-05 — Fallo durante el registro:** cuando un fallo impide completar el registro, se informa del problema, se permite volver a intentarlo y no queda una cuenta creada parcialmente.

### Reglas detalladas

| Campo | Reglas del registro |
|---|---|
| `name` | Obligatorio, cadena de texto; de 2 a 80 caracteres después de eliminar espacios exteriores. |
| `email` | Obligatorio, cadena de texto; formato válido, sin espacios interiores y máximo 254 caracteres una vez normalizado. |
| `password` | Obligatorio, cadena de texto; de 15 a 128 caracteres; admite espacios y Unicode; sin recortes ni truncamiento. |
| `role` | Obligatorio, cadena de texto; solo `SELLER` o `BUYER`; el formulario no selecciona un rol por defecto. |

El frontend muestra errores junto a los campos y no envía solicitudes inválidas. El backend realiza sus propias validaciones aunque se llame directamente a la API.

La cuenta almacena un hash de contraseña mediante un mecanismo apropiado para contraseñas, nunca texto plano. La unicidad del email se garantiza en la persistencia, no solo mediante una comprobación previa desde la interfaz.

### Sub-tareas actuales

Los números siguientes son referencias documentales, no números de issues de GitHub.

| Referencia | Título | Área | Responsabilidad y trazabilidad |
|---|---|---|---|
| US1-1 | Crear el formulario de registro y sus validaciones | Frontend | Campos, selección de rol, errores y validación previa. CA-01, CA-03. |
| US1-2 | Conectar el formulario de registro con la API | Frontend | Envío de datos, carga, prevención de envíos repetidos y gestión de respuestas. CA-01 a CA-05. |
| US1-3 | Implementar la API de registro | Backend | Validación, normalización, creación de cuenta y respuestas. CA-01, CA-03, CA-04, CA-05. |
| US1-4A | Crear la sesión del usuario tras el registro | Backend | Creación automática de sesión y reconocimiento del usuario y rol. CA-02, CA-05. |
| US1-4B | Actualizar la interfaz y redirigir al usuario según su rol | Frontend | Estado autenticado, navegación y recuperación del estado al recargar. CA-02, CA-05. |
| US1-5 | Crear la estructura y persistencia de usuarios | Backend / Base de datos | Identidad, hash, rol, unicidad del email y creación atómica. CA-01, CA-04, CA-05. |
| US1-6 | Verificar el registro completo | Testing | Pruebas de ambos roles, validaciones, duplicados simultáneos, sesión, errores e información sensible. CA-01 a CA-05. |

US1-4A y US1-4B resultan de dividir la antigua tarea conjunta de sesión. La redirección pertenece a US1-4B; no duplicar su implementación en US1-2.

## 7. US2: Login de usuario

**Como** usuario registrado, Vendedor o Comprador, **quiero** iniciar sesión de forma segura con mi email y contraseña, **para** acceder a mi perfil y consultar mi historial.

### Criterios generales

- **CA-01 — Inicio de sesión correcto:** con una cuenta registrada y credenciales correctas, accedo autenticado al inicio correspondiente a mi rol.
- **CA-02 — Credenciales incorrectas:** un email no registrado y una contraseña incorrecta provocan el rechazo del acceso con el mismo mensaje, sin permitir distinguir ambos casos.
- **CA-03 — Datos incompletos o incorrectos:** el sistema impide continuar e indica qué corregir si los datos incumplen las reglas del login.
- **CA-04 — Fallo durante el inicio de sesión:** el sistema informa del problema, no inicia una sesión nueva y permite volver a intentarlo si un fallo impide completar el acceso.

### Reglas detalladas

| Campo | Reglas del login |
|---|---|
| `email` | Obligatorio, cadena de texto; mismo formato y normalización que en el registro, máximo 254 caracteres. |
| `password` | Obligatorio, cadena de texto; de 1 a 128 caracteres, sin recortes ni modificaciones. |

**La contraseña se comprueba con las credenciales almacenadas; no se reaplica la longitud mínima de 15 caracteres del registro.** El login no solicita elegir un rol. El rol procede de la cuenta encontrada por el servidor.

Mensajes definidos en el backlog:

- Email vacío o inválido: `Introduce un email válido.`
- Credenciales incorrectas: `Email o contraseña incorrectos.` en los dos casos.

El formulario permanece en `/login` ante errores. Un acceso correcto crea una sesión con un identificador nuevo. Una solicitud rechazada no crea una sesión nueva; no se ha definido que deba cerrar automáticamente una sesión que existiera previamente.

### Sub-tareas actuales

| Referencia | Título | Área | Responsabilidad y trazabilidad |
|---|---|---|---|
| US2-1 | Crear el formulario de acceso y sus validaciones | Frontend | Pantalla `/login`, campos y validación previa. CA-03. |
| US2-2 | Conectar el formulario de acceso con la API | Frontend | Envío, carga, respuestas y errores; comunica el éxito a la gestión de autenticación. CA-01 a CA-04. |
| US2-3 | Implementar el endpoint de comprobación de credenciales | Backend | Normalización, validación, comprobación del hash y respuestas. CA-01 a CA-04. |
| US2-4 | Crear una nueva sesión al autenticar al usuario | Backend | Sesión, cookie, identificación del usuario y tratamiento del fallo al crearla. CA-01 a CA-04. |
| US2-5 | Actualizar el estado de acceso y abrir el inicio correspondiente | Frontend | Estado autenticado, redirección según rol y consulta de sesión al recargar. CA-01, CA-02, CA-04. |
| US2-6 | Comprobar la API y la separación de sesiones entre usuarios | Testing | Contratos, validación directa, cookies, fallos y correcta identidad de dos cuentas distintas. CA-01 a CA-04. |
| US2-7 | Verificar el recorrido completo de acceso desde la interfaz | Testing | Login de ambos roles, errores, carga, reintento y recarga. CA-01 a CA-04. |

Reutilizar conceptualmente la estructura de usuarios y el mecanismo de sesión de US1. Dos tareas relacionadas no implican que deban existir dos sistemas de autenticación diferentes.

## 8. US3: Publicación de inmuebles

**Como** usuario registrado con rol de Vendedor, **quiero** publicar un inmueble indicando sus características, condiciones de alquiler y fotografías, **para** ofrecerlo a las personas que buscan alojamiento en la plataforma.

### Criterios generales de la versión vigente

- **CA-01 — Acceso a la publicación:** dado que tengo una sesión iniciada como Vendedor, cuando accedo a la opción de publicar, puedo iniciar un anuncio. Solo los usuarios autenticados con ese rol tienen acceso a la funcionalidad.
- **CA-02 — Publicación con información válida:** cuando completo la información obligatoria, incluyo las fotografías requeridas y confirmo, el anuncio se publica asociado a mi cuenta y recibo confirmación.
- **CA-03 — Fotografías obligatorias:** cuando añado al menos una fotografía válida y completo la publicación, las imágenes quedan asociadas al inmueble. No se puede publicar sin fotografías.
- **CA-04 — Información incompleta o incorrecta:** si faltan datos o incumplen las reglas, se impide publicar y se indica qué corregir.
- **CA-05 — Fotografías no admitidas:** si una fotografía incumple las condiciones, se informa del motivo y se permite retirarla o sustituirla antes de publicar.
- **CA-06 — Fallo durante la publicación:** se informa del problema, se permite volver a intentarlo y no queda un anuncio publicado parcialmente.

**La obligatoriedad de una fotografía como mínimo es una decisión explícita del usuario.** Las versiones anteriores que permitían publicar sin fotos están obsoletas.

### Datos del formulario

Todos estos campos son obligatorios en el backlog vigente:

| Campo | Regla |
|---|---|
| Título del anuncio | Texto no vacío ni compuesto únicamente por espacios. |
| Calle y número | Texto no vacío ni compuesto únicamente por espacios. |
| Localidad | Texto no vacío ni compuesto únicamente por espacios. |
| Código postal | Texto no vacío ni compuesto únicamente por espacios. |
| Descripción | Texto no vacío ni compuesto únicamente por espacios. |
| Precio mensual en euros | Número mayor que cero; persistencia capaz de representar céntimos. |
| Superficie en m² | Número mayor que cero. |
| Dormitorios | Número entero igual o mayor que cero; admite estudios. |
| Baños | Número entero igual o mayor que uno. |
| Personas a las que se ofrece el alquiler | Número entero igual o mayor que uno. |
| ¿Compartirá el inmueble con otras personas? | Selección obligatoria Sí/No, sin valor por defecto. |
| Fotografías | Al menos una imagen válida. |

Se conservan por separado el número de personas y la condición de alojamiento compartido. No se ha definido una relación automática entre ambos campos ni una regla que los compare con el número de dormitorios.

El alcance exacto de «personas a las que se ofrece el alquiler» debe aclararse antes de fijar el esquema definitivo: puede referirse a plazas ofertadas, al grupo destinatario o a capacidad total. El documento actual conserva la formulación del backlog y no resuelve esa ambigüedad.

No están fijados los límites de longitud de los textos, un patrón específico de código postal, máximos de superficie/personas/baños/dormitorios ni el detalle del domicilio dentro de un edificio. No inventarlos como requisitos acordados.

### Fotografías y publicación

La base actual de las sub-tareas utiliza entre **1 y 10 imágenes**, hasta **5 MB por imagen**, en **JPEG, PNG o WebP**. El máximo, el tamaño y los formatos fueron propuestos al redactar el backlog y se conservaron en su versión vigente; documentarlos como base actual pendiente de ratificación específica si se necesita cerrar el contrato. El mínimo de una sí fue confirmado expresamente.

- El frontend permite seleccionar, previsualizar y retirar imágenes antes de publicar.
- Una imagen rechazada no elimina los demás datos ni las imágenes válidas.
- Si no queda ninguna imagen válida, no se envía el formulario y se muestra `Añade al menos una fotografía.`
- El backend comprueba cantidad, tamaño y contenido real de los archivos; la extensión no basta.
- Se conserva el orden enviado desde el formulario.
- Cada imagen almacenada tiene un identificador o nombre generado por el sistema y se asocia al inmueble correcto.
- El anuncio se publica únicamente cuando se han guardado sus datos y todas sus fotografías válidas.
- Un fallo de persistencia o almacenamiento no se comunica como éxito.
- Si se revierte la publicación, se revierten los datos creados y se eliminan los nuevos archivos que queden sin asociación.

Estas son garantías de comportamiento. No imponen una tecnología de base de datos, un proveedor de archivos ni una estrategia concreta para coordinar ambos almacenamientos.

### Propiedad y permisos

- Solo un usuario autenticado con rol `SELLER` puede publicar.
- El vendedor se obtiene de la sesión, no de un identificador de propietario elegido por el cliente.
- Cada anuncio tiene un identificador único, un único vendedor y fecha de publicación.
- Un vendedor puede publicar varios inmuebles.
- El menú de un Comprador no muestra «Publicar», pero ocultar la opción no sustituye la comprobación de permisos del servidor.

### Sub-tareas actuales

| Referencia | Título | Área | Responsabilidad y trazabilidad |
|---|---|---|---|
| US3-1 | Crear el acceso al formulario y los campos del anuncio | Frontend | Menú «Publicar», campos, reglas y errores; integra el apartado de imágenes. CA-01, CA-02, CA-04. |
| US3-2 | Incorporar la selección y previsualización de fotografías | Frontend | Selección, límites, previsualización, retirada y mínimo obligatorio. CA-03, CA-04, CA-05. |
| US3-3 | Enviar el anuncio y mostrar el resultado de la publicación | Frontend | Envío autenticado, carga, confirmación y tratamiento de errores. CA-01 a CA-06. |
| US3-4 | Implementar el endpoint de publicación y sus permisos | Backend | Autorización, propietario de sesión, validación y contrato HTTP. CA-01 a CA-06. |
| US3-5 | Crear la persistencia de inmuebles y su relación con el vendedor | Backend / Base de datos | Datos, propiedad, precio, referencias de imágenes y publicación íntegra. CA-02, CA-03, CA-06. |
| US3-6 | Validar y almacenar las imágenes asociadas al inmueble | Backend | Validación real de archivos, almacenamiento, orden, asociación y limpieza ante fallos. CA-03, CA-04, CA-05, CA-06. |
| US3-7 | Comprobar la API, los permisos y la integridad del anuncio | Testing | Publicaciones válidas, permisos, campos, archivos, límites y fallos de guardado. CA-01 a CA-06. |
| US3-8 | Verificar el recorrido completo de publicación desde la interfaz | Testing | Flujo de menú a confirmación, imágenes, validación, carga, conservación de datos y reintentos. CA-01 a CA-06. |

La interfaz conserva los datos y las fotografías seleccionadas cuando ocurre un error para permitir reintentar. No se ha definido un sistema de borradores ni persistencia del formulario al cerrar el navegador.

## 12. Tablero Kanban y límites de trabajo

Flujo propuesto para las sub-tareas:

**To do → In progress → Ready for testing → Testing → Done**

| Columna | Significado | Límite inicial propuesto |
|---|---|---|
| To do | Tareas del sprint pendientes de empezar. | Sin límite WIP; mantener el alcance del sprint. |
| In progress | Desarrollo en curso. | 4 tarjetas: hasta 2 de backend y 2 de frontend. |
| Ready for testing | Implementación terminada, pendiente de comprobación. | 2 tarjetas. |
| Testing | Verificación en curso. | 1 tarjeta. |
| Done | Criterios cumplidos y comprobaciones superadas. | Sin límite. |

Las tareas de base de datos cuentan dentro de la capacidad de backend. Se propuso una tarjeta activa por desarrollador, permitiendo que dos personas colaboren en una tarjeta. Los límites son un punto de partida para revisar durante la retrospectiva, no una regla universal ni una capacidad calculada con estimaciones.

Usar etiquetas de Frontend, Backend, Base de datos y Testing. Los bloqueos pueden señalarse con una etiqueta `Blocked` y una explicación de qué falta para avanzar. Si las pruebas encuentran un fallo, la tarea vuelve a In progress.

Las tarjetas específicas de pruebas pueden pasar de To do a Testing al comenzar su ejecución. Evitar contar dos veces el mismo trabajo de verificación si se representan simultáneamente la tarjeta de implementación y la sub-tarea de pruebas; el equipo debe acordar cómo reflejar esa relación en el tablero.

La historia principal solo pasa a Done cuando sus sub-tareas están completadas y se han comprobado sus criterios generales con el funcionamiento integrado. Una tarea de frontend terminada no demuestra por sí sola que la US completa esté terminada.

## 13. Expectativas de verificación

Los desarrolladores comprueban su trabajo antes de enviarlo a QA. Las sub-tareas de Testing recogen la validación de contratos, integración y recorrido de usuario; no significan que el QA sea la única persona responsable de la calidad.

Casos especialmente relevantes:

- Registro y acceso con ambos roles.
- Diferencia entre reglas de contraseña del registro y del login.
- Normalización y unicidad del email, incluida concurrencia en registro.
- Validación desde la interfaz y llamadas directas a la API.
- Respuesta indistinguible ante email no registrado y contraseña incorrecta.
- Sesiones correctamente asociadas a dos usuarios distintos.
- Ausencia de contraseñas, hashes y detalles internos en respuestas.
- Publicación restringida a Vendedores y propietario obtenido de la sesión.
- Publicación con una foto, varias fotos y rechazo sin fotos.
- Formatos, tamaños, cantidad y contenido real de imágenes.
- Conservación de orden y asociación correcta de fotografías.
- Fallos de guardado sin cuentas o anuncios parcialmente creados.
- Mensajes, carga, prevención de envíos repetidos y recuperación del estado al recargar.

La prevención de dobles clics en el frontend está definida. Una garantía de idempotencia del servidor ante reintentos o una pérdida de conexión después de guardar no se ha acordado. Documentar esa diferencia sin prometer que nunca habrá duplicados por cualquier causa.

## 14. Decisiones pendientes que Codex debe conservar visibles

No consta una selección definitiva de framework frontend/backend, base de datos, proveedor de imágenes o despliegue en este contexto. Si el repositorio ya contiene decisiones explícitas, reflejarlas con su evidencia; no escoger un stack solo para completar un documento.

También están pendientes:

1. Contratos completos de respuestas y errores y código de éxito del login.
2. Integracion frontend de GET /api/auth/me (endpoint backend ya implementado).
3. Nombres técnicos de los campos de publicación y envío de fotografías.
4. URLs del formulario de registro y del formulario de publicación.
5. Ratificación específica de máximos, tamaño y formatos de imágenes.
6. Límites de textos y validación territorial del código postal.
7. Semántica exacta del número de personas y de la oferta de habitaciones.
8. Duración/expiración de sesiones y condiciones de despliegue de cookies.
9. Cómo coordinar persistencia de datos e imágenes sin publicaciones parciales.
10. Qué hacer ante reintentos cuando no se conoce si una publicación llegó a guardarse.
11. Estimaciones, asignaciones personales, prioridad detallada y duración del sprint.
12. Detalles de CI/CD y criterios comunes de finalización adicionales, si el equipo los acuerda.

Separar las decisiones pendientes de los requisitos que ya se deben cumplir. Si es imprescindible resolver una para implementar, plantear una propuesta explícita; la documentación no debe simular que el equipo ya la aprobó.

# Contexto backend de SwipeHome

## Estado vigente — US4 y US6 (8 noviembre 2026)

El backend usa Django 5.2, Firebase Auth y Firestore. No hay ORM, sesiones por
cookies ni CSRF Django. El usuario confirmó expresamente mantener este stack
para US 4.4–4.7. Los contratos vigentes están en el
[README backend](../backend/README.md), [US4 backend](us4_backend.md) y
[US6 backend](us6_backend.md).

US4 reutiliza usuarios y anuncios actuales, fotografías ordenadas en
`listings.photos`, autenticación con revocación y la colección `notifications`.
LIKE crea directamente decisión, match y aviso; PASS solo crea decisión.
No hay aceptación posterior del Vendedor ni reserva del inmueble.

`accounts/repository.py` centraliza todo Firestore/Storage, incluida la
transacción y las claves canónicas `swipes/{key}`, `matches/{key}` y
`notifications/match-{key}`. Firestore garantiza unicidad de path; valores,
referencias y conjunto completo son garantías del servicio, no CHECK/FK.
Los reintentos equivalentes son 200, nuevos 201 y contrarios 409.
Abortos de lectura/commit y colisiones usan transacciones nuevas acotadas.

GET `/api/inmuebles/explorar` y POST `/api/inmuebles/{id}/decision` son BUYER;
GET `/api/notificaciones` es solo SELLER. `request.user` se construye desde el
token verificado y el perfil, sin aceptar selectores de identidad del cliente.
Los GET comparten `limit/cursor` 20/50, orden fecha/ID descendentes y cursor
firmado. Exploración carga decisiones en batch, sin OFFSET ni consultas por foto.

La evolución de esquema es aditiva y conserva avisos históricos; no hay
migraciones ORM. Los índices están en `backend/firestore.indexes.json` y su
configuración en `backend/firebase.json`; no se han desplegado remotamente.
El detalle de compatibilidad y límites de garantías está en US4 backend.

Verificación: 140 pruebas pasan con Auth/Firestore Emulator, sin omisiones;
sin emuladores pasan 116 y se omiten 24 integraciones. Django check, comprobación
de migraciones, pip check y diff check correctos. No se ha probado producción.

<details>
<summary>Historial anterior a US4 (conservado como referencia)</summary>

# Contexto backend de SwipeHome

> Estado US6 (22 octubre 2026): se conserva Firebase Auth + Firestore.
> El contrato vigente de edición del perfil, contraseña y logout está en
> [us6_backend.md](us6_backend.md). Nombre/email actuales se leen de Auth;
> rol y relaciones permanecen en Firestore. Los apartados anteriores a esta
> adaptación que describen sesiones Django son históricos.

> Estado US3-7 (1 noviembre 2026): `/api/inmuebles` usa Bearer ID token Firebase,
> exige perfil SELLER y obtiene `seller_uid` del token. Los tests API/repositorio
> y sus límites se documentan en el [README backend](../backend/README.md).

> ⚠️ Partes de este documento describen el login por sesiones y cookies, sustituido
> por Firebase Auth. Ver `infra_context.md` y `firebase_auth_migration.md`. Pendiente
> de actualizar.

> Estado US3-8 tras el merge con Azure: la interfaz `/publicar` integra el endpoint
> mediante FormData autenticado. La verificación usa Auth Emulator e intercepta
> la API, sin escrituras reales en Firestore ni Azure Blob. Detalle en el
> [README backend](../backend/README.md).

## Correcci?n de desarrollo HTTP y superusuarios (16 octubre 2026)

DJANGO_DEV=1 activa HTTP local con cookies sin Secure; sin esa variable se conserva
Secure. Debe definirse en la terminal del backend antes de arrancarlo; .env no se
carga autom?ticamente. El frontend obtiene CSRF antes de cada registro/login para
evitar reutilizar el token que Django rota. El modelo admite createsuperuser con
permisos Django independientes de BUYER/SELLER, mediante la migraci?n 0003.
Los comandos vigentes est?n en [README backend](../backend/README.md).


## Estado actualizado - US1.3, US1.4.1 y persistencia de cuentas

El backend local usa Django 5.2 y SQLite en la rama
`features-US-1.3-implementar-api-registro`. La rama de destino de la PR de estas US es `dev` (`origin/dev` en remoto). US1.4.1 (US1-4A) crea la sesion
Django al registrar la cuenta y persiste ambas en una transaccion.
Las cookies tienen HttpOnly, Secure y SameSite=Lax; CSRF esta activo.
HTTPS local y los comandos de instalacion y pruebas estan documentados en
[backend/README.md](../backend/README.md). No hay dependencias adicionales.
La identidad y el rol se resuelven desde request.user en el servidor.
US1-5 centraliza la normalizacion del email en el campo de persistencia.
La migracion 0002 audita colisiones antes de modificar datos y añade un CHECK
de email canonico; se mantienen UNIQUE de email y CHECK de rol.
Las cifras 53/56 anteriores corresponden a ejecuciones históricas de US1/US2.
La suite vigente `accounts properties` contiene 165 tests: todos pasan al
ejecutarla bajo Auth y Firestore Emulator. Azure Blob se simula con mocks. El
comando y resultado vigentes están en el
[README del backend](../backend/README.md).
GET /api/auth/me esta implementado: 200 con id/name/email/role desde la sesion,
401 sin autenticacion y 500 generico ante fallo interno, con Cache-Control no-store.
La consulta se verifica con rutas reales y HTTPS local. El recorrido integrado
de registro, destino por rol y recarga de sesion se verifico en navegador con
SELLER y BUYER; el detalle esta en el README backend.
Los apartados originales siguientes conservan el contexto del backlog;
el estado implementado actual se describe en este bloque y el README backend.


Fuente: `contexto-proyecto-codex.md` , revisada el 14 de octubre de 2026. Los apartados de la fuente mantienen su numeración original.

## Estado y responsabilidad

El backend implementado usa Django y SQLite local; el estado vigente y los comandos
estan en [backend/README.md](../backend/README.md). El login backend esta
implementado; US2-6 verifica la API y US2-7 confirmó el flujo integrado desde
la interfaz, incluida la restauración de sesión al recargar. La publicación
sigue en el backlog.

Las reglas de campos, criterios y tareas se mantienen en [project_context.md](project_context.md):

- US1: US1-3, US1-4A y US1-5 cubren API, sesión automática y persistencia atómica de usuarios; US1-6 recoge la verificación integrada.
- US2: US2-3 y US2-4 cubren comprobación de credenciales y nueva sesión; US2-6 verifica contratos y separación entre usuarios.
- US3: US3-4, US3-5 y US3-6 cubren permisos, persistencia y fotografías; US3-7 verifica contratos e integridad.

US1 y US2 comparten usuarios y mecanismo de sesión. Las validaciones del cliente no sustituyen las del servidor. Para registro, la contraseña admite 15–128 caracteres; para login, 1–128, sin modificarla en ninguno de los dos casos. El propietario de una publicación siempre procede de la sesión.

La referencia principal de las reglas de imágenes está en US3 del contexto del proyecto: al menos una fotografía es obligatorio y confirmado; los máximos, tamaños y formatos conservados en el backlog requieren ratificación específica. La publicación debe coordinar datos y archivos sin dejar un anuncio parcial; la estrategia técnica sigue pendiente.

## Verificación prevista

La suite actual `accounts properties` ejecuta 165 tests. Con Auth y Firestore
Emulator local pasan todos, incluidos los tests de carrera de email y de cambio
de contraseña. Las pruebas de US3-7 usan Firestore Emulator y mockean Azure Blob;
sus limitaciones de integración están en
el [README backend](../backend/README.md). Las pruebas heredadas de US1 y US2
también figuran en las secciones históricas; los comandos y el estado vigente
están en el README. La lista funcional está en el apartado 13 del contexto del
proyecto.

## 5. Reglas transversales y autenticación

La base documental actual utiliza autenticación mediante **sesiones y cookies**, no un contrato de JWT/Bearer. No cambiar el mecanismo silenciosamente.

- Un usuario tiene un identificador único, nombre, email normalizado, credenciales protegidas y rol.
- El email se normaliza eliminando espacios exteriores y convirtiéndolo a minúsculas.
- El email normalizado debe ser único, incluso ante registros simultáneos.
- La contraseña no se recorta, no se convierte a minúsculas, no se trunca ni se modifica.
- Nunca se devuelve una contraseña ni su hash en las respuestas.
- Los errores internos no deben revelar consultas SQL, trazas ni credenciales.
- Las cookies de sesión se han definido con `HttpOnly`, `Secure` y `SameSite=Lax`.
- El servidor identifica al usuario y determina su rol; el cliente no decide los permisos.
- Registro exitoso y login exitoso permiten acceder al inicio correspondiente al rol.
- La recarga de una página debe permitir recuperar el estado de autenticación consultando la sesión.
- Autenticación significa identificar al usuario. Autorización significa decidir qué puede hacer; la publicación exige autorización de Vendedor.

La base implementada usa PBKDF2-SHA256 de Django, sesiones en SQLite y una
vigencia local predeterminada de 14 dias. GET /api/auth/me define la consulta
del usuario actual; HTTPS y CSRF local estan documentados. La politica de
produccion y las condiciones entre dominios siguen pendientes.
La guia "Continuidad para implementar login (US2)" del README backend explica
los componentes y garantias que debe reutilizar el siguiente desarrollo.

## 9. Contratos HTTP definidos hasta ahora

Estos son los endpoints recogidos en el backlog. No confundirlos con rutas de navegación del frontend ni asumir que ya existen en el repositorio.

| Método y endpoint | Contenido | Acceso | Resultado esperado |
|---|---|---|---|
| `POST /api/auth/register` | `application/json`: `name`, `email`, `password`, `role` | Registro de persona sin cuenta | Crear la cuenta e iniciar sesión; `201 Created`. |
| `GET /api/auth/me` | Sin cuerpo; cookie de sesion | Consulta del usuario actual | Implementado: 200 con id/name/email/role; 401 sin sesion; 500 generico. |
| `POST /api/auth/login` | `application/json`: `email`, `password` | Comprobación de credenciales | Crear una sesión nueva y proporcionar identidad/rol. Código de éxito por cerrar. |
| `POST /api/inmuebles` | `multipart/form-data`: datos del anuncio y una o más fotografías | Bearer ID token Firebase válido y perfil `SELLER` | Publicar el inmueble asociado al uid verificado; `201 Created` con identificador. |

### Estados de respuesta

| Endpoint | Estados definidos y significado |
|---|---|
| Registro | `201`: cuenta y acceso completados; `400`: datos inválidos; `409`: email registrado; `500`: fallo interno. |
| Login | Éxito: código no fijado expresamente; `400`: datos inválidos; `401`: credenciales incorrectas; `500`: fallo al comprobarlas o crear sesión. |
| Publicación | `201`: publicación completada; `400`: datos o fotografías inválidos/ausentes; `401`: sesión ausente o inválida; `403`: rol sin permiso; `500`: fallo interno. |

**`200 OK` sería una propuesta razonable para el éxito del login, pero no se ha cerrado en el backlog.** No presentarlo como un acuerdo existente.

### Cuerpos y mensajes

Registro y GET /api/auth/me tienen contrato implementado y ejemplos en el README
backend. Los campos de entrada de login estan fijados, pero su cuerpo de exito
y codigo siguen pendientes. No hay un envoltorio comun acordado para toda la API.

Para publicación se han definido los campos funcionales, pero no sus nombres técnicos en `multipart/form-data`, la representación de los booleanos ni el nombre del campo o campos de archivos. No convertir los nombres españoles del formulario en un contrato de payload sin marcarlo como propuesta.

Las respuestas exitosas de autenticación deben permitir conocer el usuario y su rol; las de publicación deben proporcionar el identificador del anuncio. No se expone el hash ni la contraseña.

La autenticación vigente se realiza mediante Firebase ID token en `Authorization`;
la fila de autenticación histórica de registro/login no describe el contrato actual.

### Endpoints auxiliares pendientes

Por peticion del usuario se implemento GET /api/auth/me para consultar la sesion
al recargar: 200 con id, name, email y role; 401 sin sesion valida; 500 generico
ante fallo interno. Respuestas no-store, sin secretos ni redirecciones.
El frontend debe consumirlo para recuperar su estado autenticado.

Tampoco se han definido endpoints de logout, recuperación de contraseña, verificación de email, listado/detalle de anuncios, edición, borrado, swipes, candidatos, matches, perfiles o historial. Documentarlos únicamente como pendientes o alcance futuro cuando corresponda.

## 11. Modelo conceptual, sin diseño de implementación

La documentación puede describir estas relaciones sin imponer tablas, clases, colecciones o nombres definitivos:

- **Usuario:** identidad, nombre, email normalizado, credenciales protegidas y rol.
- **Sesión:** identifica a un usuario autenticado; soporta la consulta de su identidad y rol.
- **Inmueble/anuncio:** información y condiciones de alquiler, vendedor propietario y fecha de publicación.
- **Fotografía:** archivo o referencia almacenada, inmueble asociado y posición dentro del conjunto de imágenes.

Un vendedor puede tener varios inmuebles; cada inmueble pertenece a un vendedor. Cada anuncio publicado tiene al menos una fotografía, y las fotografías quedan asociadas al inmueble correspondiente.

No está resuelto si «inmueble» y «anuncio» serán entidades separadas. Se han utilizado de forma conjunta en el backlog inicial; no duplicarlas automáticamente en el diseño.

</details>

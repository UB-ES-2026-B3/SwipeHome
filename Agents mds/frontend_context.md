# Contexto frontend de SwipeHome

## Integración y verificación vigente US7.4 — 10 noviembre 2026

La autenticación vigente sigue siendo Firebase Auth con ID token Bearer y
revocación US6.
Los consumidores pueden usar los contratos documentados en el
[README backend](../backend/README.md) y [US4 backend](us4_backend.md).

BUYER: GET `/api/inmuebles/explorar` y POST
`/api/inmuebles/{id}/decision` con `{"decision":"LIKE"}` o PASS.
LIKE crea directamente match y aviso; no requiere aceptación del Vendedor ni
redirige a una pantalla US5.
BUYER y SELLER: GET `/api/notificaciones` devuelve sus propios avisos.
Ambos GET usan `items/next_cursor`, `limit` 20 por defecto, máximo 50.
Conservar el cursor al decidir sobre páginas previas para continuar sin saltos.
401 requiere recuperar el acceso; 500 permite reintentar sin cerrar la sesión.
Los avisos nuevos incluyen match, Comprador y vivienda; los históricos sin
match mantienen sus cuatro campos previos.

US4.10 corrigió la integración frontend: exploración con cursor, decisión por ID
y cuerpo `{decision}`; confirma solo respuestas coherentes con decisión/match.
Los controles soportan galería, gestos horizontales, teclado, retry y mensaje
vacío. `npm test` pasa 20 tests; lint y build terminan correctamente.

La comprobación de navegador usó Auth Emulator real y mock/interceptación de la
API: se revisaron datos/fotos, botones, teclado, gestos de puntero, retry tras
503, sesión expirada, recarga y viewport de 390 px/1280 px. No es persistencia
del navegador contra Firestore: el flujo de publicación, decisiones, avisos,
re-login y dos Compradores se verificó aparte en el test backend con Firestore
Emulator y Azure Blob mockeado. No se accedió a Firebase/Azure de producción.

US6.8: `ProfilePage` consulta/actualiza el perfil, cambia contraseña y permite
reintentar el logout cuando no se confirma. Si el servidor guardó el cambio pero
falló el intercambio de continuidad, el mensaje indica que hay que iniciar
sesión de nuevo. `npm test` pasa 22 tests; lint/build terminan con advertencias
de lint. Auth Emulator y API interceptada cubrieron en navegador validación,
errores, conservación del formulario, retry, recarga y logout. La API y la
revocación persistente se comprobaron aparte con emuladores en backend.

US6.9 verificó Buyer y Seller en navegador, cancelar/guardar, Enter, validación
de nombre/email y confirmación de contraseña, carga con botón deshabilitado y
sin petición repetida, persistencia de fixture al recargar, logout con cambios
pendientes, error y retry explícito desde el aviso. Tras 204, volver atrás y
abrir `/mi-perfil` llevan a la página pública; se pudo iniciar sesión de nuevo.
Auth Emulator fue real; las APIs se interceptaron. Viewports 390×844 y
1280×900 pasaron en navegador de escritorio emulado, no en hardware físico.

US7.4 corrige el consumo de `next_cursor` y permite leer la API desde ambos
roles. La pantalla muestra mensaje y fecha/hora local, estados diferenciados
de carga/vacío/error, reintento de fallo inicial y de actualización, y conserva
la lista si falla el refresco. La paginación descarta IDs repetidos. `npm test`
pasa 25 pruebas; lint/build terminan con advertencias existentes.

En navegador se utilizó Auth Emulator real y respuestas API interceptadas:
se comprobó ruta protegida sin sesión, datos/fecha, carga, vacío, fallo inicial
y retry, fallo de actualización conservando avisos y retry, paginación con
solapamiento sin duplicados y refresco con nuevos resultados. Viewports 1280×900
y 390×844 en navegador de escritorio emulado; no certifica hardware físico ni
persistencia Firestore de la UI. Persistencia backend del aviso SELLER tras
re-login sí se probó aparte en Auth/Firestore Emulator. En este árbol no existe
el productor de confirmación US5 para aviso BUYER; ese evento queda no verificado.

<details>
<summary>Historial anterior a US4 (conservado como referencia)</summary>

# Contexto frontend de SwipeHome

> Estado US6 (22 octubre 2026): se conserva Firebase Auth + Firestore.
> El contrato vigente de edición del perfil, contraseña y logout está en
> [us6_backend.md](us6_backend.md). Nombre/email actuales se leen de Auth;
> rol y relaciones permanecen en Firestore. Los apartados anteriores a esta
> adaptación que describen sesiones Django son históricos.

> ⚠️ Partes de este documento describen el login por sesiones y cookies, sustituido
> por Firebase Auth. Ver `infra_context.md` y `firebase_auth_migration.md`. Pendiente
> de actualizar.

> Estado US3-8 (1 noviembre 2026): `/publicar` está implementada y protegida
> para `SELLER`. La ruta usa token Firebase, validación de campos y firmas de
> imagen, selección/previsualización/retirada de fotos, envío multipart y
> recuperación del formulario ante errores. Ver el resultado integrado al final.

## Correcci?n de desarrollo HTTP y superusuarios (16 octubre 2026)

DJANGO_DEV=1 activa HTTP local con cookies sin Secure; sin esa variable se conserva
Secure. Debe definirse en la terminal del backend antes de arrancarlo; .env no se
carga autom?ticamente. El frontend obtiene CSRF antes de cada registro/login para
evitar reutilizar el token que Django rota. El modelo admite createsuperuser con
permisos Django independientes de BUYER/SELLER, mediante la migraci?n 0003.
Los comandos vigentes est?n en [README backend](../backend/README.md).


Fuente original: `contexto-proyecto-codex.md` de Descargas, revisada el 14 de octubre de 2026.
**Actualizado el 15 de octubre de 2026** con el stack, la implementación de US1 y el rediseño visual (rama `US1_Registro`).

## Stack frontend (confirmado a 15 oct 2026)

| Tecnología | Versión | Uso |
|---|---|---|
| React | 19.x | Librería de UI |
| Vite | 8.x | Bundler y servidor de desarrollo |
| react-router-dom | 7.x | Enrutamiento SPA |
| Oxlint | 1.x | Linter |

El frontend reside en `frontend/` en la raíz del repositorio. El backend Django corre en `http://127.0.0.1:8000` en modo HTTP local (`DJANGO_DEV=1`); Vite proxifica `/api/*` hacia él en desarrollo mediante `vite.config.js`.

### Comandos verificados

```bash
cd frontend
npm install        # instalar dependencias
npm run dev        # servidor de desarrollo (http://localhost:5173)
npm run build      # build de producción (dist/)
npm run lint       # oxlint
```

---

## Sistema de diseño — SwipeHome (establecido el 15 oct 2026)

**Todo el código visual nuevo debe seguir estas reglas sin desviarse.**

### Tipografía

- **Familia principal:** `Neue Haas Grotesk Display Pro` / `Neue Haas Grotesk Text Pro`
- **Fallbacks en orden:** `HelveticaNeue`, `Helvetica Neue`, `Helvetica`, `Arial`, `Inter`, `sans-serif`
- Declarada en `--font` en `:root` de `index.css`. Usar siempre `font-family: var(--font)`.
- Pesos utilizados: 400 (texto), 500 (énfasis leve), 700 (etiquetas), 900 (títulos/logotipo).
- Los títulos llevan `letter-spacing: -0.03em` a `-0.04em` y `font-weight: 900`.
- Las etiquetas de campo usan `text-transform: uppercase` + `letter-spacing: 0.08em` + `font-weight: 700`.

### Paleta de colores

| Variable CSS | Valor | Uso |
|---|---|---|
| `--c-red` | `#E8001C` | Acción principal, logotipo, precio, botón navbar |
| `--c-red-dark` | `#C0001A` | Hover del rojo |
| `--c-black` | `#111111` | Texto principal, botón "dark", fondo dark |
| `--c-white` | `#FFFFFF` | Fondo base, superficies |
| `--c-gray-50` | `#F5F5F5` | Fondo de inputs, fondo auth-page |
| `--c-gray-100` | `#EBEBEB` | Bordes por defecto, botón "ghost" |
| `--c-gray-200` | `#D4D4D4` | Tirador overlay, flecha select |
| `--c-gray-400` | `#9A9A9A` | Texto secundario, placeholders |
| `--c-gray-700` | `#444444` | Subtítulos, texto de apoyo |
| `--c-error` | `#E8001C` | Errores de campo (mismo que red) |

### Estética general

- **Minimalista:** fondos blancos o gris muy claro, sin gradientes en superficies principales.
- **Sin sombras decorativas excesivas:** solo `--shadow-card` en tarjetas y `--shadow-sm` en botones swipe.
- **Sin colores de fondo de marca en páginas completas:** las páginas usan `white` o `--c-gray-50`.
- **Bordes:** inputs con `1.5px solid --c-gray-100`; foco con `border-color: --c-black`.
- **Radios:** botones `100px` (píldora), cards `20px`, inputs `10px`.

### Logotipo (`components/Logo.jsx`)

- Nombre "SwipeHome" en `--c-red`, `font-weight: 900`, `text-transform: uppercase`.
- Debajo: dos SVG de "tejados" (triángulos con vértice hacia arriba = tejado invertido)
  - Tejado 1 (ancho): `polyline` de 140 px de ancho, altura 14 px.
  - Tejado 2 (corto): `polyline` de 84 px de ancho, altura 14 px.
  - Stroke `#E8001C`, `strokeWidth: 2.5`, `strokeLinecap: square`, `strokeLinejoin: miter`.
- Prop `size="sm"` reduce a 90/54 px de ancho y `strokeWidth: 2`.
- **No reemplazar el logotipo por un emoji ni por texto plano.**

### Botones

Siempre usar la clase base `.btn` más un modificador:

| Clase | Aspecto | Uso |
|---|---|---|
| `.btn--ghost` | Fondo `--c-gray-100`, texto negro | CTA secundario ("Empezar") |
| `.btn--dark` | Fondo `--c-black`, texto blanco | CTA principal ("Registrarse") |
| `.btn--red` | Fondo `--c-red`, texto blanco | Navbar "Iniciar sesión" |

- Todos los botones son píldoras: `border-radius: var(--r-btn)` = `100px`.
- Hover: `opacity: 0.88` + `translateY(-1px)`.
- Nunca gradientes en botones.

### Tarjetas de inmueble

- Clase `.deck-card` con 3 capas (`.deck-card--1/2/3`) rotadas para efecto baraja.
- Imágenes como gradientes suaves (`--c-gray` earth tones) mientras no haya fotos reales.
- Botones swipe: `.swipe-btn--pass` (gris) con icono X SVG, `.swipe-btn--like` (rojo) con corazón SVG correcto (`path` con curvas, no `♥` Unicode).
- El corazón se dibuja siempre con el SVG de `IconHeart` en `LandingPage.jsx` — **no usar ♥ ni ❤ como texto**.

### Overlay de registro

- Se abre sobre la landing con `position: fixed`, fondo semitransparente, panel desde abajo.
- Panel con `border-radius: 28px 28px 0 0` en móvil, `28px` en tablet+.
- Tirador visual (`.register-panel__handle`) gris en la parte superior.
- Cierra con Escape, clic en el fondo oscuro, o tras registro exitoso.
- **No redirigir a `/registro` para el flujo desde la landing** — usar el overlay.

### Navbar

- Fija en la parte superior, `backdrop-filter: blur(8px)`.
- Logo a la izquierda, botón "Iniciar sesión" (`.btn--red`) a la derecha.
- Sin menú hamburguesa. El inicio de SELLER incorpora el acceso «Publicar» de US3-8.

### Rutas

| Ruta | Componente | Notas |
|---|---|---|
| `/` | `LandingPage` | Página principal con baraja, CTA y overlay de registro |
| `/registro` | `RegisterPage` | Acceso directo por URL; mismo formulario sin overlay |
| `/login` | `LoginPage` | Firebase Auth; destino según rol |
| `/vendedor/inicio` | `SellerHome` | Protegida por rol SELLER |
| `/comprador/inicio` | `BuyerHome` | Protegida por rol BUYER |
| `/publicar` | `PropertyPublish` | Protegida por rol SELLER; Comprador vuelve a su inicio |

### Estructura de `frontend/src/`

```
api/
  auth.js             → registro, login, perfil, logout y cambios de cuenta Firebase
  properties.js       → POST multipart autenticado de anuncios
context/
  AuthContext.jsx     → AuthProvider, AuthContext (user, loading, setUser, clearUser)
hooks/
  useAuth.js          → hook useAuth()
components/
  Logo.jsx            → logotipo con tejados SVG
  FormField.jsx       → campo reutilizable con label, input/select y error accesible
  RegisterForm.jsx    → formulario de registro con validaciones US1; acepta prop onSuccess
pages/
  LandingPage.jsx     → /, con navbar, hero, baraja de tarjetas y overlay de registro
  RegisterPage.jsx    → /registro, acceso directo standalone
  SellerHome.jsx      → /vendedor/inicio y acceso «Publicar»
  BuyerHome.jsx       → /comprador/inicio sin opción «Publicar»
  PropertyPublish.jsx → /publicar, campos, fotos, validación, carga y resultado
  propertyForm.js     → reglas de campos, cantidad, tamaño y firma de imagen
App.jsx               → router con rutas protegidas (PrivateRoute)
main.jsx              → BrowserRouter + AuthProvider + App
index.css             → sistema de diseño completo (tokens, componentes, layout)
```

## Estado vigente de la integración con backend

La autenticación actual usa Firebase Auth en el cliente y el perfil del backend
en `GET /api/auth/me`. Las peticiones protegidas llevan el ID token Firebase en
`Authorization: Bearer …`; no se usan sesiones ni CSRF de Django. Los contratos,
comandos y resultados backend se mantienen en el
[README del backend](../backend/README.md).

La publicación utiliza `POST /api/inmuebles` con `FormData` y el token del
usuario autenticado. El navegador no fija `Content-Type`, para que el navegador
añada el límite multipart. `seller_uid` no se envía: el servidor lo deriva del
token verificado y exige rol `SELLER`. El contrato de campos, fotos, tamaños y
permisos vive en el README backend y la validación del producto en
[project_context.md](project_context.md).

## Referencias principales

[project_context.md](project_context.md) conserva las historias, criterios, validaciones de campos, reglas de fotografías y decisiones pendientes. [backend_context.md](backend_context.md) conserva los contratos HTTP y las reglas compartidas de autenticación. Este documento no define payloads ni rutas adicionales.

## Estado de implementación (rama US1_Registro)

| Tarea | Estado | Notas |
|---|---|---|
| US1-1: Formulario de registro y validaciones | ✅ Implementado | `RegisterForm.jsx` + `FormField.jsx` |
| US1-2: Conexión del formulario con la API | ✅ Implementado | `api/auth.js` + `RegisterForm.jsx` |
| US1-4B: Actualizar interfaz y redirigir según rol | ✅ Implementado | `AuthContext.jsx` + `App.jsx` |
| US1-3: API de registro (backend) | ✅ En backend (rama mergeada en dev) | `accounts/views.py` |
| US1-4A: Sesión tras registro (backend) | ✅ En backend | `accounts/views.py` (login automático) |
| US1-5: Persistencia de usuarios (backend) | ✅ En backend | `accounts/models.py` |
| US1-6: Verificación integrada | ✅ Verificada | 53 tests backend, build/lint y recorrido de ambos roles con recarga en navegador; lint con una advertencia no bloqueante |

## Responsabilidades del Sprint 0 (estado actualizado)

| Historia | Tareas de interfaz | Resultado esperado |
|---|---|---|
| US1 | US1-1 y US1-2 | Formulario de registro con nombre, email, contraseña y rol sin selección por defecto; validación, envío y tratamiento de respuestas. |
| US1 | US1-4B | Actualizar el estado de autenticación tras el registro, redirigir según rol y recuperar el estado al recargar. La redirección no se duplica en US1-2. |
| US2 | US2-1 y US2-2 | Formulario de login con email y contraseña, sin selección de rol; carga, errores y comunicación del éxito a la gestión de autenticación. |
| US2 | US2-5 | Estado autenticado, destino según rol y consulta de sesión al recargar, reutilizando el mecanismo de US1. |
| US3 | US3-1 y US3-2 | Acceso a «Publicar» para Vendedores, formulario y selección, previsualización y retirada de fotografías. |
| US3 | US3-3 | Envío autenticado, confirmación y tratamiento de errores conservando datos y fotografías para reintentar. |

Las tareas US1-6, US2-7 y US3-8 cubren la comprobación de los recorridos integrados correspondientes; la documentación del proyecto conserva su trazabilidad con los criterios generales.

## Interacción y validación

- Mostrar errores junto a los campos y evitar solicitudes inválidas y envíos repetidos mientras una solicitud está en curso.
- Normalizar el email eliminando espacios exteriores y convirtiéndolo a minúsculas; nunca recortar, alterar o truncar la contraseña.
- Aplicar la longitud de contraseña de la historia correspondiente: registro 15–128, login 1–128 caracteres.
- En login, usar `Introduce un email válido.` para email vacío o inválido y `Email o contraseña incorrectos.` para ambos tipos de credenciales incorrectas. Mantener `/login` ante fallos.
- En publicación, todos los campos definidos en US3 son obligatorios, incluida la elección Sí/No de alojamiento compartido, sin valor por defecto.
- Exigir al menos una fotografía válida. Sin imágenes válidas, mostrar `Añade al menos una fotografía válida.` y no enviar el formulario.
- Una imagen rechazada no elimina los datos ni las imágenes válidas. Conservar el orden de selección y los datos ante errores para permitir reintentos. No se ha acordado persistencia del formulario al cerrar el navegador ni un sistema de borradores.
- El menú de Comprador no muestra «Publicar». Los permisos y la identidad del propietario los comprueba el servidor.

La sesión está gestionada por Firebase Auth; el rol procede del perfil validado
por el backend. La ruta `/publicar` se protege también en el router, sin sustituir
la autorización obligatoria del endpoint.

## Resultado US3-8: recorrido integrado de publicación tras el merge con Azure

Verificación en navegador con Firebase Auth Emulator y respuestas de API
interceptadas; no se crearon anuncios en Firestore ni se subieron fotos a Azure.
El resumen por criterio es:

| CA | Prueba | Resultado |
|---|---|---|
| CA-01 | Login SELLER con Auth Emulator, opción «Publicar», entrada a `/publicar`; login BUYER, ausencia de la opción y navegación directa a la ruta. | Pasa |
| CA-02 | Formulario válido enviado como multipart autenticado, primero con una imagen y luego con varias; respuesta 201 interceptada y confirmación visible. | Pasa en interfaz; persistencia integrada no probada |
| CA-03 | Envío sin fotos y retirada de la última: aparece el error requerido y no se envía la solicitud. Tests backend cubren fotos y asociación usando Firestore Emulator y mock Azure. | Pasa |
| CA-04 | Envío con campos vacíos: errores visibles y cero solicitudes; la API también tiene pruebas de validación directa. | Pasa |
| CA-05 | Un GIF rechazado muestra el motivo sin retirar la imagen JPEG válida ni borrar campos; backend comprueba formatos y contenido. | Pasa |
| CA-06 | Carga bloquea nuevos envíos; errores 500 y conexión conservan campos/fotos y permiten reintentar. Tests backend comprueban compensación con Azure mock. | Pasa con mocks/interceptación |

`npm test` pasa 18 tests, incluidos los tests de validación, firmas JPEG/PNG/WebP
y construcción del multipart. `npm run build` pasa. `npm run lint` termina con
código 0 y avisos en `AuthContext.jsx`, `SellerHome.jsx` y `BuyerHome.jsx`. El
navegador interceptó el endpoint: no probó escritura Firestore ni subida real a
Azure Blob. Los tests backend usan Firestore Emulator y mockean Azure Blob; el
contrato real de persistencia en Azure no queda verificado en esta US.

Los límites de fotografías del backlog (1–10, hasta 5 MB, JPEG/PNG/WebP) se documentan con su estado de ratificación en US3. No imponer restricciones territoriales o longitudes de campos no acordadas.

## 10. Rutas del frontend

| Ruta u opción | Uso definido | Estado |
|---|---|---|
| `/registro` | Formulario de registro US1 | ✅ Implementado |
| `/login` | Pantalla de acceso; permanece abierta ante un login fallido. | ✅ Implementado; US2-7 verificada |
| `/vendedor/inicio` | Destino de un Vendedor; incluye acceso «Publicar». | ✅ Implementado |
| `/comprador/inicio` | Destino de un Comprador tras registro o login exitoso. | ✅ Placeholder implementado |
| Opción «Publicar» | Abre `/publicar` para un Vendedor autenticado. | ✅ Implementada y protegida en US3-8 |

### Resultado de verificación integrada US2-7 (18 octubre 2026)

Con frontend Vite y backend Django conectados a una SQLite temporal con cuentas
de prueba aisladas, se verificó en navegador el login real de SELLER y BUYER,
su destino correspondiente y la recuperación de sesión en ambas recargas mediante
`GET /api/auth/me`. Los campos vacíos y el email inválido mostraron errores y no
enviaron `POST /api/auth/login`. Un 401 mostró el mensaje acordado sin salir de
`/login`. Se interceptaron un 500 y un fallo de conexión: ambos conservaron la
ruta, informaron del problema y permitieron reintentar.

Durante una solicitud demorada, el botón mostró el estado de carga y quedó
deshabilitado. Dos eventos de envío casi simultáneos produjeron un solo POST;
tras el fallo del servidor y el fallo de conexión, el reintento autenticó al
Vendedor correctamente. No se usó la base SQLite de desarrollo.

## Decisiones que bloquean el cierre de la integración

El contrato local de login ya está integrado: acepta email y contraseña y
devuelve 200 en éxito; la ratificación formal del código de éxito en el backlog
sigue pendiente. El formulario `/publicar` y su contrato multipart están
implementados y documentados; siguen pendientes la ratificación por producto
de los campos/límites y las condiciones de deployment. Registro y consulta de
sesión ya tienen contrato. La lista completa de decisiones pendientes está en
el apartado 14 de [project_context.md](project_context.md).

Las pantallas de inicio son destinos necesarios; perfiles, historial, exploración, swipes, candidatos, matches, chat y gestión posterior de anuncios no se incorporan al Sprint 0 por estas referencias.

</details>

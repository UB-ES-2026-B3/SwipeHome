# Título de la PR

US6: implementar perfil propio, cambio de contraseña y logout seguro con Firebase

# Descripción

## Objetivo

Implementar US6.4, US6.5 y US6.7 sobre la arquitectura existente de Firebase Auth y Firestore: consultar y editar la cuenta autenticada, cambiar la contraseña y cerrar la sesión con revocación persistente en el servidor.

La identidad se obtiene exclusivamente del ID token verificado. Ambos roles, BUYER y SELLER, pueden gestionar su propio perfil.

## Cambios principales

- Consulta del perfil mediante `GET /api/auth/me`.
- Edición parcial mediante `PATCH/PUT /api/auth/me`, limitada a nombre y email. Se conservan los campos omitidos y se rechazan cambios de identificador, rol y campos desconocidos.
- Normalización del email antes de persistirlo. El email actual es válido y un email ocupado devuelve `409 Conflict`.
- Nombre y email se actualizan juntos mediante una única operación de Firebase Auth, que garantiza la unicidad del email.
- Cambio de contraseña mediante `POST /api/auth/me/password`, con comprobación de la contraseña actual, validación de la nueva y hashing gestionado por Firebase.
- Continuidad del cliente mediante intercambio inmediato de un `custom_token` tras cambiar email o contraseña.
- Logout mediante `POST /api/auth/logout`: devuelve `204`, es idempotente y persiste la revocación en Firestore. `GET` devuelve `405`.
- Verificación compartida de revocación en los endpoints protegidos, incluida la publicación de inmuebles.
- Respuestas sin contraseñas, hashes ni detalles internos y con `Cache-Control: no-store`.
- Adaptación del cliente para revocar en el servidor antes de limpiar el SDK y conservar la sesión ante errores de red o del servidor.
- Actualización de documentación, contextos de Agents y CI con pruebas del cliente y Firebase Auth Emulator.

## Persistencia e integridad

Firebase Auth es la fuente vigente del nombre y email editables. Firestore conserva el rol, la existencia del perfil y las relaciones; los campos históricos de nombre/email del documento son una instantánea del registro.

Las lecturas actuales pasan por `repository.get_user_profile`. Se reutilizan las cuentas existentes y se mantienen intactos UID, rol, inmuebles, decisiones y matches. Esta distribución evita escribir los mismos cambios en dos servicios sin una transacción común.

## Adaptación de los criterios originales

US6 se adapta expresamente a Firebase: la autenticación utiliza Bearer tokens y el identificador es `uid`. No se incorporan sesiones Django, cookies de sesión, ORM ni migraciones. La protección CSRF de Django no corresponde a este contrato; una petición con cookies solamente no puede revocar una sesión autenticada.

## Verificación local

- **90 tests backend pasan**, sin omisiones, ejecutando la suite completa dentro de Firebase Auth Emulator.
- Incluye una carrera real por el mismo email: un único ganador y ningún cambio parcial de nombre en la cuenta rechazada.
- Incluye cambio de contraseña con tokens reales del emulador, intercambio de continuidad y acceso autenticado posterior.
- Cubre inyección de identificador/rol, validación directa, logout idempotente, rechazo de tokens reutilizados y separación de cuentas y sesiones con distinto `auth_time`.
- **8 tests del cliente pasan**.
- `manage.py check`, `npm run build` y `git diff --check`: correctos.
- `npm run lint`: correcto, con la advertencia preexistente de Fast Refresh en `AuthContext.jsx`.

Las pruebas utilizan cuentas sintéticas del emulador. No se ha probado contra producción ni se ha ejecutado un despliegue o un workflow remoto.

## Configuración y límites relevantes

- Configurar `FIREBASE_WEB_API_KEY` en el backend con la Web API key del mismo proyecto para reautenticar al cambiar la contraseña. Las credenciales Admin deben permitir firmar custom tokens.
- El logout revoca el par `(uid, auth_time)` para esta API. Dos inicios de la misma cuenta en el mismo segundo comparten revocación; no proporciona separación exacta por dispositivo ni invalida directamente el refresh token del proveedor.
- No eliminar automáticamente los documentos de revocación: renovar el ID token conserva `auth_time`.
- Cambiar la contraseña puede invalidar otras sesiones Firebase. El cliente actual recibe una credencial de continuidad.
- Si el cambio se guarda y falla el intercambio de continuidad, el cliente devuelve `reauthentication_required: true` para pedir un nuevo inicio de sesión.
- Una pérdida de conexión tras aceptar Firebase una escritura puede producir un resultado ambiguo. No se promete rollback del proveedor en ese caso.
- Esta PR incorpora la integración de API necesaria; las pantallas de edición del perfil quedan fuera de su alcance.

Contrato y decisiones completos: [US6 backend](<Agents mds/us6_backend.md>).

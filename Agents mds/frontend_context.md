# Contexto frontend de SwipeHome

Fuente: `contexto-proyecto-codex.md` de Descargas, revisada el 14 de octubre de 2026. No existe frontend implementado, framework elegido ni comandos de ejecución verificados.

## Referencias principales

[project_context.md](project_context.md) conserva las historias, criterios, validaciones de campos, reglas de fotografías y decisiones pendientes. [backend_context.md](backend_context.md) conserva los contratos HTTP y las reglas compartidas de autenticación. Este documento no define payloads ni rutas adicionales.

## Responsabilidades del Sprint 0

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
- Exigir al menos una fotografía válida. Sin imágenes válidas, mostrar `Añade al menos una fotografía.` y no enviar el formulario.
- Una imagen rechazada no elimina los datos ni las imágenes válidas. Conservar el orden de selección y los datos ante errores para permitir reintentos. No se ha acordado persistencia del formulario al cerrar el navegador ni un sistema de borradores.
- El menú de Comprador no muestra «Publicar». Los permisos y la identidad del propietario los comprueba el servidor.

La sesión utiliza cookies y el rol procede del servidor. La recarga exige consultar el usuario actual, pero ese endpoint aún debe acordarse. No se adopta un token JWT/Bearer ni se inventa una estrategia de almacenamiento de credenciales en el navegador. Las condiciones de cookies entre dominios y para desarrollo local están pendientes.

Los límites de fotografías del backlog (1–10, hasta 5 MB, JPEG/PNG/WebP) se documentan con su estado de ratificación en US3. No imponer restricciones territoriales o longitudes de campos no acordadas.

## 10. Rutas del frontend

| Ruta u opción | Uso definido |
|---|---|
| `/login` | Pantalla de acceso; permanece abierta ante un login fallido. |
| `/vendedor/inicio` | Destino de un Vendedor tras registro o login exitoso. |
| `/comprador/inicio` | Destino de un Comprador tras registro o login exitoso. |
| Opción «Publicar» | Abre el formulario para un Vendedor autenticado; su URL no está fijada. |
| Formulario de registro | Necesario para US1; su URL no está fijada. |

Las dos pantallas de inicio son destinos de navegación requeridos. Su contenido completo y todas las funcionalidades futuras de cada rol no están incluidos automáticamente en el sprint.

## Decisiones que bloquean el cierre de la integración

Acordar los cuerpos de respuesta y errores, el código de éxito del login, la consulta de sesión, los nombres técnicos de campos multipart y archivos, las URLs de registro/publicación y las condiciones de cookies. La lista completa de decisiones pendientes está en el apartado 14 de [project_context.md](project_context.md).

Las pantallas de inicio son destinos necesarios; perfiles, historial, exploración, swipes, candidatos, matches, chat y gestión posterior de anuncios no se incorporan al Sprint 0 por estas referencias.

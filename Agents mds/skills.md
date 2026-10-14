# Pautas de trabajo en SwipeHome

Este archivo recoge pautas para agentes y colaboradores. No es un catálogo de skills instaladas, no instala herramientas y no sustituye un `AGENTS.md` ni las instrucciones explícitas del usuario.

## Lectura y alcance

1. Revisar las instrucciones aplicables, el estado de Git y los archivos existentes antes de modificar el proyecto.
2. Leer [project_context.md](project_context.md) para producto, Sprint 0, historias, reglas funcionales y decisiones pendientes.
3. Leer [backend_context.md](backend_context.md) o [frontend_context.md](frontend_context.md) según el área, y ambos para cambios de integración.
4. Distinguir requisitos esperados, comportamiento implementado, propuestas y decisiones pendientes. Documentar las discrepancias con evidencia.

## Documentación y desarrollo

- Mantener Vendedor/`SELLER` y Comprador/`BUYER`, aunque el producto sea de alquiler.
- Mantener las historias US1, US2 y US3 con criterios generales verificables y tareas técnicas propias de cada área; conservar la trazabilidad. No atribuir números de issues sin consultarlos.
- Usar la versión vigente de US3 con fotografías obligatorias: al menos una. Los límites restantes conservan su estado pendiente de ratificación.
- Reutilizar usuarios y sesiones entre registro y login; respetar cookies y la diferencia entre validación de contraseña de registro y login.
- No elegir tecnologías, algoritmos, contratos, URLs ni reglas de negocio para rellenar huecos documentales. Identificar una propuesta como propuesta.
- No incorporar funcionalidades futuras al Sprint 0 ni implementar código durante esta tarea documental.
- Mantener una referencia principal por tema y enlazarla desde el resto. Actualizar la documentación cuando aparezcan decisiones confirmadas o código que cambie el estado observado.
- No inventar comandos de instalación, ejecución, lint, pruebas o despliegue; acreditarlos en el repositorio antes de documentarlos.

## Git y registro local de esta tarea

La rama de trabajo es `docs/contexto-proyecto`. Se crean `features` y `release` si faltan, sin imponer todavía un flujo de integración entre ramas.

Registrar los cambios y las comprobaciones en `agent_changelog_local.md`, excluido de Git mediante `.gitignore`. No añadirlo forzadamente al índice. Conservar los archivos locales preexistentes ajenos a la tarea.

Por instrucción del usuario, esta tarea no realiza commits, push ni PR; los realizará el usuario. La creación de ramas locales no equivale a publicar cambios.

## Verificación

Para documentación: comprobar enlaces locales, reglas de exclusión, ramas, estado de Git y formato del diff. Para futuras implementaciones: usar los casos de verificación de cada US y ejecutar los controles que realmente existan. Los desarrolladores verifican su trabajo antes de QA; una historia se termina cuando sus tareas y criterios integrados están comprobados.

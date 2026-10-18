# Contexto de infraestructura (base de datos, despliegue y autenticación)

Responsable: Arnau (DevOps). Última actualización: 18 de octubre de 2026.

**Este documento es la referencia vigente para base de datos, despliegue y
autenticación.** Donde contradiga a `backend_context.md` o a
`project_context.md` en estos tres temas, manda este documento. El resto
(reglas de negocio, user stories, validaciones) sigue en los otros ficheros.

> **Si eres un agente de IA trabajando en este repositorio: lee la sección
> "Reglas para agentes" antes de tocar `backend/accounts/`.**

---

## 1. Decisiones de stack (acordadas por el equipo, 16 octubre 2026)

| Capa | Decisión |
|---|---|
| Frontend | React (Vite) |
| Backend | Python + Django |
| Base de datos | **Firestore** (NoSQL, Google Cloud) |
| Autenticación | **Firebase Auth** (en migración, ver sección 4) |
| Hosting backend | **Render**, plan gratuito |
| Hosting frontend | Firebase Hosting o Vercel (pendiente) |
| Docker | **No se usa.** Solo si el profesor lo exige. |
| Fotos de anuncios | Aplazado: Firebase Storage exige plan de pago. Usar URLs por ahora. |

Restricción dura del proyecto: **coste cero, sin tarjeta de crédito.**
Cualquier propuesta que requiera un servicio de pago queda descartada.

## 2. Proyecto de Firebase (ya creado)

- **Project ID:** `swipehome-a51d7`
- **Plan:** Spark (gratuito)
- **Firestore:** edición Standard, modo producción (reglas cerradas),
  región `europe-southwest1` (Madrid). La región es permanente.
- **Authentication:** proveedor Email/Password activado.
- **Cuenta de servicio:** la clave privada JSON la custodia Arnau y se
  configura **solo** como variable de entorno en Render
  (`FIREBASE_SERVICE_ACCOUNT_JSON`). **Nunca se sube al repositorio ni se
  comparte por chat.** Si alguien la necesita, que la pida a Arnau.
- El `firebaseConfig` del frontend (apiKey, authDomain, projectId...) **no es
  secreto**: está pensado para viajar en el bundle de JavaScript. Es distinto
  de la clave de la cuenta de servicio, que sí lo es.

Cuotas gratuitas relevantes (por proyecto y día): 50.000 lecturas,
20.000 escrituras, 20.000 borrados, 1 GiB almacenado.

## 3. Despliegue en Render

- Servicio web gratuito, construido desde GitHub. Sin Docker.
- Root directory `backend`, runtime Python 3.
- Build: `pip install -r requirements.txt`
- Start: `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT`

**Dos consecuencias importantes del plan gratuito:**

1. **El sistema de ficheros es efímero.** Se borra en cada redespliegue,
   reinicio **y cada vez que el servicio se duerme**, cosa que ocurre tras
   15 minutos sin tráfico. Por eso **SQLite no sirve en producción**: los
   usuarios registrados desaparecerían varias veces al día. No es un problema
   de configuración, es así por diseño en el plan gratuito.
2. **El servicio tarda ~1 minuto en despertar** tras estar dormido. Conviene
   abrir la app unos minutos antes de una demo o una revisión del profesor.

Variables de entorno en Render: `DJANGO_SECRET_KEY`, y más adelante
`FIREBASE_SERVICE_ACCOUNT_JSON` y `FIREBASE_PROJECT_ID`.
`RENDER_EXTERNAL_HOSTNAME` la inyecta Render automáticamente.

## 4. Autenticación: estado real y plan

### Situación actual (lo que hay en `dev`)

El registro y el login usan el **ORM de Django + sesiones + SQLite**:
modelo `accounts.User`, migraciones, `django.contrib.sessions`, cookies
`HttpOnly/Secure/SameSite=Lax` y CSRF. El frontend
(`frontend/src/api/auth.js`) ya consume ese contrato con
`credentials: 'include'` y cabecera `X-CSRFToken`.

Además, `backend/accounts/views.py` importa **`sqlite3` directamente** para
detectar emails duplicados (compara el texto del error
`UNIQUE constraint failed: accounts_user.email`). Eso ata el código a SQLite
en concreto, no solo al ORM.

### Por qué hay que cambiarlo

Por la sección 3.1: en Render, SQLite se borra varias veces al día. La base
de datos acordada por el equipo es Firestore, y **el ORM de Django no habla
con Firestore**. Por tanto el mecanismo de sesiones de Django (que guarda las
sesiones en una tabla de la base de datos) tampoco se sostiene.

### Plan acordado

Migrar registro y login a **Firebase Auth**:

- El **frontend** se autentica con el SDK de Firebase y obtiene un ID token.
- El frontend envía ese token en la cabecera `Authorization: Bearer <token>`.
- **Django** solo verifica el token con `firebase-admin` y lee/escribe el
  documento de perfil en la colección `users` de Firestore.
- Desaparecen: el modelo `User`, las migraciones, `django.contrib.sessions`,
  el CSRF de estos endpoints y el import de `sqlite3`.

**Lo que SÍ se conserva, sin tocar una línea:** `backend/accounts/validation.py`.
Está comprobado que no toca modelos ni base de datos: solo valida formato.
`validate_registration` y `validate_login` siguen siendo válidos tal cual, con
las mismas reglas (nombre 2–80, email normalizado y ≤254, contraseña 15–128 en
registro y 1–128 en login, rol `SELLER` o `BUYER`).

Lo que hay que rehacer: las vistas de `accounts/views.py`, sus tests, y la
parte de `frontend/src/api/auth.js` que gestiona cookies y CSRF.

### Nota honesta sobre el orden de las cosas

El contrato de sesiones/CSRF que hay ahora en `backend_context.md` **era**
correcto cuando se escribió. Esta migración lo sustituye de forma explícita,
no silenciosa. Si estás leyendo `backend_context.md` sección 5
("no cambiar el mecanismo silenciosamente"), este documento es ese cambio
anunciado.

## 5. Modelado en Firestore (orientación)

- Se piensa en **colecciones de documentos**, no en tablas:
  `users`, `listings`, `swipes`, `matches`.
- Se desnormaliza lo que la interfaz lee junto.
- Unicidad mediante IDs compuestos, p. ej. el id del swipe
  `{seekerId}_{listingId}`.
- **Punto débil conocido:** filtrar por varios campos a la vez (los filtros de
  perfil, las recomendaciones) exige un índice compuesto por cada combinación.
  A la escala de este proyecto, la solución acordada es traer un conjunto de
  candidatos con uno o dos filtros indexados y **terminar de filtrar en Python**.
- Cuidado con la cuota de 50.000 lecturas/día: un feed de swipes que relea
  todos los anuncios en cada swipe la agota rápido. Paginar.

## 6. Reglas para agentes (y para quien programe a mano)

1. **No añadas modelos nuevos al ORM de Django** ni migraciones. La base de
   datos destino es Firestore; todo modelo nuevo es trabajo que habrá que
   deshacer.
2. **No asumas SQLite** ni ninguna base de datos relacional. En concreto, no
   detectes errores comparando textos de excepciones de `sqlite3`.
3. **No construyas funcionalidad nueva encima de las sesiones de Django.**
   Si necesitas saber quién es el usuario, asume que vendrá de un token
   verificado, no de `request.user` con cookie de sesión.
4. **No toques `backend/accounts/validation.py`.** Se conserva tal cual.
5. **Todo acceso a Firestore irá en un único módulo** (`accounts/repository.py`
   o similar). Las vistas no llaman a Firestore directamente. Así, si algún día
   hay que cambiar de base de datos, se reescribe un fichero y no veinte.
6. **Nunca subas credenciales.** Ni claves de cuenta de servicio, ni ficheros
   `.env` con valores reales. Para añadir una variable nueva, documéntala en
   `backend/.env.example` con el valor vacío.
7. **Si tu tarea choca con este documento, pregunta a Arnau antes de
   implementar.** Es más barato que rehacerlo.

## 7. Estado de las ramas (18 octubre 2026)

- `dev` — rama de trabajo, al día.
- `main` — **vacía de código** (solo README y `Agents mds`). El revert de la
  PR #45 se mezcló aquí y eliminó todo el código, backend y frontend
  incluidos; el "reapply" (PR #48) solo llegó a `dev`. Nada se ha perdido:
  está todo en el historial.

  **Decisión: se deja así de momento**, hasta que el backend y el frontend
  estén cuadrados con Firebase. `main` solo recibirá trabajo terminado.

  > ⚠️ **AVISO IMPORTANTE para quien haga el merge a `main` en el futuro.**
  > Una PR normal de `dev` a `main` **no restaura el código**. Está
  > comprobado: git la da por buena ("Automatic merge went well"), sin
  > conflictos ni avisos, y `main` se queda con 6 ficheros, sin backend ni
  > frontend.
  >
  > El motivo: respecto al ancestro común (el merge de la PR #45, que sí
  > tenía todo el código), `main` borró los ficheros y `dev` acabó igual que
  > el ancestro tras revertir y reaplicar. Git interpreta que solo una rama
  > hizo un cambio —el borrado— y lo respeta.
  >
  > Para mergear de verdad hay que hacer **una** de estas dos cosas:
  > 1. Revertir el revert en `main` (`git revert` del commit `fdf29ff`) y
  >    mergear `dev` después, o
  > 2. Dejar `main` apuntando directamente al mismo commit que `dev`.
  >
  > Si alguien abre la PR sin esto, parecerá correcta y dejará `main` vacía.
- `deploy/render-bootstrap` — configuración de despliegue (gunicorn, endpoint
  `GET /api/health`, hosts de Render). No toca `accounts/`.

## 8. Pendiente

- Arreglar `main`.
- Primer despliegue verde en Render.
- Implementar la migración a Firebase Auth (sección 4).
- CI con GitHub Actions: ejecutar los tests en cada PR y proteger `main`.
- Hosting del frontend y configuración de CORS.

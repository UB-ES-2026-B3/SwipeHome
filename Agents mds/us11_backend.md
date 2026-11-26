# US11.3–US11.7 · Conversaciones entre usuarios con match

## Acceso

Todas las rutas usan el ID token de Firebase en `Authorization: Bearer <token>`.
Django verifica el token, la revocación US6 y el perfil BUYER o SELLER en el servidor.
El contrato Bearer prescinde de cookies y de CSRF de sesión. Todas las respuestas
US11 incluyen `Cache-Control: no-store`.

La pertenencia se comprueba contra el match y la titularidad del inmueble, siguiendo
US5. Solo un match CONFIRMED habilita la conversación. Abrir dos veces devuelve el
mismo recurso. Un cambio a PAUSED o CLOSED conserva el acceso de los participantes.
Enviar mensajes conserva los estados del match, el inmueble y la selección US9.
Consultar o abrir una conversación conserva su actividad y sus avisos.

## HTTP

| Método y ruta | Entrada | Éxito |
|---|---|---|
| POST `/api/matches/{match_id}/conversacion` | JSON `{}` | 201 nueva, 200 existente; devuelve la cabecera. |
| GET `/api/conversaciones` | `limit` entre 1 y 50 (20 por defecto), `cursor` opcional | 200 con `items` y `next_cursor`. |
| GET `/api/conversaciones/{id}` | Sin cuerpo | 200 con la cabecera. |
| GET `/api/conversaciones/{id}/mensajes` | `limit` entre 1 y 100 (50 por defecto), `before` > 0 o `after` ≥ 0 | 200 con `items`, `next_before` y `next_after`. |
| POST `/api/conversaciones/{id}/mensajes` | JSON con `client_message_id` UUID y `content` | 201 nuevo, 200 reintento idéntico; devuelve el mensaje. |

La cabecera contiene `id`, `match_id`, `other_user: {id,name,role}`,
`inmueble: {id,title,status}`, `last_message`, `created_at` y `updated_at`.
Los elementos del listado omiten `created_at`. `last_message` vale
`null` hasta el primer envío y después contiene `{id,sender_id,content,created_at}`.
`inmueble.status` refleja la disponibilidad de US9/10. El nombre del otro
participante se consulta con el mecanismo vigente de perfiles.

Los mensajes contienen `id`, `conversation_id`, `sequence`,
`sender: {id,name,role}`, `content` y `created_at`. El nombre del remitente
es el vigente cuando se envió. El servidor asigna secuencia y fecha UTC. Se
conserva el texto original, incluidos espacios y saltos de línea, con un límite
de 1 a 2000 caracteres Unicode y al menos un carácter que no sea espacio.
El consumidor debe presentar el contenido como texto. Las operaciones POST
requieren `Content-Type: application/json` y rechazan campos adicionales.

Las respuestas de error siguen `{"error":"mensaje seguro"}`: 400 para
JSON, contenido, parámetros o cursores inválidos, 401 para autenticación
ausente, inválida o revocada, 403 para rol no permitido según el decorador común,
404 para recurso inexistente o ajeno, 409 al abrir un match propio sin confirmar
o al reutilizar un UUID con otro contenido y 500 para fallos internos.
Un match ajeno devuelve 404 independientemente de su estado.

## Paginación

- El listado ordena por `updated_at DESC` e ID descendente como desempate.
  La creación es la actividad inicial. El cursor firmado está ligado al UID
  y guarda la posición de la última cabecera entregada. Cada página consulta
  el orden actual. Una conversación que recibe un mensaje puede subir por
  encima del cursor y quedar fuera de las páginas restantes. Volver a la
  primera página permite recuperar la actividad reciente. Al combinar
  páginas o refrescos, consolidar por ID y usar la última cabecera recibida.
- La página inicial de mensajes selecciona los más recientes. Con `before`
  se seleccionan los anteriores a esa secuencia. Con `after` se seleccionan
  novedades posteriores (usar 0 para empezar desde el primero). Se entrega
  cada página en orden ascendente de secuencia. La continuación de historial
  es el mínimo entregado y la de novedades el máximo entregado, si quedan
  más en la dirección correspondiente. Con ambas direcciones se devuelve 400.
  Para sondear tras agotar novedades se conserva la mayor secuencia recibida.
- Una consulta vacía devuelve `items: []` y continuaciones `null`.

## Firestore y avisos US7

`conversations/{match_id}` conserva referencias al match, inmueble y ambos
participantes, el contador y el resumen. `messages` es una subcolección
de cada conversación con ID determinista a partir de la conversación, el remitente y el UUID
normalizado. La creación usa el ID del match con precondición de documento
nuevo. Conversaciones de viviendas distintas tienen espacios de mensajes
separados. La secuencia empieza en 1 y el contador de la conversación
serializa envíos concurrentes.

El mensaje, el contador y resumen, y un aviso `MESSAGE` al otro participante
en `notifications` se guardan en el mismo commit. El aviso tiene
`conversation_id` en `GET /api/notificaciones` y un texto genérico.
Los reintentos de la transacción realizan exclusivamente operaciones Firestore.
Si se pierde una respuesta tras el commit, reutilizar el mismo UUID y texto
recupera el mensaje original y deja la fecha, secuencia y aviso intactos. La
persistencia vive en Firestore y es independiente de la sesión Firebase y del
proceso Django.

Los índices de `backend/firestore.indexes.json` cubren `buyer_uid` y
`seller_uid`, ambos con `updated_at DESC, __name__ DESC`. Las consultas de
mensajes usan el índice automático de `sequence`. El esquema es aditivo.
Las reglas de emulador ya deniegan accesos directos de clientes y el frontend
usa Auth y HTTP. Se conserva la configuración documentada de producción con
acceso de clientes cerrado. Comprobar los índices compuestos en el entorno
destino antes de habilitar la API. El emulador no certifica ese paso.

## Desarrollo y flujo con dos cuentas

Instalar y arrancar según [README del backend](../backend/README.md).
Para reproducir el flujo de dos cuentas con un proyecto demo, desde `backend/`
con Node 24, Java 21 y el entorno virtual del backend:

```powershell
npx.cmd --yes --package firebase-tools@15.34.1 firebase emulators:exec --project demo-swipehome-us4 --only auth,firestore --config tests/firebase.json ".venv\Scripts\python.exe -B manage.py test properties.test_conversations --verbosity 2"
```

La suite levanta Django en loopback, crea cuentas de prueba BUYER y SELLER,
crea anuncios y confirma los matches mediante HTTP. Para repetir manualmente
en un entorno de desarrollo con un match confirmado y los tokens de dos cuentas
distintas, usa este ejemplo PowerShell. Los tokens se obtienen con
`getIdToken()` en las respectivas sesiones Firebase del entorno.

```powershell
$api = 'http://127.0.0.1:8000/api'
$match = Read-Host 'Identificador del match CONFIRMED'
function Get-DevelopmentBearer($role) {
    $inputToken = Read-Host "ID token $role de desarrollo" -AsSecureString
    $credential = [pscredential]::new($role, $inputToken)
    @{ Authorization = 'Bearer ' + $credential.GetNetworkCredential().Password }
}
$buyer = Get-DevelopmentBearer 'BUYER'
$seller = Get-DevelopmentBearer 'SELLER'

$open = "$api/matches/$match/conversacion"
$chat = Invoke-RestMethod $open -Method Post -Headers $buyer -ContentType 'application/json' -Body '{}'
Invoke-RestMethod $open -Method Post -Headers $seller -ContentType 'application/json' -Body '{}'

$messages = "$api/conversaciones/$($chat.id)/mensajes"
$body = @{ client_message_id = [guid]::NewGuid().ToString(); content = 'Hola, podemos concertar una visita?' } | ConvertTo-Json
Invoke-RestMethod $messages -Method Post -Headers $buyer -ContentType 'application/json' -Body $body
Invoke-RestMethod $messages -Method Post -Headers $buyer -ContentType 'application/json' -Body $body
Invoke-RestMethod "${messages}?after=0&limit=10" -Headers $seller
Invoke-RestMethod "$api/conversaciones" -Headers $seller
Invoke-RestMethod "$api/notificaciones" -Headers $seller
```

## Verificación de la entrega

Pasaron 269 pruebas de `accounts properties qa.test_environment`, incluidas
las ocho de US11, con Auth y Firestore Standard emulados en loopback. Las carreras
usan hilos y barreras con solicitudes HTTP reales. Firestore rechaza un commit
con una precondición inválida y se comprueba que mensaje, resumen y aviso
conservan su estado anterior. Las pruebas también comprueban el acceso tras
logout y nuevo login, la denegación de acceso REST directo, la paginación y
la continuidad al pausar o retirar la vivienda.

En esta ejecución Firestore ya escuchaba en 8080 con `tests/firebase.json` y
el proyecto demo. Desde `backend/`, se reutilizó con este comando:

```powershell
$env:FIRESTORE_EMULATOR_HOST = '127.0.0.1:8080'
$env:FIREBASE_PROJECT_ID = 'demo-swipehome-us4'
npx.cmd --yes --package firebase-tools@15.34.1 firebase emulators:exec --project demo-swipehome-us4 --only auth --config tests/firebase.json ".venv\Scripts\python.exe -B manage.py test accounts properties qa.test_environment --verbosity 1"
```

También pasaron `manage.py check`, `makemigrations --check --dry-run`,
`pip check` y `git diff --check`. No hubo despliegue ni acceso a Firebase
de producción.


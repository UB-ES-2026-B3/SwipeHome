# Testing de SwipeHome

Los comandos de esta guía se ejecutan desde la **raíz del repositorio** en PowerShell de Windows. La [matriz de cobertura](TEST-COVERAGE.md) enlaza cada criterio con su evidencia.

## Niveles y ubicación

| Nivel | Qué comprueba | Dónde ampliar |
|---|---|---|
| Unitario y contrato aislado | Funciones, payloads, códigos de respuesta y manejo de errores con dependencias simuladas. | `frontend/tests/*.test.mjs` con Node y `backend/accounts/test_*.py`, `backend/properties/test_discovery.py` con Django. |
| Componente React | DOM, teclado, formularios, cargas, errores, botones y permisos. Vite monta los componentes reales en Chrome con Auth y API simulados. También se prueba la colaboración entre filtros y explorador. | `frontend/component/flows.spec.mjs`. |
| Integración | Django y sus clientes Firebase/Azure sobre persistencia local, más inyección de fallos concretos. Los casos de concurrencia existentes conservan peticiones simultáneas. | `backend/properties/test_firestore.py`, `test_selection.py`, `workflow_integration.py` y los casos etiquetados de `backend/accounts/test_profile.py`. |
| E2E | Usuarios independientes navegan por la aplicación React, autentican contra el emulador y escriben en Firestore a través de Django. Un recorrido de matches descarga una fotografía de Azurite. | `backend/properties/workflow_e2e.py`, `selection_e2e.py` y sus pasos en `frontend/e2e/workflows.mjs`, `selection.mjs`. |

Se reutiliza Chromium DevTools Protocol y el ejecutor `node:test`. Los componentes necesitan un DOM y eventos reales. El navegador del repositorio ya los proporciona con Vite y permite pruebas aisladas sin agregar dependencias. El ejecutor de Django distingue integración con la etiqueta `integration` y selecciona E2E explícitamente.

## Preparación desde cero

1. Instala Python 3.13, Node.js 24, Java 21 y Chrome, Chromium o Edge. Usa el entorno de trabajo del repositorio.
2. Desde la raíz, instala las dependencias de esta versión.

   ```powershell
   py -3.13 -m venv backend/.venv
   .\backend\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
   npm.cmd --prefix frontend ci
   npm.cmd install --global azurite@3.38.0
   npx.cmd --yes --package firebase-tools@15.34.1 firebase --version
   ```

3. Si el navegador está en otra carpeta, señala su ejecutable en esta terminal.

   ```powershell
   $env:SWIPEHOME_E2E_CHROME = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
   ```

4. Comprueba los servicios y las operaciones temporales.

   ```powershell
   .\scripts\test.cmd --suite prepare
   ```

El ejecutor reutiliza servicios activos y, si faltan, intenta iniciar las
instancias locales. Para mantener abiertos los servicios que inicie, usa
`--suite services` en una terminal y ejecuta las pruebas en otra. Ctrl+C
cierra los procesos iniciados por ese comando. Con un entorno previamente
iniciado, las instancias se conservan. La primera ejecución de Firebase Tools
puede necesitar descargar el emulador. Para trabajar sin conexión se puede
indicar la ruta de una instalación local 15.34.1 en `SWIPEHOME_FIREBASE_CLI`
apuntando a `firebase-tools/lib/bin/firebase.js`.

## Aislamiento y limpieza

El ejecutor establece `FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099`,
`FIRESTORE_EMULATOR_HOST=127.0.0.1:8080` y el proyecto
`demo-swipehome-us4` en los procesos de QA. Quita variables de credenciales
y proxies heredados. El cliente Firebase de los fixtures usa credenciales
anónimas de prueba y comprueba el proyecto y los endpoints del SDK.
`qa/environment.py` configura el cliente Azure del backend con la cuenta
pública de desarrollo `devstoreaccount1` y el contenedor `listings` en
`http://127.0.0.1:10000`. Las sondas de Auth, Firestore y Blob comprueban
lectura, escritura y borrado de sus propios registros.

Vite recibe el destino Django efímero en loopback y su propio SDK Auth con
el emulador habilitado. Cada usuario del navegador tiene un contexto nuevo.
El navegador resuelve solo hostnames de loopback. Las fuentes externas
pueden usar la fuente de reserva. Auth usa emails sintéticos y se eliminan
sus cuentas. Los fixtures borran documentos de colecciones con prefijo
único y los blobs nuevos pertenecientes al UID de prueba. Los datos de
otros usuarios y las instancias previamente abiertas se conservan.

## Comandos

Desde la raíz en PowerShell:

```powershell
.\scripts\test.cmd --suite all
.\scripts\test.cmd --suite unit
.\scripts\test.cmd --suite components
.\scripts\test.cmd --suite integration
.\scripts\test.cmd --suite e2e
.\scripts\test.cmd --story 8.6
.\scripts\test.cmd --suite components --story 5.9
.\scripts\test.cmd --suite integration --test properties.workflow_integration.WorkflowIntegrationTests.test_preferences_invalidate_cursor_and_survive_new_auth_session
.\scripts\test.cmd --suite components --test 'validación accesible'
.\scripts\test.cmd --suite e2e --test properties.workflow_e2e.WorkflowBrowserTests.test_two_homes_keep_independent_proposal_status --visual --debug
npm.cmd --prefix frontend run lint
npm.cmd --prefix frontend run build
```

`--story` admite 5.8, 5.9, 8.6, 9.7 y 9.8. Para E2E e integración
`--test` admite una ruta Django con puntos. Para componentes admite una
expresión regular del título. `--suite all` ejecuta unitarios, componentes,
integración y E2E y se detiene ante el primer nivel fallido. El código de
salida de un fallo se conserva. Los componentes funcionan sin emuladores.
`--visual` abre el navegador y `--debug` conserva capturas también al pasar.

## Resultados y depuración

La consola muestra nombres, totales y fallos de Django y Node. Para guardar
un informe de texto, desde la raíz:

```powershell
.\scripts\test.cmd --suite e2e 2>&1 | Tee-Object -FilePath .qa/e2e-console.log
$LASTEXITCODE
```

Después de `--suite prepare` existe `.qa/`. Los fallos del navegador
generan en esa carpeta capturas PNG y un JSON con la URL y el texto visible
de cada contexto. El nombre identifica el escenario y el número de contexto.
Este ejecutor usa DevTools y genera esos artefactos para revisar la UI.
El modo visual permite observar una reproducción del caso individual.
Cuando el ejecutor arranca un servicio, guarda su salida en `.qa/firebase-*.log`
o `.qa/azurite-*.log`. Los archivos locales quedan excluidos de Git.

## Cómo añadir una prueba

**Componente.** Dentro de `frontend/component/flows.spec.mjs`, usa el
montador compartido. El nombre empieza con la US para permitir filtrado.

```javascript
component('US 5.9 muestra el vacío del comprador', 'MatchesPage', {
  replies: { getMatches: [success(page([]))] },
}, async (tab) => {
  await tab.text('Aún no tienes matches confirmados.')
  assert.deepEqual(await calls(tab, 'getMatches'), [[{}]])
})
```

**Integración.** Añade a una clase basada en `EmulatorFixture` un caso
que compruebe HTTP y la persistencia. Los métodos de fixture crean hogares,
usuarios, matches, propuestas y publicaciones con fotos temporales.

```python
def test_like_appears_in_sellers_pending_candidates(self):
    decision_id = self.candidate("buyer", "PENDING")
    page = self.assert_status(self.request("GET", "/api/matches/candidatos", "seller"), 200)
    self.assertEqual(page["items"][0]["id"], decision_id)
    self.assertEqual(self.rows("swipes")[decision_id]["seller_decision"], "PENDING")
```

**E2E.** Registra el paso junto a los escenarios de `frontend/e2e/workflows.mjs`.
Incluye `pending` en el objeto que selecciona el escenario. Espera un estado
visible antes de actuar. El método Django de la segunda muestra prepara y
verifica Firestore.

```javascript
async function pending() {
  const buyer = await account('buyer')
  await buyer.text('Piso luminoso')
  await buyer.click('Me interesa')
  await buyer.text('Interés enviado al vendedor.')
}
```

```python
def test_browser_persists_pending_interest(self):
    self.browser("workflows", "pending")
    self.assertEqual([row["seller_decision"] for row in self.rows("swipes").values()], ["PENDING"])
```

Para incorporar otra US, añade sus pruebas donde corresponda, registra su
identificador y selectores en `STORIES` de `backend/qa/run.py` y enlaza los
criterios en la matriz. Reserva simulaciones para fallos o fronteras
directamente controladas por la prueba. Comprueba siempre el estado final
cuando una operación pueda persistir parcialmente.

## Problemas frecuentes

| Síntoma | Comprobación |
|---|---|
| 8080, 9099 o 10000 ocupado | `--suite prepare` verifica los servicios detectados. Si el puerto pertenece a otro programa, identifica el proceso antes de cambiarlo. La suite no mata procesos ajenos. |
| Azurite activo y error de contenedor | Comprueba que contiene `listings`. Si lo preparas manualmente, créalo con acceso de lectura pública a blobs para permitir que Chrome muestre las fotos de prueba. La sonda comprueba el SDK autenticado. |
| Firebase no está disponible | Verifica Java 21, el CLI 15.34.1, el caché del emulador y `backend/tests/firebase.json`. Revisa el log del servicio que corresponda. |
| Django o Vite inaccesibles | Revisa la primera excepción del recorrido. Cada prueba escoge puertos locales y los libera al terminar. Ejecuta desde la raíz y comprueba `backend/.venv` y `frontend/node_modules`. |
| Login falla | Comprueba el emulador Auth y el proyecto demo. Los usuarios de la prueba se crean en cada ejecución. La suite establece sus variables de Vite para evitar que un `.env.local` redirija las pruebas. |
| Chrome no inicia o DevTools se desconecta | Comprueba la ruta al ejecutable y los permisos del renderizador. En entornos limitados, el navegador puede requerir ejecución local autorizada fuera del sandbox. |
| Datos residuales tras interrumpir la prueba | Repite el caso. Los nombres de colección y las cuentas tienen IDs únicos. Para recuperar espacio, elimina solo los registros del identificador de la ejecución interrumpida en el emulador local. |
| PowerShell bloquea archivos `.ps1` | Ejecuta `scripts/test.cmd` desde PowerShell o CMD. El ejecutor no requiere cambiar la política de scripts. |

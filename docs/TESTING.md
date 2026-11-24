# Pruebas de QA de SwipeHome

Desde la raíz, con Python 3.13, Node 24, Java 21, Chrome o Edge y Azurite:

```powershell
py -3.13 -m venv backend/.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
npm.cmd --prefix frontend ci
npm.cmd install --global azurite@3.38.0
.\scripts\test.cmd --suite unit
.\scripts\test.cmd --suite components
.\scripts\test.cmd --suite integration
.\scripts\test.cmd --suite e2e
```

El ejecutor usa el proyecto demo `demo-swipehome-us4`, Auth y Firestore
en los puertos locales 9099 y 8080, y Azurite en el 10000. Inicia los
servicios que falten y cierra las instancias que inició. Las capturas y los
logs quedan en `.qa/`. Se puede fijar el ejecutable de Chromium mediante
`SWIPEHOME_E2E_CHROME` y seleccionar casos mediante `--test`. En integración
y E2E el selector es una ruta Django con puntos. En componentes se interpreta
como expresión regular del título.

## Regresiones observadas sobre dev

- **Actualización de candidaturas tras un conflicto.** El caso de componente
  «US 5.9 candidaturas paginadas y conflicto con actualización fallida» recibe
  HTTP 409 al decidir y HTTP 503 al recargar. La interfaz muestra «Hemos
  actualizado las listas». Node devuelve `AssertionError [ERR_ASSERTION]:
  No se debe anunciar una actualización que respondió 503` y `true !== false`.

- **Candidaturas tras cerrar una vivienda.**
  `properties.test_selection.SelectionIntegrationTests.test_acceptance_closes_only_its_home_and_notifies_affected_candidates_privately`
  espera que la página de candidaturas pendientes contenga únicamente la vivienda
  abierta. Con límite 1, la vivienda cerrada ocupa la primera página.
  Django la identifica con `AssertionError: Lists differ: ['home'] != ['open']`.
- **Validación accesible y envío de preferencias.**
  El caso de componente «US 8.6 validación accesible y restablecimiento fallido
  conservan los filtros» detecta que el campo con error devuelve `null` para
  `aria-describedby` en vez de `pref-max-price-error`. Dos llamadas consecutivas
  a `requestSubmit()` producen dos llamadas al guardado con el mismo payload.
  Node devuelve `AssertionError [ERR_ASSERTION]: Expected values to be strictly deep-equal`.

Los asserts permanecen activos para que la salida de la suite siga mostrando las
regresiones. Ejecuta los niveles por separado para obtener sus resultados aunque
un nivel anterior falle.

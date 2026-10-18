import { initializeApp } from 'firebase/app'
import { getAuth } from 'firebase/auth'

/**
 * Inicialización del SDK de Firebase en el navegador.
 *
 * El firebaseConfig NO es secreto: está pensado para viajar en el bundle.
 * Es distinto de la cuenta de servicio del backend, que sí lo es.
 * Los valores vienen de las variables VITE_FIREBASE_* (ver frontend/.env.example).
 */
const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
}

const missing = Object.entries(firebaseConfig)
  .filter(([, value]) => !value)
  .map(([key]) => key)
if (missing.length > 0) {
  throw new Error(
    `Faltan variables de entorno de Firebase (${missing.join(', ')}). ` +
      'Copia frontend/.env.example a frontend/.env.local y rellena los valores.',
  )
}

export const auth = getAuth(initializeApp(firebaseConfig))

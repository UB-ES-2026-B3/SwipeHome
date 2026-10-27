import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { changePassword, updateProfile } from '../api/auth'
import { FormField } from '../components/FormField'
import { Logo } from '../components/Logo'
import { useAuth } from '../hooks/useAuth'

const ROLE_LABELS = { BUYER: 'Comprador', SELLER: 'Vendedor' }

function validateProfile({ name, email }) {
  const errors = {}
  const trimmedName = name.trim()
  const trimmedEmail = email.trim().toLowerCase()

  if (!trimmedName) errors.name = 'El nombre es obligatorio.'
  else if (trimmedName.length < 2 || trimmedName.length > 80) {
    errors.name = 'El nombre debe tener entre 2 y 80 caracteres.'
  }
  if (!trimmedEmail) errors.email = 'El email es obligatorio.'
  else if (
    trimmedEmail.length > 254 ||
    /\s/.test(trimmedEmail) ||
    !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)
  ) {
    errors.email = 'Introduce un email válido.'
  }
  return errors
}

function validatePassword({ currentPassword, newPassword, confirmation }) {
  const errors = {}
  if (!currentPassword) errors.current_password = 'Introduce tu contraseña actual.'
  if (!newPassword) errors.new_password = 'Introduce una nueva contraseña.'
  else if (newPassword.length < 15 || newPassword.length > 128) {
    errors.new_password = 'La nueva contraseña debe tener entre 15 y 128 caracteres.'
  } else if (newPassword === currentPassword) {
    errors.new_password = 'La nueva contraseña debe ser diferente de la actual.'
  }
  if (!confirmation) errors.confirmation = 'Confirma la nueva contraseña.'
  else if (confirmation !== newPassword) {
    errors.confirmation = 'La confirmación debe coincidir con la nueva contraseña.'
  }
  return errors
}

function apiError(data, fallback) {
  return data?.error || fallback
}

export function ProfilePage() {
  const { user, loading, setUser, logout } = useAuth()
  const navigate = useNavigate()
  const [profile, setProfile] = useState({ name: user?.name || '', email: user?.email || '' })
  const [profileErrors, setProfileErrors] = useState({})
  const [profileMessage, setProfileMessage] = useState(null)
  const [savingProfile, setSavingProfile] = useState(false)
  const [passwords, setPasswords] = useState({
    currentPassword: '',
    newPassword: '',
    confirmation: '',
  })
  const [passwordErrors, setPasswordErrors] = useState({})
  const [passwordMessage, setPasswordMessage] = useState(null)
  const [savingPassword, setSavingPassword] = useState(false)

  if (loading) {
    return <div className="page-loading" aria-label="Cargando perfil"><div className="page-loading__spinner" /></div>
  }

  if (!user) return null

  function resetProfile() {
    setProfile({ name: user.name, email: user.email })
    setProfileErrors({})
    setProfileMessage(null)
  }

  async function handleProfileSubmit(event) {
    event.preventDefault()
    const errors = validateProfile(profile)
    setProfileErrors(errors)
    setProfileMessage(null)
    if (Object.keys(errors).length) return

    setSavingProfile(true)
    try {
      const result = await updateProfile({
        name: profile.name.trim(),
        email: profile.email.trim().toLowerCase(),
      })
      if (result.ok) {
        setUser(result.data)
        setProfile({ name: result.data.name, email: result.data.email })
        setProfileMessage('Cambios guardados correctamente.')
      } else if (result.status === 400) {
        setProfileErrors(result.data?.errors || {})
      } else if (result.status === 409) {
        setProfileErrors({ email: 'Este email ya está registrado.' })
      } else {
        setProfileMessage(apiError(result.data, 'No se pudieron guardar los cambios.'))
      }
    } catch {
      setProfileMessage('No hay conexión con el servidor. Inténtalo de nuevo.')
    } finally {
      setSavingProfile(false)
    }
  }

  async function handlePasswordSubmit(event) {
    event.preventDefault()
    const errors = validatePassword(passwords)
    setPasswordErrors(errors)
    setPasswordMessage(null)
    if (Object.keys(errors).length) return

    setSavingPassword(true)
    try {
      const result = await changePassword(passwords.currentPassword, passwords.newPassword)
      if (result.ok) {
        setPasswords({ currentPassword: '', newPassword: '', confirmation: '' })
        setPasswordMessage('Contraseña actualizada correctamente.')
      } else if (result.status === 400) {
        setPasswordErrors(result.data?.errors || {})
      } else {
        setPasswordMessage(apiError(result.data, 'No se pudo cambiar la contraseña.'))
      }
    } catch {
      setPasswordMessage('No hay conexión con el servidor. Inténtalo de nuevo.')
    } finally {
      setSavingPassword(false)
    }
  }

  return (
    <main className="profile-page">
      <header className="profile-page__header">
        <button type="button" className="profile-page__back" onClick={() => navigate(-1)}>
          Volver
        </button>
        <Logo size="sm" />
        <button type="button" className="profile-page__logout" onClick={logout}>
          Cerrar sesión
        </button>
      </header>

      <div className="profile-page__content">
        <h1>Mi perfil</h1>
        <p className="profile-page__subtitle">Consulta y actualiza tus datos de cuenta.</p>

        <section className="profile-card" aria-labelledby="account-data-title">
          <h2 id="account-data-title">Datos de la cuenta</h2>
          <form onSubmit={handleProfileSubmit} noValidate>
            {profileMessage && <div className="profile-message" role="status">{profileMessage}</div>}
            <FormField id="profile-name" label="Nombre" name="name" value={profile.name}
              onChange={(event) => setProfile({ ...profile, name: event.target.value })}
              error={profileErrors.name} maxLength={80} />
            <FormField id="profile-email" label="Email" type="email" name="email" value={profile.email}
              onChange={(event) => setProfile({ ...profile, email: event.target.value })}
              error={profileErrors.email} maxLength={254} />
            <div className="profile-role">
              <span className="form-field__label">Rol</span>
              <strong>{ROLE_LABELS[user.role]}</strong>
            </div>
            <div className="profile-actions">
              <button type="submit" className="btn btn--red" disabled={savingProfile}>
                {savingProfile ? 'Guardando…' : 'Guardar cambios'}
              </button>
              <button type="button" className="btn btn--ghost" onClick={resetProfile} disabled={savingProfile}>
                Cancelar
              </button>
            </div>
          </form>
        </section>

        <section className="profile-card" aria-labelledby="password-title">
          <h2 id="password-title">Cambiar contraseña</h2>
          <form onSubmit={handlePasswordSubmit} noValidate>
            {passwordMessage && <div className="profile-message" role="status">{passwordMessage}</div>}
            <FormField id="current-password" label="Contraseña actual" type="password"
              value={passwords.currentPassword}
              onChange={(event) => setPasswords({ ...passwords, currentPassword: event.target.value })}
              error={passwordErrors.current_password} autoComplete="current-password" />
            <FormField id="new-password" label="Nueva contraseña" type="password"
              value={passwords.newPassword}
              onChange={(event) => setPasswords({ ...passwords, newPassword: event.target.value })}
              error={passwordErrors.new_password} autoComplete="new-password" />
            <FormField id="password-confirmation" label="Confirmar nueva contraseña" type="password"
              value={passwords.confirmation}
              onChange={(event) => setPasswords({ ...passwords, confirmation: event.target.value })}
              error={passwordErrors.confirmation} autoComplete="new-password" />
            <button type="submit" className="btn btn--dark" disabled={savingPassword}>
              {savingPassword ? 'Actualizando…' : 'Cambiar contraseña'}
            </button>
          </form>
        </section>
      </div>
    </main>
  )
}

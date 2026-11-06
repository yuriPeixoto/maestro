import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Copy } from 'lucide-react'
import type { AccountChanges, AccountUser, UserRole } from '../../services/api'
import {
  useCreateAccount, useDeactivateAccount, useTemporaryPassword, useUpdateAccount,
} from '../../hooks/useUsers'
import Dialog from './Dialog'
import {
  apiErrorMessage, buttonDanger, buttonGhost, buttonPrimary, fieldClass, hintClass, labelClass,
} from './ui'

const ROLES: UserRole[] = ['viewer', 'operator', 'admin']
const COPIED_FEEDBACK_MS = 2_000

const displayName = (user: AccountUser) => user.full_name || user.username

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation()
  if (!error) return null
  return <p role="alert" className="mt-4 text-xs text-red-300">{apiErrorMessage(error, t)}</p>
}

function RoleSelect({ id, value, onChange }: { id: string; value: UserRole; onChange: (role: UserRole) => void }) {
  const { t } = useTranslation()
  return (
    <select id={id} className={fieldClass} value={value} onChange={(e) => onChange(e.target.value as UserRole)}>
      {ROLES.map((role) => <option key={role} value={role}>{t(`roles.${role}`)}</option>)}
    </select>
  )
}

// ── New account ──────────────────────────────────────────────────────────────

export function NewAccountDialog({ onClose, onCreated }: {
  onClose: () => void
  onCreated: (user: AccountUser, password: string) => void
}) {
  const { t } = useTranslation()
  const create = useCreateAccount()
  const [fullName, setFullName] = useState('')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<UserRole>('viewer')

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    create.mutate(
      { username: username.trim(), email: email.trim(), full_name: fullName.trim() || null, role },
      { onSuccess: (created) => onCreated(created, created.temporary_password ?? '') },
    )
  }

  return (
    <Dialog
      title={t('users.new.title')}
      onClose={onClose}
      dismissible={!create.isPending}
      footer={
        <>
          <button type="button" className={buttonGhost} onClick={onClose} disabled={create.isPending}>{t('users.cancel')}</button>
          <button type="submit" form="new-account" className={buttonPrimary} disabled={create.isPending}>
            {create.isPending ? t('users.working') : t('users.new.submit')}
          </button>
        </>
      }
    >
      <form id="new-account" onSubmit={submit} className="grid gap-3.5">
        <div>
          <label className={labelClass} htmlFor="n-name">{t('users.fields.fullName')}</label>
          <input id="n-name" className={fieldClass} value={fullName} onChange={(e) => setFullName(e.target.value)}
            placeholder={t('users.new.fullNamePlaceholder')} maxLength={120} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelClass} htmlFor="n-user">{t('users.fields.username')}</label>
            <input id="n-user" className={`${fieldClass} font-mono`} value={username} onChange={(e) => setUsername(e.target.value)}
              placeholder={t('users.new.usernamePlaceholder')} required maxLength={64} autoComplete="off" />
          </div>
          <div>
            <label className={labelClass} htmlFor="n-role">{t('users.fields.role')}</label>
            <RoleSelect id="n-role" value={role} onChange={setRole} />
          </div>
        </div>
        <div>
          <label className={labelClass} htmlFor="n-mail">{t('users.fields.email')}</label>
          <input id="n-mail" className={fieldClass} type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </div>
        <p className={`${hintClass} mt-0`}>{t('users.new.hint')}</p>
      </form>
      <ErrorLine error={create.error} />
    </Dialog>
  )
}

// ── Edit ─────────────────────────────────────────────────────────────────────

export function EditAccountDialog({ user, onClose }: { user: AccountUser; onClose: () => void }) {
  const { t } = useTranslation()
  const update = useUpdateAccount()
  const [fullName, setFullName] = useState(user.full_name ?? '')
  const [email, setEmail] = useState(user.email)
  const [role, setRole] = useState<UserRole>(user.role)

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    const changes: AccountChanges = {}
    if (fullName.trim() !== (user.full_name ?? '')) changes.full_name = fullName.trim()
    if (email.trim() !== user.email) changes.email = email.trim()
    if (role !== user.role) changes.role = role
    if (Object.keys(changes).length === 0) {
      onClose()
      return
    }
    update.mutate({ id: user.id, changes }, { onSuccess: onClose })
  }

  return (
    <Dialog
      title={t('users.edit.title')}
      subtitle={t('users.edit.subtitle', { username: user.username })}
      onClose={onClose}
      dismissible={!update.isPending}
      footer={
        <>
          <button type="button" className={buttonGhost} onClick={onClose} disabled={update.isPending}>{t('users.cancel')}</button>
          <button type="submit" form="edit-account" className={buttonPrimary} disabled={update.isPending}>
            {update.isPending ? t('users.working') : t('users.save')}
          </button>
        </>
      }
    >
      <form id="edit-account" onSubmit={submit} className="grid gap-3.5">
        <div>
          <label className={labelClass} htmlFor="e-name">{t('users.fields.fullName')}</label>
          <input id="e-name" className={fieldClass} value={fullName} onChange={(e) => setFullName(e.target.value)} maxLength={120} />
        </div>
        <div>
          <label className={labelClass} htmlFor="e-mail">{t('users.fields.email')}</label>
          <input id="e-mail" className={fieldClass} type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </div>
        <div>
          <label className={labelClass} htmlFor="e-role">{t('users.fields.role')}</label>
          <RoleSelect id="e-role" value={role} onChange={setRole} />
          <p className={hintClass}>{t('users.edit.roleHint')}</p>
        </div>
      </form>
      <ErrorLine error={update.error} />
    </Dialog>
  )
}

// ── Deactivate ───────────────────────────────────────────────────────────────

export function DeactivateDialog({ user, onClose }: { user: AccountUser; onClose: () => void }) {
  const { t } = useTranslation()
  const deactivate = useDeactivateAccount()
  return (
    <Dialog
      title={t('users.deactivate.title', { name: displayName(user) })}
      onClose={onClose}
      dismissible={!deactivate.isPending}
      footer={
        <>
          <button type="button" className={buttonGhost} onClick={onClose} disabled={deactivate.isPending}>{t('users.cancel')}</button>
          <button type="button" className={buttonDanger} disabled={deactivate.isPending}
            onClick={() => deactivate.mutate(user.id, { onSuccess: onClose })}>
            {deactivate.isPending ? t('users.working') : t('users.deactivate.submit')}
          </button>
        </>
      }
    >
      <p className="text-[13px] text-slate-300 leading-relaxed">{t('users.deactivate.body')}</p>
      <ErrorLine error={deactivate.error} />
    </Dialog>
  )
}

// ── Temporary password ───────────────────────────────────────────────────────

export function TemporaryPasswordDialog({ user, onClose, onGenerated }: {
  user: AccountUser
  onClose: () => void
  onGenerated: (password: string) => void
}) {
  const { t } = useTranslation()
  const generate = useTemporaryPassword()
  const effects = ['oldStops', 'sessionEnds', 'lockoutCleared', 'mustChange'] as const
  return (
    <Dialog
      title={t('users.temporary.title', { name: displayName(user) })}
      onClose={onClose}
      dismissible={!generate.isPending}
      footer={
        <>
          <button type="button" className={buttonGhost} onClick={onClose} disabled={generate.isPending}>{t('users.cancel')}</button>
          <button type="button" className={buttonPrimary} disabled={generate.isPending}
            onClick={() => generate.mutate(user.id, { onSuccess: onGenerated })}>
            {generate.isPending ? t('users.working') : t('users.temporary.submit')}
          </button>
        </>
      }
    >
      <ul className="pl-4 list-disc text-[13px] text-slate-300 leading-7">
        {effects.map((effect) => <li key={effect}>{t(`users.temporary.${effect}`)}</li>)}
      </ul>
      <ErrorLine error={generate.error} />
    </Dialog>
  )
}

/** The password, once: closing the dialog is the last chance to see it. */
export function PasswordShownDialog({ title, password, onClose }: { title: string; password: string; onClose: () => void }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  const copy = () => {
    navigator.clipboard.writeText(password).then(
      () => {
        setCopied(true)
        window.setTimeout(() => setCopied(false), COPIED_FEEDBACK_MS)
      },
      () => setCopied(false), // no clipboard (plain HTTP): the password is still on screen to copy by hand
    )
  }

  return (
    <Dialog
      title={title}
      onClose={onClose}
      dismissible={false}
      footer={<button type="button" className={buttonPrimary} onClick={onClose}>{t('users.password.done')}</button>}
    >
      <div className="flex items-center gap-2 rounded-xl border border-violet-400/40 bg-brand-dark/90 px-3.5 py-3">
        <span className="flex-1 font-mono text-xl tracking-wider text-slate-100 select-all break-all" aria-label={t('users.password.label')}>
          {password}
        </span>
        <button type="button" className={buttonGhost} onClick={copy}>
          {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
          {copied ? t('users.password.copied') : t('users.password.copy')}
        </button>
      </div>
      <p className={hintClass} aria-live="polite">{t('users.password.hint')}</p>
    </Dialog>
  )
}

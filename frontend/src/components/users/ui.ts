import type { TFunction } from 'i18next'

export const fieldClass =
  'w-full bg-brand-dark/80 border border-white/10 rounded-lg py-2 px-3 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-violet-400/70 focus:ring-2 focus:ring-brand-purple/25 transition-colors'

export const labelClass = 'block mb-1.5 text-[10px] text-slate-400 uppercase tracking-widest font-bold'

export const hintClass = 'mt-1.5 text-xs text-slate-400 leading-relaxed'

const buttonBase =
  'inline-flex items-center justify-center gap-2 min-h-9 px-3.5 py-2 rounded-lg text-[13px] font-semibold transition-colors disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-400'

export const buttonPrimary = `${buttonBase} bg-brand-purple text-white hover:bg-violet-700 shadow-[0_0_20px_rgba(124,58,237,0.3)]`
export const buttonGhost = `${buttonBase} border border-white/10 text-slate-300 hover:bg-white/5`
export const buttonDanger = `${buttonBase} border border-red-400/40 text-red-300 hover:bg-red-400/10`

export const iconButton =
  'inline-flex items-center justify-center w-9 h-9 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-white/5 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet-400'

// The API answers in English; these are the refusals a person can act on.
const KNOWN_ERRORS: [RegExp, string][] = [
  [/^Username already exists/, 'users.errors.usernameTaken'],
  [/^Email already in use/, 'users.errors.emailTaken'],
  [/^There must be at least one active admin/, 'users.errors.lastAdmin'],
  [/^Reactivate the account first/, 'users.errors.reactivateFirst'],
  [/^You cannot /, 'users.errors.notYourself'],
]

const FORBIDDEN = 403
const UNPROCESSABLE = 422

export function apiErrorMessage(error: unknown, t: TFunction): string {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })?.response
  if (response?.status === FORBIDDEN) return t('users.errors.forbidden')
  if (response?.status === UNPROCESSABLE) return t('users.errors.invalid')
  const detail = typeof response?.data?.detail === 'string' ? response.data.detail : ''
  const known = KNOWN_ERRORS.find(([pattern]) => pattern.test(detail))
  return known ? t(known[1]) : t('users.errors.generic')
}

import type { ServerName as Name } from '../../hooks/useServerName'

/**
 * A server's name as a person reads it (nickname, label, hostname: useServerName), with the
 * hostname small underneath when they differ. `nameClass` styles the main line.
 */
export default function ServerName({ name, nameClass = 'font-semibold text-slate-100', inline = false }: {
  name: Name
  nameClass?: string
  /** The hostname beside the name instead of under it, for one-line headers. */
  inline?: boolean
}) {
  return (
    <>
      <span className={nameClass}>{name.display}</span>
      {name.renamed && (
        <span className={`${inline ? 'ml-2' : 'block mt-0.5'} text-[11px] font-normal text-slate-400 font-mono`}>{name.hostname}</span>
      )}
    </>
  )
}

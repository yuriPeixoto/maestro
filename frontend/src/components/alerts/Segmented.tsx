interface Option<T extends string> {
  value: T
  label: string
}

/** A row of toggle buttons where exactly one is pressed. */
export default function Segmented<T extends string>({
  label, options, value, onChange,
}: {
  label: string
  options: Option<T>[]
  value: T
  onChange: (value: T) => void
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex border border-white/10 rounded-[10px] overflow-hidden">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
          className={`min-h-9 px-3.5 py-2 text-[13px] font-semibold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-violet-400 ${
            option.value === value ? 'bg-violet-500/20 text-violet-100' : 'text-slate-400 hover:text-slate-200 hover:bg-white/5'
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

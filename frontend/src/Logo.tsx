/** The VGVault mark: SNES face buttons on a cartridge tile (same art as public/favicon.svg). */
export default function Logo({ className = 'logo' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 64 64" aria-hidden="true">
      <rect x="2" y="2" width="60" height="60" rx="14" fill="#212328" />
      <rect x="2.75" y="2.75" width="58.5" height="58.5" rx="13.25" fill="none" stroke="#32353E" strokeWidth="1.5" />
      <circle cx="32" cy="17" r="8.5" fill="#4F43AE" />
      <circle cx="17" cy="32" r="8.5" fill="#4F43AE" />
      <circle cx="47" cy="32" r="8.5" fill="#9E86E9" />
      <circle cx="32" cy="47" r="8.5" fill="#9E86E9" />
      <circle cx="50.5" cy="13.5" r="3" fill="#E63946" />
    </svg>
  )
}

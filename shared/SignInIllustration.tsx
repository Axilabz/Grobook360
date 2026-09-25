// Sign-in background illustration, recreated as inline SVG (line-art,
// business/accounting theme) instead of the 3 multi-megabyte PNG files
// Layout.tsx previously loaded per breakpoint
// (public/{Mobile,Tablet,Web}SignInBackGroundImage.png). One responsive
// SVG replaces all three — same illustration theme (accounting desk
// scene on the left, business-insights/inventory scene on the right,
// scattered doodle decorations), no image file dependency, near-zero
// payload.
import React from 'react';

const SignInIllustration: React.FC<{ className?: string }> = ({ className }) => (
  <svg
    viewBox="0 0 1200 700"
    className={className}
    preserveAspectRatio="xMidYMid meet"
    xmlns="http://www.w3.org/2000/svg"
  >
    <g stroke="#1F2937" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" opacity="0.85">
      {/* ---------- LEFT CLUSTER: Accounting desk scene ---------- */}

      {/* Invoice card (tilted) */}
      <g transform="translate(40,40) rotate(-8)">
        <rect x="0" y="0" width="110" height="80" rx="8" fill="#DCEBFF" stroke="#1F2937" />
        <line x1="16" y1="20" x2="80" y2="20" stroke="#60A5FA" strokeWidth="4" />
        <line x1="16" y1="36" x2="94" y2="36" />
        <line x1="16" y1="50" x2="70" y2="50" />
        <circle cx="88" cy="62" r="12" fill="#fff" stroke="#0066FF" />
        <path d="M82 62 l4 5 l9 -11" stroke="#0066FF" strokeWidth="3" />
      </g>

      {/* Coins */}
      <g transform="translate(150,55)">
        <circle cx="0" cy="20" r="22" fill="#EFF6FF" />
        <circle cx="26" cy="10" r="22" fill="#DCEBFF" />
        <text x="26" y="17" textAnchor="middle" fontSize="20" fontWeight="700" fill="#0066FF" stroke="none">$</text>
      </g>

      {/* Calendar */}
      <g transform="translate(230,30)">
        <rect x="0" y="10" width="60" height="52" rx="6" fill="#fff" stroke="#1F2937" />
        <line x1="0" y1="26" x2="60" y2="26" />
        <line x1="14" y1="0" x2="14" y2="16" />
        <line x1="46" y1="0" x2="46" y2="16" />
        <circle cx="16" cy="40" r="3" fill="#1F2937" stroke="none" />
        <circle cx="30" cy="40" r="3" fill="#1F2937" stroke="none" />
        <circle cx="44" cy="40" r="3" fill="#1F2937" stroke="none" />
      </g>

      {/* Scattered decorations top-left */}
      <circle cx="320" cy="55" r="7" fill="#8AC0FF" stroke="none" />
      <path d="M280 15 h30" strokeDasharray="4 5" />
      <path d="M20 100 q10 -10 20 0" />
      <circle cx="300" cy="95" r="10" />
      <path d="M296 95 l3 4 l7 -8" stroke="#0066FF" />

      {/* Person at desk with laptop */}
      <g transform="translate(50,150)">
        {/* desk */}
        <line x1="0" y1="110" x2="150" y2="110" strokeWidth="3" />
        <line x1="14" y1="110" x2="14" y2="150" />
        <line x1="136" y1="110" x2="136" y2="150" />
        {/* laptop */}
        <rect x="55" y="86" width="50" height="30" rx="3" fill="#fff" />
        <rect x="50" y="112" width="60" height="6" rx="2" fill="#DCEBFF" />
        {/* chair */}
        <path d="M20 165 v-30 q0 -8 8 -8 h4" />
        {/* person */}
        <circle cx="70" cy="45" r="16" fill="#fff" />
        <path d="M70 61 v20 q0 10 -14 14 v20" />
        <path d="M70 81 q16 4 16 14 v20" />
        <path d="M56 95 q-14 4 -18 20" />
        <path d="M86 95 q10 -4 16 -6" />
      </g>

      <text x="60" y="335" fontSize="19" fontStyle="italic" fontWeight="600" fill="#1F2937" stroke="none" fontFamily="Georgia, serif">
        ACCOUNTING
      </text>

      {/* Barcode */}
      <g transform="translate(10,220)">
        <rect x="0" y="0" width="100" height="60" rx="4" fill="#fff" stroke="#1F2937" />
        {[4, 10, 14, 22, 28, 34, 40, 48, 54, 60, 66, 74, 80, 88].map((x, i) => (
          <line key={x} x1={x} y1="8" x2={x} y2="42" strokeWidth={i % 3 === 0 ? 3 : 1.5} />
        ))}
        <text x="50" y="54" textAnchor="middle" fontSize="9" letterSpacing="1" fill="#1F2937" stroke="none">H055500N</text>
      </g>

      {/* Forklift / inventory icon */}
      <g transform="translate(0,340)">
        <rect x="30" y="0" width="16" height="16" fill="#DCEBFF" stroke="#1F2937" />
        <rect x="30" y="18" width="16" height="16" fill="#DCEBFF" stroke="#1F2937" />
        <path d="M0 40 h30 v-14 h10 l8 14" />
        <circle cx="10" cy="46" r="6" />
        <circle cx="38" cy="46" r="6" />
      </g>

      <path d="M120 380 h20" strokeDasharray="4 5" />
      <path d="M0 60 l10 10 m-10 0 l10 -10" transform="translate(340,150)" />

      {/* ---------- RIGHT CLUSTER: Business insights scene ---------- */}

      {/* Bar chart */}
      <g transform="translate(940,90)">
        <path d="M0 90 L60 20" strokeDasharray="4 4" />
        <rect x="0" y="60" width="16" height="30" fill="#DCEBFF" stroke="#1F2937" />
        <rect x="22" y="40" width="16" height="50" fill="#8AC0FF" stroke="#1F2937" />
        <rect x="44" y="20" width="16" height="70" fill="#DCEBFF" stroke="#1F2937" />
      </g>
      <text x="930" y="215" fontSize="18" fontWeight="700" fill="#1F2937" stroke="none" fontFamily="Georgia, serif">BUSINESS INSIGHTS</text>
      <g transform="translate(895,195)">
        <circle cx="0" cy="0" r="11" />
        <path d="M-5 0 l3 4 l8 -9" stroke="#0066FF" />
      </g>

      {/* Open book / ledger */}
      <g transform="translate(850,260)">
        <path d="M0 10 q40 -14 80 0 v70 q-40 -14 -80 0 z" fill="#fff" stroke="#1F2937" />
        <path d="M40 10 v70" />
        <line x1="10" y1="26" x2="34" y2="20" />
        <line x1="10" y1="40" x2="34" y2="34" />
        <line x1="46" y1="20" x2="70" y2="26" />
        <line x1="46" y1="34" x2="70" y2="40" />
        <path d="M64 6 v20 l6 -6 l6 6 v-20 z" fill="#0066FF" stroke="none" />
      </g>

      {/* Monitor with pie chart + person pointing */}
      <g transform="translate(970,250)">
        <rect x="0" y="0" width="120" height="86" rx="6" fill="#fff" stroke="#1F2937" />
        <rect x="50" y="86" width="20" height="14" fill="#fff" stroke="#1F2937" />
        <line x1="30" y1="100" x2="90" y2="100" strokeWidth="3" />
        <circle cx="35" cy="40" r="22" fill="#DCEBFF" stroke="#1F2937" />
        <path d="M35 18 A22 22 0 0 1 57 40 L35 40 Z" fill="#0066FF" stroke="none" />
        <path d="M35 18 A22 22 0 0 0 15 52 L35 40 Z" fill="#8AC0FF" stroke="none" />
        <line x1="72" y1="20" x2="104" y2="20" />
        <line x1="72" y1="32" x2="104" y2="32" />
        <line x1="72" y1="44" x2="92" y2="44" />

        {/* standing person pointing at screen */}
        <g transform="translate(120,10)">
          <circle cx="14" cy="14" r="13" fill="#fff" stroke="#1F2937" />
          <path d="M14 27 v40 q0 8 -10 10 v20" />
          <path d="M14 27 q14 4 14 16 v10" />
          <path d="M0 45 q-14 -2 -20 -18" />
          <path d="M28 40 q10 -4 16 -2" />
        </g>
      </g>

      {/* Calculator */}
      <g transform="translate(945,400)">
        <rect x="0" y="0" width="70" height="90" rx="6" fill="#fff" stroke="#1F2937" />
        <rect x="10" y="10" width="50" height="18" rx="3" fill="#DCEBFF" />
        {[0, 1, 2, 3].map((row) =>
          [0, 1, 2].map((col) => (
            <rect key={`${row}-${col}`} x={10 + col * 18} y={38 + row * 13} width="12" height="9" rx="2" fill="#EFF6FF" stroke="#1F2937" strokeWidth="1" />
          ))
        )}
      </g>

      {/* Scattered decorations right */}
      <circle cx="820" cy="400" r="8" fill="#8AC0FF" stroke="none" />
      <rect x="895" y="360" width="14" height="14" fill="#C4B5FD" stroke="none" transform="rotate(20 902 367)" />
      <path d="M780 430 l18 18 m0 -18 l-18 18" />
      <path d="M760 380 h26" strokeDasharray="4 5" />
      <circle cx="1150" cy="430" r="6" fill="#0066FF" stroke="none" />
    </g>
  </svg>
);

export default SignInIllustration;

# Product Design Specification — Impeccable

**Product**: B2B Sales Intelligence & Outreach Dashboard  
**Target Market**: Slovak & Czech e-commerce businesses (SMEs)  
**Primary Use**: CRM-integrated lead generation, company research, outreach management  
**Design Aesthetic**: Linear/Stripe Dashboard style  

---

## Design Principles

### 1. **Clarity Over Decoration**
- Every visual element serves a function
- Data presentation is the priority
- Eliminate visual noise

### 2. **Professional & Trustworthy**
- Enterprise SaaS aesthetic
- Consistent, predictable interactions
- Polished but not flashy

### 3. **Performance First**
- Light, clean layouts load quickly
- Typography guides hierarchy clearly
- Whitespace aids readability

---

## Style Guidelines

### DO NOT USE
- ❌ Gradients (background fills, text, borders)
- ❌ Glassmorphism effects
- ❌ Shadows (heavy or decorative)
- ❌ Blur effects
- ❌ Bright accent colors
- ❌ Rounded corners beyond 4-6px
- ❌ Heavy animations or transitions
- ❌ Skewed/rotated elements

### DO USE
- ✅ Solid, flat colors (neutral palette + 1-2 accent colors)
- ✅ Crisp, clean borders (1px, subtle gray)
- ✅ Generous whitespace
- ✅ Clear typography hierarchy (weight, size, opacity)
- ✅ Minimal, purposeful icons
- ✅ Tight, consistent spacing (4px grid)
- ✅ Data-focused tables and charts
- ✅ Subtle micro-interactions (hover states, loading indicators)

---

## Color Palette

### Neutral Base
- **Background**: `#FFFFFF` (white) or `#FAFAFA` (light gray for sections)
- **Text Primary**: `#1A1A1A` (near-black for body text)
- **Text Secondary**: `#666666` (gray for labels, descriptions)
- **Borders**: `#E5E5E5` (light gray)
- **Dividers**: `#F0F0F0` (very light gray)

### Accent Color (Single Accent)
- **Primary Action**: `#0066CC` (professional blue) or similar
- **Success**: `#28A745` (green, used sparingly)
- **Warning**: `#FFC107` (amber)
- **Error**: `#DC3545` (red)

### Interactive States
- **Hover**: Slight opacity change or background color shift (not bold)
- **Active**: Accent color with subtle indicator
- **Disabled**: `#CCCCCC` text, `#F5F5F5` background
- **Focus**: Thin accent border (2px)

---

## Typography

### Font Family
- **Primary**: `Inter`, `Helvetica Neue`, `system-ui` (clean, sans-serif)
- **Monospace** (for data/code): `Menlo`, `Monaco`, `Courier New`

### Scale
- **Heading 1 (Page Title)**: 28-32px, `600-700` weight
- **Heading 2 (Section)**: 20-24px, `600` weight
- **Heading 3 (Subsection)**: 16-18px, `600` weight
- **Body**: 14-16px, `400-500` weight
- **Small/Label**: 12-13px, `400-500` weight, slightly lighter gray
- **Monospace Data**: 13-14px, `400` weight

### Line Height
- Headers: `1.2`
- Body: `1.5`
- Data/Lists: `1.6`

---

## Spacing System (4px Grid)

Use multiples of 4px for consistency:
- **Padding**: `8px`, `12px`, `16px`, `24px`, `32px`
- **Margins**: `8px`, `12px`, `16px`, `24px`, `32px`
- **Gap (flex/grid)**: `8px`, `12px`, `16px`, `24px`

### Component Spacing
- **Button**: `12px 16px` (small), `16px 24px` (large)
- **Card**: `16px` padding
- **Section**: `32px` margin between sections
- **Page Container**: `24px` padding on sides

---

## Components & Patterns

### Buttons
- **Style**: Solid background (accent color) with white text
- **Size**: 40px height (small), 44px (large)
- **Border Radius**: `4-6px`
- **Hover**: Slightly darker shade or reduced opacity
- **Secondary Button**: Outline style (border + transparent bg)
- **Disabled**: Grayed out, no hover effects

### Cards/Panels
- **Border**: `1px solid #E5E5E5`
- **Border Radius**: `6-8px`
- **Padding**: `16px`
- **Hover** (if interactive): Subtle shadow `0 2px 8px rgba(0,0,0,0.04)` or border color change

### Forms
- **Input Fields**: `1px solid #E5E5E5` border, `4px` border-radius
- **Padding**: `8px 12px`
- **Focus**: `2px` accent color border, no outline
- **Label**: `12px`, `#666666`, placed above input
- **Error State**: Red text below field, red border

### Tables
- **Header**: Slightly darker background (`#F5F5F5`), bold text
- **Rows**: `1px` bottom border between rows
- **Alternating Rows** (optional): Subtle background color for readability
- **Padding**: `12px`

### Navigation/Sidebar
- **Background**: `#FAFAFA` or white
- **Active Item**: Subtle accent background or left border
- **Hover**: Very subtle background change
- **Dividers**: `1px solid #E5E5E5`

### Data Visualizations
- **Charts**: Minimal axes, clear labels
- **Colors**: Use accent color + neutral grays
- **No 3D effects, gradients, or shadows**
- **Legend**: Small, right-aligned, optional

---

## Interactions & Micro-interactions

### Loading States
- Simple spinner (outline only, no fill)
- "Loading..." text below
- Fade in/out: 200-300ms

### Transitions
- **Navigation**: 150-200ms fade or slide
- **Hover effects**: 150ms
- **Form validation**: Instant or 100ms
- **No bounces or elastic effects**

### Feedback
- **Success**: Brief green check mark + message (auto-dismiss in 3-4s)
- **Error**: Red icon + error message (stays until dismissed or corrected)
- **Confirmation**: Modal with clear actions
- **Tooltips**: Dark background, white text, 200px max width

---

## Page Layout Template

```
┌─────────────────────────────────────────┐
│  Header (Navigation, Logo, User)        │
├──────────┬──────────────────────────────┤
│ Sidebar  │  Main Content Area           │
│ (if      │  • Page Title (32px)         │
│  used)   │  • Filters/Controls          │
│          │  • Data Tables/Cards         │
│          │  • Pagination (if needed)    │
│          │                              │
│          │  Footer (optional)           │
└──────────┴──────────────────────────────┘
```

**Spacing**:
- Header height: 60-64px
- Sidebar width (if used): 240-280px
- Main content padding: 24px
- Section gaps: 32px

---

## Checklist for Design Reviews

When reviewing a design using Impeccable:

- [ ] No gradients, blur, or glassmorphism
- [ ] Spacing follows 4px grid
- [ ] Typography hierarchy is clear
- [ ] Colors limited to neutral + 1-2 accents
- [ ] Component sizes are consistent
- [ ] Borders are 1px or subtle
- [ ] Hover/active states are subtle
- [ ] Data is the focus, not decoration
- [ ] Responsive at mobile, tablet, desktop
- [ ] Accessibility: color contrast, keyboard nav, ARIA labels

---

## Reference

- **Inspiration**: Linear.app, Stripe Dashboard, Vercel, Figma (clean mode)
- **Impeccable Skill**: `.claude/skills/impeccable/.claude/skills/impeccable/`
- **CLAUDE.md**: Design skills configuration for this project

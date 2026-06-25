# Claude Code Configuration

## Project Context

**Project**: B2B Sales Intelligence & Outreach Dashboard (SK/CZ e-commerce)  
**Type**: Python backend (web scraping) + API  
**Purpose**: CRM-integrated lead generation and company intelligence

---

## Design Skills Configuration

This project includes 3 specialized design skills for UI/UX improvements:

### 1. **Emil Design Engineering** (`.claude/skills/emil-design-eng/`)

**When to use**: Interactive UI components, animations, micro-interactions, and modern React patterns

**Resources**:
- Main skill: `.claude/skills/emil-design-eng/skills/emil-design-eng/SKILL.md`

**Best for**:
- Polished component libraries
- Smooth transitions and state animations
- Interactive form handling
- Component composition patterns

**Access**: When redesigning dashboard interactions or building component libraries

---

### 2. **Impeccable Design System** (`.claude/skills/impeccable/.claude/skills/impeccable/`)

**When to use**: Professional dashboard design, typography, spacing systems, and design tokens for enterprise UIs

**Resources**:
- Main skill: `.claude/skills/impeccable/.claude/skills/impeccable/SKILL.md`
- Reference guides: `.claude/skills/impeccable/.claude/skills/impeccable/reference/`
- Scripts & utilities: `.claude/skills/impeccable/.claude/skills/impeccable/scripts/`
- Product configuration: `./PRODUCT.md` (local to this project)

**Best for**:
- Dashboard layouts and grids
- Design system documentation
- Consistent spacing and sizing
- Color and typography systems
- Professional/minimalist aesthetics (Linear/Stripe style)

**Access**: When styling the main dashboard, creating design documentation, or establishing UI consistency

**Special**: Configure with `PRODUCT.md` which describes this project's style requirements

---

### 3. **Taste Skill** (`.claude/skills/taste-skill/skills/`)

**When to use**: Visual design aesthetics, layout patterns, design inspiration, and UI style guidance

**Resources**:
- Collection of design skills: `.claude/skills/taste-skill/skills/` contains:
  - `brutalist-skill/SKILL.md` — minimal, content-first design
  - `soft-skill/SKILL.md` — rounded, friendly design
  - `redesign-skill/SKILL.md` — comprehensive redesigns
  - `image-to-code-skill/SKILL.md` — converting designs to code
  - `minimalist-skill/SKILL.md` — clean, sparse layouts
  - And more...

**Best for**:
- Design inspiration and aesthetic guidance
- Choosing visual direction (brutalist, soft, minimalist)
- Converting mockups to code
- Frontend styling across multiple approaches

**Access**: When needing design direction, choosing visual style, or converting design mockups

---

## Usage Guidelines

### Using a Design Skill

When starting a UI/design task, use the relevant skill:

```
/impeccable — Design system, dashboard layouts, professional styling
/emil-design-eng — Components, interactions, animations
/taste-skill — Design aesthetics, visual direction, style choices
```

### Priority & Combination

1. **Start with Impeccable** if the task involves:
   - Dashboard design
   - Professional/enterprise styling
   - Design consistency across pages
   - Typography and spacing systems

2. **Add Emil Design** if the task needs:
   - Interactive components
   - Smooth animations
   - React component patterns
   - Micro-interactions

3. **Reference Taste Skill** for:
   - Visual direction when uncertain about style
   - Design inspiration from multiple approaches
   - Converting visual mockups to code

### For This Project

This project is a **B2B sales intelligence dashboard** for SK/CZ e-commerce outreach.

**Design Direction**: Linear/Stripe Dashboard aesthetic
- Clean, professional, data-focused
- NO gradients or glassmorphism
- Consistent spacing and typography
- Data visualization friendly
- Enterprise/SaaS standard

See `PRODUCT.md` for complete design specification for Impeccable.

---

## File Organization

```
.claude/
├── skills/
│   ├── emil-design-eng/          # Emil Design Engineering skill
│   │   └── skills/
│   │       └── emil-design-eng/
│   ├── impeccable/                # Impeccable Design System
│   │   └── .claude/
│   │       └── skills/
│   │           └── impeccable/
│   └── taste-skill/               # Taste Skill (multi-design approach)
│       └── skills/
│           ├── brutalist-skill/
│           ├── soft-skill/
│           ├── redesign-skill/
│           ├── image-to-code-skill/
│           └── ... (other design skills)
CLAUDE.md                           # This file (configuration)
PRODUCT.md                          # Product spec for Impeccable design
```

---

## Notes

- Skills are git-tracked in `.claude/skills/` to maintain reproducibility
- Each skill has its own `SKILL.md` documentation
- Use `PRODUCT.md` to communicate design requirements to Impeccable
- Skills are designed to complement each other — use them together as needed

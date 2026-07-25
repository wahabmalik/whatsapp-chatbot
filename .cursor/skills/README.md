# Cursor UI/UX Skills

Free Agent Skills installed for this project. Cursor loads them from `.cursor/skills/` automatically.

| Skill | Source | Use when |
|-------|--------|----------|
| **frontend-design** | [anthropics/skills](https://github.com/anthropics/skills) | Building or reshaping UI with distinctive visual direction |
| **effective-ui-design** | [sebastian-software/effective-ui-design-skill](https://github.com/sebastian-software/effective-ui-design-skill) | Accessibility, spacing, typography, forms, buttons, SEO |
| **ui-design-brain** | [carmahhawwari/ui-design-brain](https://github.com/carmahhawwari/ui-design-brain) | Component patterns for 60+ UI elements |
| **web-design-guidelines** | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) | Auditing UI against Vercel Web Interface Guidelines |

Mirrored under `.agents/skills/` for multi-agent CLI compatibility.

## Reinstall

```bash
npx skills add github.com/anthropics/skills/tree/main/skills/frontend-design --skill frontend-design -y
npx skills add sebastian-software/effective-ui-design-skill --skill effective-ui-design -y
npx skills add carmahhawwari/ui-design-brain --skill ui-design-brain -y
npx skills add vercel-labs/agent-skills --skill web-design-guidelines -y
cp -a .agents/skills/. .cursor/skills/
```

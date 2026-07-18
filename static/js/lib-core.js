// ── LIBRARY CORE ──
let _libCurrentCategory = null;
let _libCurrentSub = null;
let _libCurDoc = null;   // {category, path} of the doc currently open (for detail triggers)

function libIcon(name) {
  const icons = {
    'code-guides': '\u{1F4BB}', 'os-guides': '\u{1F4BB}', 'openclaw-docs': '\u{1F4DA}',
    'project-docs': '\u{1F4CB}', 'error-solutions': '\u{26A0}\u{FE0F}',
    'procedures': '\u{1F4DD}', 'archived-pages': '\u{1F4C2}'
  };
  return icons[name] || '\u{1F4D6}';
}

function libLabel(name) {
  const labels = {
    'code-guides': 'Code Guides', 'os-guides': 'OS Guides', 'openclaw-docs': 'OpenClaw Docs',
    'project-docs': 'Project Docs', 'error-solutions': 'Error Solutions',
    'procedures': 'Procedures', 'archived-pages': 'Archived Pages'
  };
  return labels[name] || name;
}

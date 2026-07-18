# CSS Quick Reference

> Offline reference guide for AI agents. Last updated: 2026-07-10.

## Contents
1. Selectors
2. Box Model
3. Display & Positioning
4. Flexbox
5. Grid
6. Animations
7. Responsive Design
8. Custom Properties
9. Common Patterns

## 1. Selectors

```css
/* Basic */
* { }                          /* universal */
.tag { }                       /* class */
#id { }                        /* id */
div { }                        /* element */
div, p { }                     /* multiple */

/* Combinators */
div > p { }                    /* direct child */
div p { }                      /* descendant */
div + p { }                    /* adjacent sibling */
div ~ p { }                    /* general sibling */

/* Attribute */
[type="text"] { }
[class^="btn-"] { }            /* starts with */
[class$="-active"] { }         /* ends with */
[class*="card"] { }            /* contains */

/* Pseudo-classes */
:hover :focus :active :visited
:first-child :last-child :nth-child(2)
:nth-child(odd) :nth-child(even)
:nth-child(3n+1)               /* every 3rd starting at 1 */
:not(.exclude) { }
:empty { }                     /* no children */
:target { }                    /* matches URL fragment */
:checked { }                   /* checked checkbox/radio */
:disabled :enabled :read-only

/* Pseudo-elements */
::before { content: "→"; }     /* insert content before */
::after { content: ""; }        /* insert content after */
::first-letter { }
::first-line { }
::selection { }
::placeholder { }

/* Specificity: inline > #id > .class > element */
/* !important overrides specificity (avoid if possible) */
```

## 2. Box Model

```css
/* Box-sizing (always set this) */
* { box-sizing: border-box; }  /* width includes padding+border */
/* default: content-box (width = content only) */

/* Properties */
margin: 20px;                  /* all sides */
margin: 10px 20px;             /* top/bottom left/right */
margin: 10px 20px 30px 40px;   /* top right bottom left */
margin: auto;                  /* center horizontally (block) */

padding: 20px;                 /* same shorthand as margin */

border: 2px solid #333;
border-radius: 8px;
border: none;
outline: none;                 /* remove default focus outline */

/* Box shadow */
box-shadow: 0 2px 8px rgba(0,0,0,0.1);
box-shadow: 0 0 0 2px blue, 0 4px 12px rgba(0,0,0,0.2); /* layered */
```

## 3. Display & Positioning

```css
/* Display types */
display: block;        /* full width, line break */
display: inline;       /* content width, no line break */
display: inline-block; /* inline but accepts width/height */
display: none;         /* removed from layout */
display: flex;         /* flex container */
display: grid;         /* grid container */
display: contents;     /* element's children become part of parent */

/* Position */
position: static;      /* default, normal flow */
position: relative;     /* offset from normal position */
position: absolute;    /* relative to nearest positioned ancestor */
position: fixed;       /* relative to viewport */
position: sticky;      /* relative until scroll threshold */

/* Examples */
.relative { position: relative; top: 10px; left: 20px; }
.absolute { position: absolute; top: 0; right: 0; }
.sticky { position: sticky; top: 0; z-index: 100; }

/* Z-index (only works on positioned elements) */
z-index: 1;            /* lower */
z-index: 999;          /* higher */
```

## 4. Flexbox

```css
/* Container properties */
.container {
  display: flex;
  flex-direction: row;          /* row | row-reverse | column | column-reverse */
  justify-content: center;       /* main axis: flex-start | center | space-between | space-around | space-evenly */
  align-items: center;           /* cross axis: flex-start | center | stretch | baseline */
  flex-wrap: wrap;               /* nowrap | wrap | wrap-reverse */
  gap: 16px;                     /* spacing between items */
  align-content: space-between;  /* multi-line alignment */
}

/* Item properties */
.item {
  flex-grow: 1;                   /* grow to fill space */
  flex-shrink: 0;                 /* don't shrink */
  flex-basis: 200px;              /* initial size */
  flex: 1;                       /* shorthand: grow=1 shrink=1 basis=0 */
  order: -1;                     /* reorder (default: 0) */
  align-self: flex-end;          /* override align-items for one item */
}

/* Centering pattern */
.center {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
}
```

## 5. Grid

```css
/* Basic grid */
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;      /* 3 equal columns */
  grid-template-columns: repeat(3, 1fr);
  grid-template-columns: 200px 1fr 100px;    /* fixed + flexible */
  grid-template-columns: repeat(auto-fit, minmax(250, 1fr));
  grid-template-rows: auto 1fr auto;
  gap: 16px;
  grid-gap: 16px 24px;                        /* row col */
}

/* Grid areas */
.layout {
  display: grid;
  grid-template-areas:
    "header header header"
    "sidebar main main"
    "footer footer footer";
  grid-template-columns: 200px 1fr 1fr;
  grid-template-rows: 60px 1fr 40px;
}
.header { grid-area: header; }
.sidebar { grid-area: sidebar; }
.main { grid-area: main; }
.footer { grid-area: footer; }

/* Item placement */
.item {
  grid-column: 1 / 3;     /* start at col 1, end before col 3 */
  grid-row: 2 / 4;
  grid-column: span 2;   /* span 2 columns */
}

/* Alignment */
.container { justify-items: center; align-items: center; }
.item { justify-self: end; align-self: start; }
```

## 6. Animations

```css
/* Transitions (state change) */
.btn {
  transition: all 0.3s ease;
  transition: background 0.2s, transform 0.3s ease-out;
  transition: width 300ms cubic-bezier(0.4, 0, 0.2, 1);
}
.btn:hover {
  background: blue;
  transform: scale(1.05);
}

/* Keyframe animations */
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}
.element {
  animation: fadeIn 0.5s ease forwards;
  animation: fadeIn 1s ease 0.5s infinite alternate;
  /* name | duration | timing | delay | iteration | direction */
}

/* Common animations */
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
@keyframes shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-10px); }
  75% { transform: translateX(10px); }
}

/* Transform */
transform: translate(50px, 100px);
transform: rotate(45deg);
transform: scale(1.5);
transform: skew(10deg, 5deg);
transform: translate(-50%, -50%) rotate(45deg);  /* chained */
```

## 7. Responsive Design

```css
/* Media queries */
@media (max-width: 768px) { /* tablet */ }
@media (max-width: 480px) { /* mobile */ }
@media (min-width: 1200px) { /* large desktop */ }

/* Breakpoint convention */
/* Mobile-first: base styles are mobile, then add larger screens */
.base { /* mobile styles */ }
@media (min-width: 768px) { /* tablet additions */ }
@media (min-width: 1024px) { /* desktop additions */ }

/* Units */
rem: relative to root font size (16px default)  /* preferred */
em: relative to parent font size
%: relative to parent
vw/vh: viewport width/height (1 = 1%)
vmin/vmax: smaller/larger of vw or vh
px: absolute (not responsive)

/* Modern responsive */
img { max-width: 100%; height: auto; }
.video-container { aspect-ratio: 16 / 9; width: 100%; }

/* Container queries (newer) */
@container sidebar (min-width: 400px) {
  .card { display: grid; grid-template-columns: 1fr 2fr; }
}
.card-container { container-type: inline-size; }
```

## 8. Custom Properties (Variables)

```css
:root {
  --primary: #007bff;
  --secondary: #6c757d;
  --bg: #f8f9fa;
  --text: #212529;
  --spacing: 16px;
  --radius: 8px;
  --font: 'Inter', sans-serif;
  --shadow: 0 2px 8px rgba(0,0,0,0.1);
}

.button {
  background: var(--primary);
  color: white;
  padding: var(--spacing);
  border-radius: var(--radius);
  font-family: var(--font);
  box-shadow: var(--shadow);
}

/* Dynamic override */
.dark-theme {
  --bg: #1a1a1a;
  --text: #f8f9fa;
}

/* Fallback values */
color: var(--maybe-undefined, #333);
```

## 9. Common Patterns

```css
/* Center anything */
.center-absolute {
  position: absolute;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%);
}
.center-flex {
  display: flex;
  justify-content: center;
  align-items: center;
}
.center-grid {
  display: grid;
  place-items: center;
}

/* Sticky header */
.header {
  position: sticky;
  top: 0;
  z-index: 100;
  background: var(--bg);
  backdrop-filter: blur(10px);
}

/* Sidebar layout */
.sidebar-layout {
  display: grid;
  grid-template-columns: 250px 1fr;
  min-height: 100vh;
}
@media (max-width: 768px) {
  .sidebar-layout { grid-template-columns: 1fr; }
}

/* Card */
.card {
  background: white;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  transition: transform 0.2s, box-shadow 0.2s;
}
.card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 24px rgba(0,0,0,0.12);
}

/* Text truncation */
.truncate {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* Reset */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

/* Smooth scroll */
html { scroll-behavior: smooth; }

/* Hide visually but keep for screen readers */
.sr-only {
  position: absolute;
  width: 1px; height: 1px;
  padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0,0,0,0);
  white-space: nowrap; border: 0;
}
```

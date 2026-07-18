# HTML Quick Reference

> Offline reference guide for AI agents. Last updated: 2026-07-10.

## Contents
1. Document Structure
2. Semantic HTML5 Tags
3. Forms
4. Accessibility
5. Meta Tags
6. HTML5 APIs
7. Media
8. Common Patterns

## 1. Document Structure

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Page Title</title>
</head>
<body>
    <header>
        <nav><!-- navigation --></nav>
    </header>
    <main>
        <article><!-- main content --></article>
    </main>
    <footer><!-- footer --></footer>
</body>
</html>
```

## 2. Semantic HTML5 Tags

```html
<header>     <!-- Top section of page or article -->
<nav>        <!-- Navigation links -->
<main>       <!-- Main content (one per page) -->
<article>    <!-- Self-contained content (blog post, card) -->
<section>    <!-- Thematic grouping of content -->
<aside>      <!-- Sidebar, related content -->
<footer>     <!-- Bottom section -->
<figure>     <!-- Image/diagram with caption -->
<figcaption> <!-- Caption for figure -->
<time datetime="2026-07-10">July 10, 2026</time>
<mark>       <!-- Highlighted text -->
<details>    <!-- Collapsible disclosure -->
  <summary>Click to expand</summary>
  Hidden content here.
</details>
```

## 3. Forms

```html
<form action="/submit" method="POST">
  <fieldset>
    <legend>User Info</legend>
    
    <label for="name">Name:</label>
    <input type="text" id="name" name="name" required 
           minlength="2" maxlength="50" placeholder="Enter name">
    
    <label for="email">Email:</label>
    <input type="email" id="email" name="email" required
           pattern="[^@]+@[^@]+\.[a-z]+" 
           placeholder="user@example.com">
    
    <label for="age">Age:</label>
    <input type="number" id="age" name="age" min="18" max="120">
    
    <label for="pwd">Password:</label>
    <input type="password" id="pwd" name="pwd" 
           minlength="8" required>
    
    <label for="color">Favorite color:</label>
    <input type="color" id="color" name="color" value="#ff0000">
    
    <label for="birthday">Birthday:</label>
    <input type="date" id="birthday" name="birthday">
    
    <label for="file">Upload:</label>
    <input type="file" id="file" name="file" 
           accept="image/*" multiple>
  </fieldset>
  
  <fieldset>
    <label for="bio">Bio:</label>
    <textarea id="bio" name="bio" rows="4" cols="50"></textarea>
    
    <label for="country">Country:</label>
    <select id="country" name="country">
      <optgroup label="North America">
        <option value="us">United States</option>
        <option value="ca">Canada</option>
      </optgroup>
      <option value="other">Other</option>
    </select>
    
    <input type="checkbox" id="agree" name="agree" required>
    <label for="agree">I agree to terms</label>
    
    <label>Gender:
      <input type="radio" name="gender" value="m"> Male
      <input type="radio" name="gender" value="f"> Female
      <input type="radio" name="gender" value="o"> Other
    </label>
  </fieldset>
  
  <button type="submit">Submit</button>
  <button type="reset">Reset</button>
</form>
```

## 4. Accessibility

```html
<!-- Alt text for images -->
<img src="logo.png" alt="Company Logo">
<img src="decorative.png" alt="">  <!-- empty for decorative -->

<!-- ARIA roles and labels -->
<div role="navigation" aria-label="Main Menu">
  <a href="/" aria-current="page">Home</a>
</div>

<button aria-label="Close dialog" aria-pressed="false">X</button>

<!-- Live regions for dynamic content -->
<div aria-live="polite" id="status">Loading...</div>
<div aria-live="assertive" id="errors"></div>

<!-- Skip link (keyboard navigation) -->
<a href="#main" class="skip-link">Skip to main content</a>
<main id="main">

<!-- Label associations -->
<label for="search">Search</label>
<input type="search" id="search" aria-describedby="search-help">
<small id="search-help">Enter at least 3 characters</small>

<!-- Heading hierarchy (don't skip levels) -->
<h1>Page Title</h1>
  <h2>Section</h2>
    <h3>Subsection</h3>

<!-- Table accessibility -->
<table>
  <caption>Sales by Quarter</caption>
  <thead>
    <tr><th scope="col">Quarter</th><th scope="col">Revenue</th></tr>
  </thead>
  <tbody>
    <tr><th scope="row">Q1</td><td>$10k</td></tr>
  </tbody>
</table>
```

## 5. Meta Tags

```html
<head>
  <!-- Essential -->
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="Page description for SEO">
  <title>Page Title</title>
  
  <!-- Open Graph (social sharing) -->
  <meta property="og:title" content="My Page">
  <meta property="og:description" content="Description for social">
  <meta property="og:image" content="https://example.com/image.jpg">
  <meta property="og:url" content="https://example.com">
  <meta property="og:type" content="website">
  
  <!-- Twitter Cards -->
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="My Page">
  <meta name="twitter:image" content="https://example.com/image.jpg">
  
  <!-- Theme color -->
  <meta name="theme-color" content="#007bff">
  
  <!-- Icons -->
  <link rel="icon" href="/favicon.ico">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  
  <!-- Preload resources -->
  <link rel="preload" href="/fonts/main.woff2" as="font" crossorigin>
  <link rel="preconnect" href="https://api.example.com">
  
  <!-- Canonical URL -->
  <link rel="canonical" href="https://example.com/page">
  
  <!-- Redirect (use sparingly) -->
  <meta http-equiv="refresh" content="3;url=https://example.com">
</head>
```

## 6. HTML5 APIs

```html
<!-- LocalStorage (persists) -->
<script>
localStorage.setItem('key', 'value');
const val = localStorage.getItem('key');
localStorage.removeItem('key');
localStorage.clear();
</script>

<!-- SessionStorage (cleared on tab close) -->
<script>
sessionStorage.setItem('temp', 'data');
const temp = sessionStorage.getItem('temp');
</script>

<!-- Geolocation -->
<script>
navigator.geolocation.getCurrentPosition(
  pos => console.log(pos.coords.latitude, pos.coords.longitude),
  err => console.error(err),
  { enableHighAccuracy: true, timeout: 5000 }
);
</script>

<!-- Canvas -->
<canvas id="canvas" width="500" height="300"></canvas>
<script>
const ctx = canvas.getContext('2d');
ctx.fillStyle = 'red';
ctx.fillRect(10, 10, 100, 50);
ctx.beginPath();
ctx.arc(250, 150, 30, 0, Math.PI * 2);
ctx.stroke();
ctx.font = '20px Arial';
ctx.fillText('Hello', 200, 50);
</script>

<!-- Web Workers -->
<script>
const worker = new Worker('worker.js');
worker.postMessage({ command: 'start', data: [1,2,3] });
worker.onmessage = e => console.log('Result:', e.data);
worker.terminate();
</script>

<!-- Intersection Observer (lazy loading) -->
<script>
const observer = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.src = entry.target.dataset.src;
      observer.unobserve(entry.target);
    }
  });
});
document.querySelectorAll('img[data-src]').forEach(img => observer.observe(img));
</script>
```

## 7. Media

```html
<!-- Audio -->
<audio controls>
  <source src="audio.mp3" type="audio/mpeg">
  <source src="audio.ogg" type="audio/ogg">
  Your browser doesn't support audio.
</audio>

<!-- Video -->
<video width="640" height="360" controls poster="poster.jpg">
  <source src="video.mp4" type="video/mp4">
  <track src="subtitles.vtt" kind="subtitles" srclang="en" label="English">
</video>

<!-- Responsive image -->
<picture>
  <source media="(min-width: 800px)" srcset="large.jpg">
  <source media="(min-width: 400px)" srcset="medium.jpg">
  <img src="small.jpg" alt="Responsive image">
</picture>

<!-- Lazy loading -->
<img src="placeholder.jpg" data-src="real-image.jpg" 
     loading="lazy" alt="Lazy loaded">
```

## 8. Common Patterns

```html
<!-- Card layout -->
<article class="card">
  <img src="thumb.jpg" alt="Thumbnail" loading="lazy">
  <div class="card-body">
    <h3>Title</h3>
    <p>Description text here.</p>
    <a href="/link">Read more</a>
  </div>
</article>

<!-- Accordion (pure HTML) -->
<details>
  <summary>Section 1</summary>
  <p>Content for section 1</p>
</details>
<details>
  <summary>Section 2</summary>
  <p>Content for section 2</p>
</details>

<!-- Dialog (native) -->
<dialog id="modal">
  <form method="dialog">
    <p>Are you sure?</p>
    <button>Cancel</button>
    <button value="confirm">Confirm</button>
  </form>
</dialog>
<script>
document.getElementById('modal').showModal();
</script>

<!-- Data attributes -->
<div data-user-id="42" data-role="admin" data-toggle="modal">
  User info
</div>

<!-- Template element -->
<template id="card-template">
  <div class="card">
    <h3></h3>
    <p></p>
  </div>
</template>
<script>
const template = document.getElementById('card-template');
const clone = template.content.cloneNode(true);
clone.querySelector('h3').textContent = 'Title';
document.body.appendChild(clone);
</script>
```

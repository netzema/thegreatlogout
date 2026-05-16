# The Great Logout — GitHub Pages Landing Page

This is a static one-page website for The Great Logout.

## Files

- `index.html` — full landing page with embedded CSS and JS
- `CNAME` — custom domain file for GitHub Pages

## Quick customization

Open `index.html` and change:

```css
--accent: #B6FF3B;
```

Good alternatives:

```css
--accent: #32E6FF; /* cyan */
--accent: #FF3B3B; /* red */
--accent: #FFD166; /* amber */
--accent: #B983FF; /* purple */
```

Also replace all `mailto:hello@thegreatlogout.org` links with real links once they exist:

- pledge form
- support page
- donation link
- crowdfunding page
- contact address

## Deploy on GitHub Pages

1. Put `index.html` and `CNAME` into your GitHub Pages repository.
2. Commit and push.
3. In GitHub:
   - Repository → Settings → Pages
   - Source: Deploy from a branch
   - Branch: `main`
   - Folder: `/root`
4. Wait until GitHub publishes the site.

## Custom domain

The included `CNAME` file uses:

```txt
thegreatlogout.org
```

Only keep this file if you own the domain.

# Eregion website

The product and download page for Eregion, live at
[ethany14.github.io/Eregion-Agent](https://ethany14.github.io/Eregion-Agent/). It is a static site with no build step.

| Page | Contents |
| --- | --- |
| `index.html` | Home: overview, the five stages, Jev speed, privacy and download |
| `guide.html` | User guide: install, examples and walkthroughs, one topic at a time |
| `docs.html` | Documentation: settings, Jev, browser options, data, updating, architecture |

Every page has a ☰ menu that opens a side panel with Home, every guide topic and
every docs topic. Guide and Docs also keep that list beside the content. `script.js`
shows the chosen topic (from the URL hash) with Previous/Next links; without
JavaScript every topic is shown in sequence.

All pages share `styles.css`, `script.js` and the images in `assets/`. The header,
footer and icon sprite are repeated in each page, so change them in all three.

## Preview

Open `frontend/site/index.html` in a browser, or serve the folder:

```sh
python -m http.server 4000 --directory site
```

Then visit [localhost:4000](http://localhost:4000).

## Publish with GitHub Pages

1. In the repository on GitHub, open **Settings → Pages** and set **Source** to
   **GitHub Actions**.
2. Merge changes to `main`. Any change under `frontend/site/` publishes the site again, or
   open **Actions → Publish website → Run workflow** to publish by hand.

The site is published at `https://<owner>.github.io/<repository>/`.

## Assets

| Path | Contents |
| --- | --- |
| `assets/screens/` | App screenshots in Night (`*-night.webp`) and Day (`*-light.webp`), including Job alerts |
| `assets/readme/` | The README banner in both themes |
| `assets/holly.svg` | The holly mark, also used as the favicon |

The screenshots show example data (a fictional candidate and companies), not
real applications. Retake them whenever the app's layout changes so the site and
README stay accurate. The page follows the app's design tokens in
`frontend/web_app/tokens.css`; update both together.

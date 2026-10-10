# Eregion website

The product and download page for Eregion. It is a static site with no build step:
`index.html`, `styles.css`, `script.js` and the images in `assets/`.

## Preview

Open `site/index.html` in a browser, or serve the folder:

```sh
python -m http.server 4000 --directory site
```

Then visit [localhost:4000](http://localhost:4000).

## Publish with GitHub Pages

1. In the repository on GitHub, open **Settings → Pages** and set **Source** to
   **GitHub Actions**.
2. Open **Actions → Publish website → Run workflow**.

The site is published at `https://<owner>.github.io/<repository>/`. To republish
on every change, add a `push` trigger for `site/**` to
`.github/workflows/pages.yml`.

## Assets

| Path | Contents |
| --- | --- |
| `assets/screens/` | App screenshots in Night (`*-night.webp`) and Day (`*-light.webp`) |
| `assets/readme/` | The README banner in both themes |
| `assets/holly.svg` | The holly mark, also used as the favicon |

The screenshots show example data (a fictional candidate and companies), not
real applications. Retake them whenever the app's layout changes so the site and
README stay accurate. The page follows the app's design tokens in
`web_app/tokens.css`; update both together.

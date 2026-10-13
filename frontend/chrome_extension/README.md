# Eregion Lens

Compare a job with your resume while you browse. Eregion Lens opens a Chrome Side
Panel, extracts the selected page, and lets you review the job before saving it
or requesting a fit analysis. Continue with materials, applications, and interview
practice in the [Eregion web app](../../README.md).

## Install

1. Follow the [Eregion setup](../../README.md#get-started) and start the local server
   on port 8000.
2. Open `http://localhost:8000/apply`, upload a selectable-text PDF resume, and
   check your saved details.
3. Open `chrome://extensions` in Chrome 116 or later.
4. Enable **Developer mode**, choose **Load unpacked**, and select this
   `chrome_extension` directory.
5. Open a job posting and click the Eregion Lens toolbar icon.

The extension uses `http://localhost:8000`. Keep the backend running while using
it, and reload the unpacked extension after updating its files.

## Use it

Opening the panel from the toolbar starts extraction of the selected HTTP(S) page.
Review or edit the title, company, and description, then choose **Analyze fit** or
**Save job**. A saved job can be opened in career chat with its context attached.

If extraction is incomplete, use **Extract page** again, select the relevant job
text, or paste the description into the editable field. Chrome's internal pages
and other protected surfaces cannot be extracted.

Fit analysis uses the resume saved in the local service. The score, requirement
statuses, and suggestions help explain the comparison; they do not predict a
hiring decision or generate an approved application document.

## Permissions and data flow

| Permission | Use |
| --- | --- |
| `activeTab` | Temporary access to the page selected through the toolbar action. |
| `scripting` | Run the page-text extractor. |
| `storage` | Keep the selected tab and a temporary extraction handoff in session storage. |
| `sidePanel` | Display the extension interface. |
| `http://localhost:8000/*` | Contact the local Eregion API. |

The extraction result is temporarily cached in Chrome session storage while it
passes from the toolbar worker to the panel, then consumed by the panel. The
theme preference is saved locally. Extracted text is not automatically submitted
for model analysis: **Analyze fit** and **Save job** initiate the corresponding
local-service actions. Analysis sends relevant content through the server's
configured model provider.

The extension does not request browsing history, cookies, downloads,
`webRequest`, `tabs`, or blanket access to all websites. Your resume is managed by
the backend, not uploaded through the extension.

## Troubleshooting

- **Service unavailable:** confirm the backend is running on port 8000 in the
  expected Python environment; check `http://localhost:8000/health`.
- **No saved resume:** upload one in the web app before analyzing a job.
- **Wrong job extracted:** review the editable fields and use manual extraction
  or pasted text, especially on pages containing several listings.
- **Analysis failed:** check provider access and the backend error message. A
  healthy local server does not guarantee a successful model request.

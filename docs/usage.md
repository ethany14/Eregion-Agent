# Using Eregion

[Home](../README.md) · [Configuration](configuration.md)

## Set up your profile

Upload a PDF resume with selectable text in the conversation composer. Eregion
saves the original file and extracts candidate information for later applications.
Check **Your details** before starting, especially contact information, schools,
degrees, fields of study, and dates.

Keep in-progress and completed education distinct. If a fact is missing, tell the
agent instead of relying on it to infer a qualification. Confirmed career evidence
and saved preferences serve different purposes: a preference is not proof of
experience.

## Find and compare roles

Describe your preferred role, location, seniority, and working arrangement. You
can ask for a single search, supply a direct posting link, or paste the job
description itself. When pasting, identify the text as the job description so its
source is clear.

The agent can browse public postings and compare them with your resume. Read the
evidence and gaps alongside the score. A listing title seen in search results
does not mean the agent could read the full posting; login restrictions and other
limits should appear in its response.

Saved jobs retain source snapshots. A source change or a correction to your
candidate facts can require a new analysis or material review.

## Prepare and review materials

Ask for a tailored resume, a cover letter, or answers to application questions.
Eregion checks drafts against their cited sources and revises within a bounded
attempt limit. A generated file is not automatically an approved document.

Use **The Forge** or the material cards in chat to inspect the content,
verification result, and version. Download the PDF and check its layout as well
as its wording. If a draft needs revision, describe the change in the same chat.

Approval applies to a specific version. When a newer draft fails or is still
being generated, an older successful document remains available for inspection.
Choose it explicitly if that is the version you want. Changed evidence or an
invalidated selection requires another review; the agent must not silently
substitute a different approved document.

## Prepare an application

After approving materials, ask the agent to apply to the selected role. It opens
the application, fills known details, handles repeatable sections such as
education, and uploads or enters the selected materials where the form allows.

When several questions need answers, complete the available choices and use
**Submit answers & continue** once. You can also answer naturally in chat. Missing
work authorization, sponsorship, consent, or employer-specific facts may still
need a focused question.

The agent may run multiple application workers. Watch the active application
before replying or reviewing materials. Progress messages describe work in
progress; the final review should reflect the fields and attachments actually
present in the browser.

Inspect the completed form before using the final submission action. Editing a
reviewed form can invalidate that review. If a submission outcome is uncertain,
check the employer's page or confirmation before attempting anything again.

## Watch or take over the browser

Open **The Lookout** from the conversation header to see browser activity. Use
**Control browser** for direct interaction when a site needs help; resume the
agent after completing the step.

The local preview and **Visual browser backup** are separate. The preview lets
you watch the browser. Visual backup allows requested screenshots to reach your
configured model so it can operate difficult controls. It is optional and off by
default. Account pages use the dedicated secure account workflow.

Provide passwords through the secure account form, not chat. The agent can use
supplied credentials for supported login or registration steps. MFA, email
verification, CAPTCHA, and some SSO flows require your interaction.

Chrome normally runs in an off-screen window. The
[browser configuration](configuration.md#browser-and-worker-settings) includes a
headless mode if you prefer it; switching from headless to visible Chrome can
require reopening the page and rechecking unsaved fields.

## Reuse confirmed answers

Candidate details and the saved resume persist across applications and server
restarts. Remembered answers retain their source question and scope. Review the
available memory choices and remove an answer when it no longer applies.

Similar wording alone is not enough to reuse consent, immigration, or
employer-specific answers. New corrections take precedence over old saved values.
Generated drafts and incidental form choices do not become confirmed career
facts automatically.

## Schedule recommendations

Ask for daily recommendations with a time, timezone, and search preferences,
or configure them in **Job alerts**. For example:

> Every day at 9 AM in America/New_York, find new junior analyst roles in
> New York or remote US. Show the strongest matches.

Recommendations appear in the app. Browser notifications require permission and
browser support. Review digests, mark them as read, and edit or pause the search
as your preferences change. Recurring searches track previously recommended jobs
to avoid showing the same recommendation each round.

This scheduler runs in the local backend. Keep the computer awake and the server
running for execution at the requested time. You can still ask for a one-off
search in any conversation.

## Practice for interviews

Select a saved role and ask for a mock interview. Answer each question in chat,
review the feedback, and read the final report when the session finishes.
Interview practice does not confirm new resume evidence on your behalf.

## Resume work and troubleshoot

Conversations, started applications, and reviewed documents are saved locally.
Paused tasks remain paused. Running work can recover after a backend restart,
but a reopened browser may require login or a fresh review.

| Symptom | What to check |
| --- | --- |
| The model does not reply | Check the configured model, provider access, balance, and rate limits. Retry the saved task after resolving the provider error. |
| Chrome does not start | Install Google Chrome and install `requirements.txt` in the same Python environment that runs the server. |
| A field cannot be filled | Inspect the browser's current choices or validation message. Correct the source fact or take over, then resume. |
| A PDF has no readable content | Upload a selectable-text PDF; image-only scans are not supported. |
| Materials need review again | Check whether the document version, job source, candidate facts, or preferences changed. |
| A scheduled search did not run | Check the schedule's timezone, enabled state, and whether the local server was running. |

For installation and environment problems, see [Configuration](configuration.md).

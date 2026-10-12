# Stage 1 sources ? implementation and validation

Fixed no-new-failures base: `3a23ea0086783224375d1140902891dac93b7b4e`
(the HEAD specified at task start). The reviewer result at `3b8d062`
(1959 passed, 132 skipped, zero failed) is historical context, not the diff base.

## Delivered behavior

Four GET-verified real boards, their counts/dates, anonymized scope derivation and
all coverage gaps are recorded in [the coverage report](board-directory-coverage-2026-10-11.md).
There are no synthetic entries in production. The executable schema is
`BoardEntry`; `load_directory` validates entries and duplicate identities.
The refresh CLI is dry-run by default; successful GETs update observed coverage,
UTC date and count. An empty valid response records zero and removes old coverage
labels. Failures preserve the old verification date and are flagged. Workday
explicit searches remain available, but the POST listing cannot satisfy GET-only
verification and is not falsely added to the directory.

`search_jobs(use_directory=true)` preserves tool names/order and chooses fresh
boards by role/location. The existing board parsing, role-term and location
filters and seniority warnings remain authoritative. The prompt prefers directory
selection after requested sources are blocked and labels explicit tokens as
unverified. All recommendations still require read, `posting_qualification`,
`search_policy.opening_level`, import, actual score and explicit recommendation.
No eligibility threshold or acceptance evaluator was changed.

Candidate persistence and directory aggregation share `job_key`. Repeated directory
queries return cached no-new-evidence; the existing task-host identity rule also
handles differently worded searches yielding the same candidates. Source health
records success/empty/HTTP-error with timestamps in the current turn and a durable
latest outcome/consecutive-error history across turns. A 404 or repeated error
excludes the board for that turn and flags it for the refresh CLI's health input.
Browser observations preserve this history.

Each discovery instance lazily owns one shared HTTPX client, closed on harness
shutdown. Public HTTPX APIs alone are used: no SDK internals are replaced or
bypassed. Redirects remain manual and each target is validated; `trust_env=False`
and `follow_redirects=False` remain in effect, and a public request hook prevents
server cookies being resent across reads. API hosts are serial with a configurable
minimum interval, with at most three simultaneous requests across hosts. Directory
fan-out is sequential and capped at five boards. No new HTML parallelism or
challenge bypass is introduced. Explicit and directory board searches observe
context-local cancellation before requests, while waiting for slots/host limits,
and between chunks. An already blocked synchronous read is bounded by the existing
20-second HTTP timeout; cancellation cannot preempt that socket read immediately.

See [configuration](../configuration.md#verified-company-board-discovery) for both
new environment settings and refresh commands.

## Offline business replay

`tests/test_b6_offline_replay.py`, its frozen archive, and
`scripts/remaining_search_acceptance.py` are unchanged from the fixed base.
New tests reuse the frozen transport and real production task loop. Directory
metadata is explicitly synthetic and test-only. The positive case preserves
recorded board responses and adds a test-only projection of the archived GoodApple
posting to the already synthetic board link list; it does not claim that this
projection was a real public response. Both posting bodies still pass the original
read/import/score/recommend and acceptance paths.

- Positive directory recovery: **2 qualifying recommendations**, unchanged
  `evaluate_search` passes, LinkedIn access restriction disclosed, persisted scores
  retained, repeated directory search is no-new-evidence, zero provider calls.
- Negative directory recovery: **0 recommendations**, completed honestly with the
  two-position shortfall and blocked sources disclosed. Acceptance reports only
  `fewer_than_two_verified_scored_qualifying_recommendations`, as intended.
- Final focused run: **24 passed, 1 skipped**. Skip: opt-in paid model lane.
  Evidence: `.codex-runs/b6-evidence/focused-verified.log` and `focused.xml`.

A new test initially allowed the resume-save fixture's default background analysis
warmup to reach the replay network guard. The guard rejected it. The new fixture
now disables warmup before setup; the original guard was not changed. Both final
full runs also explicitly disable `JOB_AGENT_ANALYSIS_WARMUP` and remove live/paid
opt-ins. No live model test was enabled.

## Full regression environment

Python: repository `.venv/Scripts/python.exe`. Pytest arguments: `-q -ra
-p no:cacheprovider`, an isolated `--basetemp`, and JUnit XML. The fixed base is
exported with `git archive` and extracted via the standard Python `tarfile` API
into `.codex-runs/b6-evidence/base-tree/`; it is not a mutable checkout of the
implementation. Base and implementation use the same interpreter, process-local
offline settings and test runner. Scratch evidence is under the user-authorized
`.codex-runs/b6-evidence/`, not the inaccessible `tmp/`.

Windows Python 3.13 creates restrictive 0700 temporary directories in this sandbox.
The evidence-only runner uses 0777 for newly created directories strictly beneath
its evidence root, allowing inherited ACLs. No existing ACL, SDK internals,
production test, skip marker, threshold or acceptance code is changed. This
bootstrap is not part of the shipped implementation. Windows named-pipe failures
are compared and listed rather than patched or skipped. Initial interrupted runs
are exploratory and are not counted as final regression results.

Final full-suite results and the per-test skip/failure comparison follow below.

## Delivery

Implementation commit: `8b11a10c53aa412a5c35a3453d90e5537936f2e8`.
Documentation/validation is a separate follow-up commit at the bundle branch tip.
The main repository's `.git` is read-only under the supplied permission profile;
commits were created in `.codex-runs/b6-evidence/submission.git` with an index over
the shared worktree, using explicit file paths only. No ACL changes or push.
The final incremental bundle is `.codex-runs/b6-evidence/stage-1-sources.bundle`,
branch `stage-1-sources`, with the fixed base as prerequisite. Main-worktree source
changes remain visible; a bundle is not a claim that the main branch moved.

The three untracked `docs/benchmarks/main-stability-LIVE-sample-20261011*`
directories remain untracked and are not in either commit. No manual inspection or modification of `.env` or `tmp/` was performed;
existing test code retains its normal model-configuration initialization. Evidence-only runners, logs, scratch files and local database
contents are not included in the submission commits.

## Final regression comparison
- Fixed base: **12 failed, 1943 passed, 132 skipped, 1 warning, 4 errors, 4 subtests passed in 1340.08s (0:22:20)**.
- Implementation: **9 failed, 1964 passed, 132 skipped, 1 warning, 4 errors, 4 subtests passed in 1368.60s (0:22:48)**.
- New failures: **0**; added skips: **0**; changed skip reasons: **0**.

Evidence: `.codex-runs/b6-evidence/offline-base.log|xml`, `offline-full.log|xml`, `comparison.json`.

### Full-run failures (not modified or skipped)

- `tests.test_auto_apply_review_fixes.ChromeChecks::test_confirmation_negative_and_positive_pages` — both runs; error: Windows named-pipe CreateFile / WinError 5.
- `tests.test_auto_apply_review_fixes.ChromeChecks::test_one_submit_click_then_confirmation` — both runs; error: Windows named-pipe CreateFile / WinError 5.
- `tests.test_auto_apply_review_fixes.ChromeChecks::test_real_standard_answer_form_only_sends_edits` — both runs; error: Windows named-pipe CreateFile / WinError 5.
- `tests.test_auto_apply_review_fixes.ChromeChecks::test_success_url_without_a_receipt_is_not_confirmation` — both runs; error: Windows named-pipe CreateFile / WinError 5.
- `tests.test_browser_runtime_recovery::test_changed_url_and_control_refresh_without_replaying_old_action` — both runs; failure: Windows named-pipe CreateFile / WinError 5.
- `tests.test_browser_runtime_recovery::test_closed_chrome_during_creation_recovers_once_with_actual_observation` — both runs; failure: Windows named-pipe CreateFile / WinError 5.
- `tests.test_browser_runtime_recovery::test_parallel_context_owner_and_last_task_close` — both runs; failure: Windows named-pipe CreateFile / WinError 5.
- `tests.test_browser_runtime_recovery::test_repeated_transport_failure_remains_error_not_site_block` — both runs; failure: Windows named-pipe CreateFile / WinError 5.
- `tests.test_general_repairs::test_import_uses_observed_posting_instead_of_task_instruction` — base only; failure: ValueError: Set LLM_MODEL_ID in the environment or project's .env file..
- `tests.test_general_repairs::test_job_quote_cannot_override_observed_web_even_when_verbatim` — base only; failure: AssertionError: Regex pattern did not match.   Expected regex: 'not identifiable'   Actual message: "Set LLM_MODEL_ID in the environment or project's .env file.".
- `tests.test_mcp_app::test_fastapi_lifecycle_health_effective_tools_and_snapshot` — both runs; failure: Windows named-pipe CreateFile / WinError 5.
- `tests.test_mcp_runtime::test_local_stdio_server_end_to_end_persists_both_tools` — both runs; failure: AssertionError: assert <ToolExecutio...IED: 'denied'> == <ToolExecutio...: 'completed'>      - completed   + denied.
- `tests.test_mcp_runtime::test_one_stdio_connection_supports_two_concurrent_session_calls` — both runs; failure: Windows named-pipe CreateFile / WinError 5.
- `tests.test_mcp_runtime::test_stdio_call_uses_owned_thread_boundary_from_running_event_loop` — both runs; failure: Windows named-pipe CreateFile / WinError 5.
- `tests.test_mcp_runtime::test_timed_out_stdio_connection_is_not_reused` — both runs; failure: Windows named-pipe CreateFile / WinError 5.
- `tests.test_remaining_phase4::test_blocked_remote_source_does_not_prevent_literal_authorized_jd_import` — base only; failure: ValueError: Set LLM_MODEL_ID in the environment or project's .env file..

The three base-only failures are constructor configuration failures: `git archive`
excludes the untracked `.env`, and the tests mock semantic classification but still
initialize its model object. They are not claimed as fixes. A focused follow-up
used identical synthetic `LLM_MODEL_ID`, `LLM_API_KEY` and an `.invalid` base URL
on both sides, with a fail-closed guard on the application's provider-call boundary.
Both base and implementation produced **3 passed**, with zero provider-call attempts.
Evidence: `constructor-base.log|xml`, `constructor-head.log|xml` under the evidence
root. No SDK internals were replaced. Raw full-suite counts above are retained;
the follow-up does not silently rewrite them.

Of the 13 common sandbox failures/errors, **12 directly contain named-pipe
CreateFile / WinError 5**. The remaining local-stdio end-to-end test reports denied
rather than completed because optional server tools are unavailable; its attribution
to the same pipe-startup restriction is an inference supported by the companion
stdio startup failures, not a direct CreateFile traceback in that assertion.
The reviewer must still run the full suite outside the sandbox. The gate here is
**no new failures**, not an assertion that the sandbox suite is all green.

### Every skipped test and reason

- `tests.test_account_browser::test_email_first_then_password_only_without_requesting_credentials_again` — Offline Chrome opt-in
- `tests.test_account_browser::test_generic_username_and_unfamiliar_submit_button` — Offline Chrome opt-in
- `tests.test_account_browser::test_job_form_email_is_not_treated_as_login` — Offline Chrome opt-in
- `tests.test_account_browser::test_model_can_resolve_structural_ambiguity_without_page_or_credentials` — Offline Chrome opt-in
- `tests.test_account_browser::test_model_cannot_target_final_application_submission` — Offline Chrome opt-in
- `tests.test_account_browser::test_new_consent_on_second_step_pauses_before_credential_submission` — Offline Chrome opt-in
- `tests.test_account_browser::test_password_only_frame_on_existing_site_is_detected` — Offline Chrome opt-in
- `tests.test_account_browser::test_pausing_during_model_selection_prevents_credential_fill` — Offline Chrome opt-in
- `tests.test_account_browser::test_persistent_account_heading_after_login_does_not_block_application` — Offline Chrome opt-in
- `tests.test_account_browser::test_single_password_registration_and_email_button_are_supported` — Offline Chrome opt-in
- `tests.test_account_browser::test_verification_is_not_mistaken_for_another_password_request` — Offline Chrome opt-in
- `tests.test_account_browser::test_wrong_credentials_are_not_retried_and_password_is_cleared` — Offline Chrome opt-in
- `tests.test_auto_apply_browser::test_actual_browser_agent_repairs_keyboard_only_field_after_autofill` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_answering_during_background_work_keeps_focus_and_sends_one_batch` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_browser_rejects_different_posting_and_ignores_job_description_thanks` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_checkbox_observation_includes_the_actual_privacy_question` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_compact_chat_reply_fills_real_controls_without_model` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_duplicate_city_suggestions_select_once_and_repeated_fill_does_not_reopen` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_generic_page_control_opens_details_but_cannot_send_form_or_toggle_consent` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_greenhouse_react_select_hidden_inputs_and_attach_label` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_lever_location_requires_a_selected_suggestion` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_lever_required_checkbox_group_does_not_require_every_option` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_numbered_city_clarification_fills_real_controls_without_model[comma_region-combobox]` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_numbered_city_clarification_fills_real_controls_without_model[comma_region-select]` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_numbered_city_clarification_fills_real_controls_without_model[numbered-combobox]` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_numbered_city_clarification_fills_real_controls_without_model[numbered-select]` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_numbered_city_clarification_fills_real_controls_without_model[shrunk_comma-combobox]` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_numbered_city_clarification_fills_real_controls_without_model[shrunk_comma-select]` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_numbered_city_clarification_fills_real_controls_without_model[shrunk_numbered-combobox]` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_numbered_city_clarification_fills_real_controls_without_model[shrunk_numbered-select]` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_paused_browser_keeps_dispatching_background_requests` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_readonly_portal_dropdown_and_replaced_dom_nodes` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_real_browser_form_resume_question_and_confirmation[https://job-boards.greenhouse.io/example/jobs/123]` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_real_browser_form_resume_question_and_confirmation[https://jobs.lever.co/example/abc123]` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_searching_an_open_dropdown_does_not_toggle_it_closed` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_slow_tracking_resource_does_not_prevent_using_loaded_form` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_browser::test_web_application_flow_with_actual_api_and_offline_employer` — Set JOB_AGENT_BROWSER_TESTS=1 to run offline Chrome integration tests.
- `tests.test_auto_apply_candidate::test_chat_ui_restores_resume_edits_education_and_batches_answers` — Opt-in real browser fixture
- `tests.test_auto_apply_candidate::test_two_education_rows_include_optional_details_and_do_not_refill` — Opt-in real browser fixture
- `tests.test_auto_apply_decisions::test_browser_exposes_relationships_errors_and_can_revalidate_after_correction` — Offline Chrome opt-in
- `tests.test_auto_apply_decisions::test_category_selection_can_reveal_a_separate_dependent_field` — Offline Chrome opt-in
- `tests.test_auto_apply_decisions::test_text_shaped_hierarchical_picker_category_then_leaf_without_reasking[False]` — Offline Chrome opt-in
- `tests.test_auto_apply_decisions::test_text_shaped_hierarchical_picker_category_then_leaf_without_reasking[True]` — Offline Chrome opt-in
- `tests.test_auto_apply_decisions::test_workday_style_degree_mapping_uses_confirmed_profile_then_survives_autofill` — Offline Chrome opt-in
- `tests.test_auto_apply_drafting::test_resume_draft_ui_edits_and_sends_through_real_api` — Opt-in offline Chrome UI test
- `tests.test_auto_apply_optional::test_optional_demographic_controls_render_and_fill_real_dropdowns` — Opt-in offline Chrome integration test
- `tests.test_auto_apply_reliability::test_closed_popup_returns_to_the_application_tab` — Offline Chrome opt-in
- `tests.test_auto_apply_reliability::test_generic_confirmation_is_only_accepted_after_submitting` — Offline Chrome opt-in
- `tests.test_auto_apply_reliability::test_offscreen_window_is_shown_without_reloading` — Offline Chrome opt-in
- `tests.test_auto_apply_resume::test_duplicate_new_chat_opens_cancelled_attempt_and_resume_works` — Opt-in offline Chrome UI test
- `tests.test_auto_apply_visual::test_clicks_cannot_submit_or_grant_unknown_consent` — Offline Chrome opt-in
- `tests.test_auto_apply_visual::test_css_pixel_dimensions_and_coordinate_bounds` — Offline Chrome opt-in
- `tests.test_auto_apply_visual::test_failed_dom_action_automatically_gives_model_screenshot_and_tools` — Offline Chrome opt-in
- `tests.test_auto_apply_visual::test_hover_scroll_drag_and_keyboard_use_the_same_screenshot_space` — Offline Chrome opt-in
- `tests.test_auto_apply_visual::test_old_coordinates_rejected_after_dom_change_scroll_and_dom_action` — Offline Chrome opt-in
- `tests.test_auto_apply_visual::test_roleless_hierarchical_menu_completed_by_pixels_with_feedback` — Offline Chrome opt-in
- `tests.test_auto_apply_visual::test_screenshot_coordinates_reach_iframe_target` — Offline Chrome opt-in
- `tests.test_auto_apply_visual::test_secret_page_and_disabled_visual_mode_do_not_capture` — Offline Chrome opt-in
- `tests.test_auto_apply_visual::test_typing_uses_source_and_enter_cannot_implicitly_submit` — Offline Chrome opt-in
- `tests.test_auto_apply_visual::test_visual_images_stop_after_returning_to_dom_and_capture_once` — Offline Chrome opt-in
- `tests.test_auto_apply_visual::test_visual_navigation_keeps_host_missing_answer_and_review_checks` — Offline Chrome opt-in
- `tests.test_auto_apply_workday::test_job_to_login_to_multipage_review_and_single_submit` — Offline Chrome opt-in
- `tests.test_auto_apply_workday::test_login_state_reused_by_same_owner_only` — Offline Chrome opt-in
- `tests.test_auto_apply_workday::test_registration_explicit_consent_and_password_exclusion` — Offline Chrome opt-in
- `tests.test_auto_apply_workday::test_secure_account_ui_keeps_password_out_of_chat_and_clears_input` — Offline Chrome opt-in
- `tests.test_auto_apply_workday::test_workday_visible_submit_surface_and_header_are_disambiguated` — Offline Chrome opt-in
- `tests.test_b6_offline_replay::test_b6_frozen_web_with_configured_model` — Opt-in paid model against frozen B6 web; never run by offline validation
- `tests.test_browser_job_search::test_browser_search_capture_score_and_recommend_uses_selected_job_only` — Offline Chrome opt-in
- `tests.test_browser_visibility::test_activity_panel_only_opens_window_on_explicit_button_click` — Offline Chrome opt-in
- `tests.test_browser_visibility::test_default_is_headless_and_only_explicit_handoff_requests_a_window[application]` — Offline Chrome opt-in
- `tests.test_browser_visibility::test_default_is_headless_and_only_explicit_handoff_requests_a_window[browse]` — Offline Chrome opt-in
- `tests.test_browser_visibility::test_failed_window_launch_keeps_original_browser_alive` — Offline Chrome opt-in
- `tests.test_career_browser::test_chat_surfaces_model_outage_and_recovers_a_greeting` — Opt-in offline Chrome integration.
- `tests.test_career_browser::test_default_chat_searches_scores_reviews_applies_and_interviews[home]` — Opt-in offline Chrome integration.
- `tests.test_career_browser::test_default_chat_searches_scores_reviews_applies_and_interviews[saved_job]` — Opt-in offline Chrome integration.
- `tests.test_career_browser::test_general_browsing_without_resume_has_preview_in_existing_chat` — Opt-in offline Chrome integration.
- `tests.test_career_browser::test_rendered_browser_evidence_flows_into_saved_job` — Opt-in offline Chrome integration.
- `tests.test_career_flow::test_configured_model_directs_real_career_tools_with_synthetic_sources` — Opt-in configured model; synthetic resume and local tool IO only.
- `tests.test_career_timeline_browser::test_result_cards_are_chronological_after_reply_poll_and_reload[1440-light]` — Opt-in offline Chrome
- `tests.test_career_timeline_browser::test_result_cards_are_chronological_after_reply_poll_and_reload[1440-night]` — Opt-in offline Chrome
- `tests.test_career_timeline_browser::test_result_cards_are_chronological_after_reply_poll_and_reload[390-light]` — Opt-in offline Chrome
- `tests.test_career_timeline_browser::test_result_cards_are_chronological_after_reply_poll_and_reload[390-night]` — Opt-in offline Chrome
- `tests.test_chat_typography::test_chat_markdown_readability_copy_and_untrusted_content[1440]` — Opt-in offline Chrome integration.
- `tests.test_chat_typography::test_chat_markdown_readability_copy_and_untrusted_content[390]` — Opt-in offline Chrome integration.
- `tests.test_general_browser::test_browser_can_inspect_embedded_content` — Offline Chrome opt-in
- `tests.test_general_browser::test_control_cannot_change_into_submit_after_observation` — Offline Chrome opt-in
- `tests.test_general_browser::test_final_send_credentials_consent_and_private_url_stay_guarded` — Offline Chrome opt-in
- `tests.test_general_browser::test_hash_routes_are_not_stripped_from_browser_urls` — Offline Chrome opt-in
- `tests.test_general_browser::test_home_search_cross_site_back_and_tabs` — Offline Chrome opt-in
- `tests.test_general_browser::test_job_control_search_matches_title_and_company_across_card_text` — Offline Chrome opt-in
- `tests.test_general_browser::test_job_panels_can_be_read_and_scrolled_independently` — Offline Chrome opt-in
- `tests.test_general_browser::test_local_editor_dropdown_and_toggle_need_no_candidate_profile` — Offline Chrome opt-in
- `tests.test_general_browser::test_login_overlay_can_be_dismissed_without_exposing_account_contents` — Offline Chrome opt-in
- `tests.test_general_browser::test_long_pages_expose_late_controls_and_text` — Offline Chrome opt-in
- `tests.test_general_browser::test_searches_remain_available_inside_application_worker` — Offline Chrome opt-in
- `tests.test_general_browser::test_shadow_controls_delayed_content_and_recovery_from_stale_ref` — Offline Chrome opt-in
- `tests.test_general_browser::test_visual_capture_blocks_email_only_login_and_coordinate_submission` — Offline Chrome opt-in
- `tests.test_general_browser::test_visual_click_operates_unlabelled_custom_dom_and_checks_freshness` — Offline Chrome opt-in
- `tests.test_job_alerts_browser::test_chat_discovery_and_daily_alerts_share_ui_without_forcing_schedule` — Offline Chrome opt-in
- `tests.test_job_alerts_browser::test_repaired_forge_and_weekday_editor_in_day_night_desktop_mobile` — Offline Chrome opt-in
- `tests.test_remaining_account_browser::test_control_enter_navigation_frame_and_end` — Opt-in offline Chrome
- `tests.test_remaining_account_browser::test_shared_login_same_owner_host_only_and_stale_close_cannot_erase` — Opt-in offline Chrome
- `tests.test_remaining_account_ui::test_account_banner_shared_login_and_takeover_navigation_full_chain` — Offline Chrome UI opt-in
- `tests.test_remaining_cover_style::test_real_cover_letter_preserves_source_citations_and_specific_natural_opening` — Explicit paid real cover-letter generation and grounding review
- `tests.test_remaining_cover_style::test_real_original_failure_revision_with_frozen_provenance` — Only the unexecuted original-failure revision lane; no writer repeat
- `tests.test_remaining_interview_async_ui::test_current_question_and_late_feedback_binding_in_real_chrome` — Local Chrome UI opt-in
- `tests.test_remaining_interview_feedback::test_real_main_chat_feedback_latency[agent-30]` — Explicit paid real feedback latency check
- `tests.test_remaining_interview_feedback::test_real_main_chat_feedback_latency[fast-10]` — Explicit paid real feedback latency check
- `tests.test_remaining_job_body::test_existing_alert_filtered_views_do_not_reset_real_taskhost_progress` — Offline Chrome opt-in
- `tests.test_remaining_job_body::test_location_keeps_work_mode_only_from_the_target_header[Remote]` — Offline Chrome opt-in
- `tests.test_remaining_job_body::test_location_keeps_work_mode_only_from_the_target_header[]` — Offline Chrome opt-in
- `tests.test_remaining_job_body::test_page_source_hash_ignores_region_and_navigation_views_but_tracks_real_changes` — Offline Chrome opt-in
- `tests.test_remaining_job_body::test_real_chrome_job_only_excludes_other_company_and_footer[False]` — Offline Chrome opt-in
- `tests.test_remaining_job_body::test_real_chrome_job_only_excludes_other_company_and_footer[True]` — Offline Chrome opt-in
- `tests.test_remaining_job_body::test_saved_real_indeed_body_and_detail_action_are_consumable` — Explicit saved real public-page replay
- `tests.test_remaining_job_body::test_split_detail_nested_body_metadata_and_region_survive_filtered_reads` — Offline Chrome opt-in
- `tests.test_remaining_live::test_long_real_search_conversations[analyst-junior data analyst in New York]` — Explicit paid real-model/public research check
- `tests.test_remaining_live::test_long_real_search_conversations[backend-senior backend engineer, remote US]` — Explicit paid real-model/public research check
- `tests.test_remaining_live::test_long_real_search_conversations[designer-junior UX designer, Austin]` — Explicit paid real-model/public research check
- `tests.test_remaining_live::test_long_real_search_conversations[student-machine learning internship, California]` — Explicit paid real-model/public research check
- `tests.test_remaining_live_batch::test_eight_job_production_cold_resolver_and_persistent_warm` — Explicit real-provider batch performance opt-in
- `tests.test_remaining_live_body::test_original_python_posting_scoring_is_isolated_from_related_companies` — Explicit paid Jev check
- `tests.test_remaining_mock_browser::test_review_remember_submit_second_job_and_restart[False]` — Opt-in offline real Chrome
- `tests.test_remaining_mock_browser::test_review_remember_submit_second_job_and_restart[True]` — Opt-in offline real Chrome
- `tests.test_remaining_phase4_chrome::test_actual_failure_challenge_wording_is_blocked_and_recovery_pending_restores_after_control` — Local Chrome opt-in
- `tests.test_remaining_phase4_chrome::test_user_control_refreshes_actual_blocked_cache_before_agent_read` — Local Chrome opt-in
- `tests.test_remaining_polish_ui::test_search_title_chronicle_and_cancel_state_in_real_ui` — Offline real Chrome opt-in
- `tests.test_skill_runtime::test_symlinks_are_rejected` — Symlink creation is unavailable on this platform.
- `tests.test_speed_pipeline::test_known_three_page_application_needs_zero_model_calls[https://example.wd5.myworkdayjobs.com/en-US/Careers/job/Speed-Test_R123]` — Opt-in real Chrome
- `tests.test_speed_pipeline::test_known_three_page_application_needs_zero_model_calls[https://job-boards.greenhouse.io/example/jobs/123]` — Opt-in real Chrome
- `tests.test_speed_pipeline::test_known_three_page_application_needs_zero_model_calls[https://jobs.lever.co/example/speed-test]` — Opt-in real Chrome
- `tests.test_speed_pipeline::test_worker_chrome_is_shared_but_contexts_are_isolated` — Opt-in real Chrome

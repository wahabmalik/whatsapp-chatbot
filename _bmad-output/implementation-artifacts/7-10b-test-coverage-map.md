# Story 7.10: Test Coverage Map and Epic Baseline Test Count Artifact

Status: ready-for-dev

## Story

As a sprint reviewer and future developer,
I want a test coverage map linking each Epic 7 story's acceptance criteria to the test file and test class that verifies it, plus a recorded baseline pytest pass count at epic open and close,
so that sprint reviewers can audit AC-to-test traceability without cross-referencing multiple files, and so future epics have a numeric baseline to measure against.

## Acceptance Criteria

1. A `test-coverage-map.md` artifact is created at `_bmad-output/implementation-artifacts/test-coverage-map.md` containing a Markdown table with columns: **Story Key | AC Reference | Test File | Test Class / Function | Notes**.
2. Every Epic 7 story (7-1 through 7-8) has at least one row in the table mapping its primary acceptance criterion to the concrete test file and test class or function that verifies it.
3. The coverage map includes a **Baseline Test Count** section recording:
   - The total `pytest` pass count at Epic 7 open (estimated from the last Epic 6 close count available in `epic-6-retro-2026-05-02.md` or reconstructed from git)
   - The total `pytest` pass count at the time this story is closed (run `pytest -q` and capture the summary line)
4. No production source code is modified. This story creates documentation artifacts only.
5. The baseline test count is captured using the project's existing virtualenv (`pytest -q`) and the result summary line is reproduced verbatim in the coverage map.

## Tasks / Subtasks

- [ ] Create `_bmad-output/implementation-artifacts/test-coverage-map.md` (AC: 1, 2)
  - [ ] Add table header row: Story Key | AC Reference | Test File | Test Class / Function | Notes
  - [ ] Add one or more rows for each of 7-1 through 7-8 from completed story files
  - [ ] Cross-reference each entry against the actual test file to confirm the class/function name is correct
- [ ] Populate Baseline Test Count section (AC: 3, 5)
  - [ ] Retrieve Epic 6 closing test count from `epic-6-retro-2026-05-02.md` or `test-results.txt`
  - [ ] Run `pytest -q` in the project virtualenv and capture the summary line
  - [ ] Record both counts in the Baseline Test Count section
- [ ] Verify no production files were touched — diff should show only the new `.md` artifact (AC: 4)

## Dev Notes

- **This is a documentation-only story.** The only file created is `_bmad-output/implementation-artifacts/test-coverage-map.md`. No `app/`, `tests/`, or config files are modified.
- The table entries for 7-1 through 7-8 can be derived directly from the completed story files in `_bmad-output/implementation-artifacts/`. Each story's **Changes** section lists the exact test file and test class added.
- The `pytest -q` baseline run should be executed against the full test suite with no filtering flags so the count is representative. The summary line format is typically: `N passed in X.XXs`.
- The Epic 6 closing test count is documented in `_bmad-output/implementation-artifacts/epic-6-retro-2026-05-02.md` under "Test Suite Signal at Epic Close" — use those test files to infer the approximate pass count if an explicit number is not stated. Alternatively, check `test-results.txt` at repo root.
- **Non-scope boundary:** Do not add new pytest tests, modify architecture.md, or change any production path. If coverage gaps are observed during table construction, note them in the "Notes" column of the map rather than fixing them in this story.

### Project Structure Notes

- Output artifact: `_bmad-output/implementation-artifacts/test-coverage-map.md`
- No changes to `app/`, `tests/`, `_bmad-output/planning-artifacts/`, or any `.py` file
- Run command: `.venv\Scripts\python.exe -m pytest -q` (Windows virtualenv) — do not use `pytest` bare since the venv must be active

### References

- Epic 6 retro carry-forward actions table: [_bmad-output/implementation-artifacts/epic-6-retro-2026-05-02.md](_bmad-output/implementation-artifacts/epic-6-retro-2026-05-02.md) — action rows 3 and 4
- Completed story 7-1 through 7-8 for table row source data: `_bmad-output/implementation-artifacts/7-[1-8]-*.md`
- Test files currently in scope: `tests/test_sprint_status_integrity.py`, `tests/test_operational_route_inventory.py`, `tests/test_operator_template_url_contract.py`, `tests/test_docs_runtime_endpoint_contract.py`, `tests/test_reliability.py`, `tests/test_retry_escalation_contract.py`, `tests/test_wa_id_propagation_contract.py`, `tests/test_deferred_delivery_observability.py`

## Dev Agent Record

### Agent Model Used

_to be filled by dev agent_

### Debug Log References

_none anticipated — documentation-only story_

### Completion Notes List

_to be filled by dev agent_

### File List

- `_bmad-output/implementation-artifacts/test-coverage-map.md` (CREATE)

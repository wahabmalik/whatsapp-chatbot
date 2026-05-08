# Story 7.3: Operator Template url_for Contract Test

## Status
Done

## Summary
Added a contract test that prevents hardcoded absolute URL paths in operator-facing templates and removed the remaining hardcoded absolute path.

## Implemented
- New test file: `tests/test_operator_template_url_contract.py`
- Contract asserts no `href="/..."`, `action="/..."`, or `data-...="/..."` literals in operator templates.
- Updated `app/templates/agents-enhanced.html` to remove a hardcoded absolute docs path.

## Validation
- `pytest tests/test_operator_template_url_contract.py -q`
- Result: 1 passed

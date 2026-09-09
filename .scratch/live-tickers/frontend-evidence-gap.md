# Frontend acceptance evidence gaps

Code corrections are mostly accepted. Existing browser_acceptance.py is insufficient evidence for several claims. Own frontend and frontend evidence only; fix code only if actual verification uncovers a bug.

1. Override/reset currently sleeps and prints PASS without asserting value or request count. Capture original response, POST body with PE=35, changed returned PE base price, and one reset GET without /reset suffix. Assert every override control is cleared and defaults restored. Simulate429/503 reset response, assert exactly one request and correct visible status.
2. Current timeout test immediately aborts route, so it tests network failure rather than the 45-second application deadline. Test the actual timeout handler. Also test delayed response body after headers, where the original cleanup bug existed. Use controllable fetch mocks loading the actual API module, or a local streaming test server; shorten timers in the test harness only if necessary. Assert TIMEOUT, canceled signals and eventual settlement, not any broad error text.
3. Include a delayed old ticker request resolved/rejected after switching to a new ticker. Assert the current company and error/loading state remain correct. Test cancellation while decoding JSON body.
4. Current script no longer contains AAPL/MSFT tests but completion claims them. Restore actual live AAPL/MSFT queries and preserve current evidence. Do not reuse old screenshots as proof for new code.
5. Preserve stdout and exit codes in a new frontend-verification-final report plus exact assertions and actual evidence paths. Explicitly mark unmet checks. Read coordinator-verification-plan.md. The backend is still correcting data consistency, so do not assert all4 models must always be available.

When backend is ready, coordinate final live smoke on production build. No commits. Use same model/full access. Report honestly: no broad 'nothing remains' claims unsupported by concrete checks.

Bump: patch

Pytest gives each Python test 630 seconds for fixture setup, the test body, and teardown. If the test hangs, pytest reports the timeout with a traceback and continues. Collection and session startup run before the timer starts.

Release steps: none.

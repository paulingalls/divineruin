Bump: patch

Pytest gives each Python test 630 seconds for fixture setup, the test body and teardown. A test that hangs in a sync call or an idle await fails with a timeout traceback, and the run goes on. A hang that keeps the asyncio loop busy can swallow that timeout. At twice the bound, a backstop dumps every thread's stack and ends the process. Under xdist only that worker ends, and the run reports the test as crashed. Collection and session startup run before the timer starts.

Release steps: none.

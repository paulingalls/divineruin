"""Actual image CMD must reject incomplete production configuration before readiness."""

import subprocess


def run(h, image, settings):
    values = dict(settings, EMAIL_TRANSPORT="mock", DATABASE_URL="", RESEND_API_KEY="", GEMINI_API_KEY=" ")
    envfile = h.tmp / "invalid.env"
    envfile.write_text("".join(name + "=" + value + "\n" for name, value in values.items()))
    container = h.command(["docker", "create", "--network", "none", "--env-file", str(envfile), image], capture=True)
    h.exports.append(container)
    h.command(["docker", "start", container])
    result = subprocess.run(
        ["docker", "wait", container], env=h.env, capture_output=True, text=True, timeout=25, check=True
    )
    assert int(result.stdout.strip()) != 0, "incomplete production image started"
    output = h.command(["docker", "logs", container], capture=True, merged=True)
    for name in ("DATABASE_URL", "RESEND_API_KEY", "GEMINI_API_KEY", "EMAIL_TRANSPORT"):
        assert name in output, (name, output)
    assert "mock" in output and "Server running" not in output
    h.command(["docker", "rm", container])
    h.exports.remove(container)
    print("image configuration refused all missing names and mock transport", flush=True)

"""Real worker writes, HTTP portrait generation, retained-volume recreation and CLI refusal."""

import base64
import hashlib
import json
import subprocess
import urllib.request

ROOT = "/var/lib/divineruin/media"
SERVICES = ("server", "agent", "worker")


def configure(h, override):
    override["services"]["server"]["networks"] = ["default"]
    preload = h.tmp / "provider.ts"
    preload.write_text("""import { mock } from "bun:test";
const bytes = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64");
mock.module("/app/apps/server/src/image-provider.ts", () => ({requestImage: async () => bytes}));
""")
    preload.chmod(0o644)
    # Docker Desktop mounts the file itself; the private parent remains host-only.
    override["services"]["server"].update(
        command=["bun", "--preload", "/tmp/provider.ts", "src/index.ts"],
        volumes=[str(preload) + ":/tmp/provider.ts:ro"],
    )
    for service in ("agent", "worker"):
        override["services"][service]["command"] = [
            "python",
            "-c",
            "import time; time.sleep(600)",
        ]


def exec_python(h, service, code):
    return h.command([*h.compose, "exec", "-T", service, "python", "-c", code], capture=True)


def fetch(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.headers, response.read()


def snapshot(h):
    result = {}
    for service in SERVICES:
        container = h.command([*h.compose, "ps", "-q", service], capture=True)
        info = h.inspect(container)
        mount = next(m for m in info["Mounts"] if m["Destination"] == ROOT)
        assert mount["Type"] == "volume"
        uid = h.command([*h.compose, "exec", "-T", service, "id", "-u"], capture=True)
        assert uid == "10001"
        result[service] = (info["Id"], info["Image"], mount["Name"], uid)
    assert len({item[2] for item in result.values()}) == 1
    print("media identities " + json.dumps(result), flush=True)
    return result


def bundled(h, url):
    headers, data = fetch(url + "/api/assets/images/companion_kael_primary")
    assert headers.get_content_type() == "image/png"
    assert data == (h.root / "assets/images/companion_kael_primary.png").read_bytes()
    assert (
        exec_python(
            h,
            "agent",
            """
import asyncio, os
from pathlib import Path
os.environ["ASYNC_AUDIO_DIR"] = "/tmp/retired-audio"
from prologue import PROLOGUE_PATH, audio_frames_from_file
assert Path(PROLOGUE_PATH).read_bytes() == Path("/app/assets/audio/prologue.mp3").read_bytes()
assert not Path("/var/lib/divineruin/media/portraits/companion_kael_primary.png").exists()
async def main():
    frames = audio_frames_from_file(PROLOGUE_PATH, sample_rate=24000, num_channels=1)
    try:
        frame = await anext(frames)
        assert frame.samples_per_channel > 0
    finally:
        await frames.aclose()
asyncio.run(main())
print("bundled playback decoded")
""",
        )
        == "bundled playback decoded"
    )


def worker_write(h):
    activity_id = "media_" + h.run_id
    h.bun(
        """const s = new Bun.SQL(process.env.DATABASE_URL);
const id = """
        + json.dumps(activity_id)
        + """;
const data = {player_id: id, activity_type: "crafting", status: "in_progress",
 resolve_at: "2099-01-01T00:00:00Z", outcome: {tier: "success"},
 narration_text: "A hammer rings.", narration_segments: [{character: "DM_NARRATOR", emotion: "neutral", text: "A hammer rings."}]};
await s`INSERT INTO players (player_id, data) VALUES (${id}, ${JSON.stringify({id})}::jsonb)`;
await s`INSERT INTO async_activities (id, player_id, data) VALUES (${id}, ${id}, ${data})`;
await s.close();"""
    )
    output = exec_python(
        h,
        "worker",
        """
import asyncio, base64, json
from pathlib import Path
import async_worker, db, db_activity_queries, tts_prerender
from llm_config import AUDIO_DIR
from media_dir import validate_media_dir
validate_media_dir()
audio = tts_prerender._generate_mp3_silence(0.1)
async def synthesize(*args, **kwargs):
    return audio
async def notification(*args, **kwargs):
    return "Ready."
tts_prerender.inworld_tts = synthesize
async_worker.generate_notification_hook = notification
async_worker.send_push_notification = notification
async def main():
    activity = await db_activity_queries.get_activity("""
        + repr(activity_id)
        + """)
    await async_worker._resolve_single_activity(activity)
    row = await db_activity_queries.get_activity(activity["id"])
    assert row["status"] == "resolved" and row["narration_audio_url"]
    data = (Path(AUDIO_DIR) / (activity["id"] + ".mp3")).read_bytes()
    print(json.dumps({"url": row["narration_audio_url"], "bytes": base64.b64encode(data).decode()}))
    await db.close_all()
asyncio.run(main())
""",
    )
    return json.loads(output.splitlines()[-1])


def startup_refusals(h, images, settings):
    # Every probe uses the actual image CMD, bounded by Docker stop only on harness failure.
    for service in SERVICES:
        image = images["server" if service == "server" else "agent"]
        entry = (
            []
            if service == "server"
            else ["python", "agent.py", "start"]
            if service == "agent"
            else ["python", "async_worker.py"]
        )
        cases = [
            ("unset", None, None),
            ("blank", "  ", None),
            ("missing", "/missing-media", None),
            ("readonly", ROOT, "root"),
        ]
        if service != "worker":
            cases += [("audio", ROOT, "audio"), ("portraits", ROOT, "portraits")]
        for label, value, readonly in cases:
            envfile = h.tmp / "probe.env"
            values = dict(settings, SERVER_URL="http://server:3001")
            values.pop("MEDIA_DIR", None)
            if value is not None:
                values["MEDIA_DIR"] = value
            envfile.write_text("".join(k + "=" + v + "\n" for k, v in values.items()))
            envfile.chmod(0o600)
            mounts = []
            volume = h.project + "_media"
            if readonly:
                mounts = [
                    "-v",
                    volume + ":" + ROOT + (":ro" if readonly == "root" else ""),
                ]
                if readonly != "root":
                    mounts += [
                        "--mount",
                        "type=bind,src=" + str(h.tmp / "readonly") + ",dst=" + ROOT + "/" + readonly + ",readonly",
                    ]
            container = h.command(
                [
                    "docker",
                    "create",
                    "--network",
                    "none",
                    "--env-file",
                    str(envfile),
                    *mounts,
                    image,
                    *entry,
                ],
                capture=True,
            )
            h.exports.append(container)
            h.command(["docker", "start", container])
            result = subprocess.run(
                ["docker", "wait", container],
                env=h.env,
                capture_output=True,
                text=True,
                timeout=25,
            )
            assert result.returncode == 0 and int(result.stdout.strip()) != 0, (
                service,
                label,
                result.stdout,
            )
            output = h.command(["docker", "logs", container], capture=True, merged=True)
            assert "MEDIA_DIR" in output, (service, label, output)
            assert "Server running" not in output and "Async worker starting" not in output
            assert "failed to connect to livekit" not in output
            h.command(["docker", "rm", container])
            h.exports.remove(container)
            print("startup refused " + service + " " + label, flush=True)


def run(h, images, settings):
    readonly = h.tmp / "readonly"
    readonly.mkdir()
    readonly.chmod(0o755)
    h.command([*h.compose, "up", "-d", "--no-deps", *SERVICES])

    def endpoint():
        return "http://127.0.0.1:" + h.command([*h.compose, "port", "server", "3001"], capture=True).rsplit(":", 1)[1]

    url = endpoint()
    h.ready(url)
    before = snapshot(h)
    bundled(h, url)
    narration = worker_write(h)
    headers, audio = fetch(url + narration["url"])
    assert headers.get_content_type() == "audio/mpeg" and audio
    assert audio == base64.b64decode(narration["bytes"])
    request = urllib.request.Request(
        url + "/api/images/generate",
        data=json.dumps(
            {
                "templateId": "npc_portrait",
                "vars": {"description": "A smith", "features": "Scarred hands"},
            }
        ).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Internal-Secret": settings["INTERNAL_SECRET"],
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        portrait = json.load(response)
    headers, png = fetch(url + portrait["url"])
    assert headers.get_content_type() == "image/png" and png
    # PNG IHDR is the actual processed output, not the provider's raw image.
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and (
        int.from_bytes(png[16:20], "big"),
        int.from_bytes(png[20:24], "big"),
    ) == (1024, 1024)
    row = json.loads(
        h.bun(
            """const s = new Bun.SQL(process.env.DATABASE_URL);
const [row] = await s`SELECT file_path FROM generated_assets WHERE id = ${"""
            + json.dumps(portrait["assetId"])
            + """}`;
console.log(JSON.stringify(row)); await s.close();"""
        )
    )
    assert row["file_path"] == ROOT + "/portraits/" + portrait["assetId"] + ".png"
    disk = h.command(
        [
            *h.compose,
            "exec",
            "-T",
            "server",
            "bun",
            "-e",
            "console.log(Buffer.from(await Bun.file("
            + json.dumps(row["file_path"])
            + ").arrayBuffer()).toString('base64'))",
        ],
        capture=True,
    )
    assert png == base64.b64decode(disk)
    h.command([*h.compose, "rm", "-s", "-f", *SERVICES])
    h.command([*h.compose, "up", "-d", "--no-deps", *SERVICES])
    url = endpoint()
    h.ready(url)
    after = snapshot(h)
    for service in SERVICES:
        assert before[service][0] != after[service][0] and before[service][1:] == after[service][1:]
    assert fetch(url + narration["url"])[1] == audio
    assert fetch(url + portrait["url"])[1] == png
    bundled(h, url)
    print(
        "retained bytes "
        + json.dumps(
            {
                "audio": hashlib.sha256(audio).hexdigest(),
                "portrait": hashlib.sha256(png).hexdigest(),
            }
        ),
        flush=True,
    )
    startup_refusals(h, images, settings)
    leftovers = exec_python(
        h,
        "agent",
        "from pathlib import Path; print([str(p) for p in Path('"
        + ROOT
        + "').rglob('*') if p.is_file() and p.name.startswith('.probe-')])",
    )
    assert leftovers == "[]"

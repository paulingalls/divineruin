#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ "${1:-}" == server && $# == 1 ]] || { echo 'usage: bash scripts/deploy-smoke.sh server' >&2; exit 2; }
source scripts/worktree-common.sh
wt_authorize connect
export SMOKE_DB="$DATABASE_URL" SMOKE_REDIS="$REDIS_URL" SMOKE_OWNER="$COMPOSE_PROJECT_NAME"
exec python3 - <<'PY'
import json
import os
import pathlib
import re
import shutil
import signal
import socket
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

root = pathlib.Path.cwd()
run_id = uuid.uuid4().hex[:12]
project = 'dr-smoke-' + os.environ['WT_CHECKOUT_ID'] + '-' + run_id
name = 'smoke_' + run_id
key = name + ':sentinel'
tmp = pathlib.Path(tempfile.mkdtemp(prefix='dr-smoke-'))
os.chmod(tmp, 0o700)
children = []
created_db = False
compose_started = False
sentinel = False
exports = []
log = open(tmp / 'run.log', 'w+')
env = dict(os.environ)
base_db = env['SMOKE_DB']
base_redis = env['SMOKE_REDIS']
fixture_db = urllib.parse.urlsplit(base_db)._replace(path='/' + name).geturl()
private_values = [base_db, base_redis, fixture_db]
env.update(DEPLOY_ENV_FILE=str(tmp / 'runtime.env'), DEPLOY_HTTP_PORT='0')
compose = ['docker', 'compose', '-p', project, '-f', str(root / 'deploy/compose.yml'), '-f', str(tmp / 'override.json')]

def command(args, *, capture=False, input=None, settings=None):
    result = subprocess.run(args, input=input, text=True, env=settings or env,
                            stdout=subprocess.PIPE if capture else log, stderr=log, timeout=300)
    if result.returncode:
        raise RuntimeError(f'{args[0:2]} exited {result.returncode}; see smoke log')
    return result.stdout.strip() if capture else None

def authorize():
    command(['bash', '-c', 'source scripts/worktree-common.sh; wt_authorize connect; wt_validate_resources "$COMPOSE_PROJECT_NAME"'])

def bun(code, db=fixture_db):
    authorize()
    settings = dict(env, DATABASE_URL=db, REDIS_URL=base_redis, SMOKE_KEY=key)
    return command(['bun', '--no-env-file', 'run', '-'], capture=True, input=code, settings=settings)

def proxy_url(original, port):
    parts = urllib.parse.urlsplit(original)
    credentials, marker, _ = parts.netloc.rpartition('@')
    return parts._replace(netloc=credentials + marker + f'proxy:{port}').geturl()

def inspect(resource):
    return json.loads(command(['docker', 'inspect', resource], capture=True))[0]

def http(url, body=None, method=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers=headers, method=method)
    start = time.monotonic()
    try:
        response = urllib.request.urlopen(req, timeout=2)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        data = response.read()
        return response.status, json.loads(data) if data else None, time.monotonic() - start

def ready(url, process=None):
    for _ in range(120):
        if process and process.poll() is not None:
            raise RuntimeError('host server exited before readiness')
        try:
            if http(url + '/api/me')[0] == 401:
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.25)
    raise RuntimeError('server readiness deadline expired')

health_calls = []

def health(url, failed=None):
    now = time.monotonic()
    health_calls[:] = [t for t in health_calls if now - t < 60]
    assert len(health_calls) < 30, 'health smoke exceeds rate limit budget'
    health_calls.append(now)
    status, body, elapsed = http(url + '/api/health')
    expected = {'status': 'unavailable' if failed else 'ok', 'dependencies': {
        dep: 'unavailable' if dep == failed else 'ok' for dep in ('postgres', 'valkey')}}
    print(f'health {failed or "healthy"}: {status} {body} {elapsed:.3f}s', flush=True)
    assert status == (503 if failed else 200) and body == expected and elapsed < 2

def host(args, settings):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    settings = dict(settings, PORT=str(port))
    child = subprocess.Popen(args, env=settings, stdout=log, stderr=log, start_new_session=True)
    children.append(child)
    url = f'http://127.0.0.1:{port}'
    ready(url, child)
    return child, url

def stop(child):
    if child.poll() is None:
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()

def image_sources(image):
    container = command(['docker', 'create', image], capture=True)
    exports.append(container)
    archive = tmp / 'image.tar'
    command(['docker', 'export', '-o', str(archive), container])
    with tarfile.open(archive) as tree:
        paths = [entry.name.removeprefix('./') for entry in tree]
    assert 'app/apps/server/src/index.ts' in paths and 'app/packages/shared/src/index.ts' in paths
    bad = []
    for path in paths:
        parts = pathlib.PurePosixPath(path).parts
        if any(p == '.env' or p.startswith('.env.') or p == '.git' for p in parts):
            bad.append(path)
        if path.startswith('app/') and 'node_modules' not in parts:
            if re.search(r'(^|/)(tests?|__tests__|fixtures|test-fixtures|mocks|__mocks__|mobile)(/|$)|[.]test[.]|/(test-env|activities-test-mock|test-util)[.]', path):
                bad.append(path)
    assert not bad, f'image contains forbidden sources: {bad[:8]}'
    archive.unlink()
    command(['docker', 'rm', container])
    exports.remove(container)

def main():
    global created_db, compose_started, sentinel
    authorize()
    upstreams = {}
    for service in ('postgres', 'valkey'):
        ids = command(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=' + env['SMOKE_OWNER'],
                       '--filter', 'label=com.docker.compose.service=' + service], capture=True).splitlines()
        assert len(ids) == 1
        upstreams[service] = inspect(ids[0])
    common = set(upstreams['postgres']['NetworkSettings']['Networks']) & set(upstreams['valkey']['NetworkSettings']['Networks'])
    assert len(common) == 1, 'expected one common checkout-owned network'
    network = common.pop()
    labels = inspect(network)['Labels']
    for suffix in ('clone', 'checkout'):
        assert labels['com.divineruin.' + suffix] == env['WT_' + suffix.upper() + '_ID']
    override = {'services': {'server': {'networks': ['default']}, 'proxy': {
        'image': 'ghcr.io/shopify/toxiproxy:2.12.0', 'ports': ['127.0.0.1::8474'],
        'networks': ['default', 'checkout']}}, 'networks': {'checkout': {'external': True, 'name': network}}}
    (tmp / 'override.json').write_text(json.dumps(override))
    settings = {'DATABASE_URL': proxy_url(fixture_db, 15432),
                'REDIS_URL': proxy_url(base_redis, 16379), 'JWT_SECRET': uuid.uuid4().hex + uuid.uuid4().hex,
                'INTERNAL_SECRET': uuid.uuid4().hex, 'CORS_ORIGIN': 'https://smoke.invalid', 'NODE_ENV': 'production', 'PORT': '3001'}
    private_values.extend(settings[k] for k in ('DATABASE_URL', 'REDIS_URL', 'JWT_SECRET', 'INTERNAL_SECRET'))
    (tmp / 'runtime.env').write_text(''.join(k + '=' + v + '\n' for k, v in settings.items()))
    os.chmod(tmp / 'runtime.env', 0o600)
    command(compose + ['build'])
    image = command(compose + ['images', '-q', 'server'], capture=True)
    if not image:
        image = project + '-server'
    print('image ' + command(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], capture=True), flush=True)
    uid = command(['docker', 'run', '--rm', '--entrypoint', 'id', image, '-u'], capture=True)
    assert uid.isdigit() and int(uid) > 0, 'image must execute as non-root'
    image_sources(image)
    bun('const s = new Bun.SQL(process.env.DATABASE_URL); await s.unsafe(`CREATE DATABASE "' + name + '"`); await s.close();', base_db)
    created_db = True
    authorize()
    fixture_env = dict(env, DATABASE_URL=fixture_db, REDIS_URL=base_redis)
    command(['bun', '--no-env-file', 'run', 'scripts/migrate.ts'], settings=fixture_env)
    authorize()
    command(['uv', 'run', '--project', 'scripts', '--frozen', 'python', 'scripts/seed_content.py'], settings=fixture_env)
    bun('const r = new Bun.RedisClient(process.env.REDIS_URL); await r.set(process.env.SMOKE_KEY,"alive","EX",1800); r.close();')
    sentinel = True
    fixture = json.loads(bun('''const s = new Bun.SQL(process.env.DATABASE_URL);
const [a] = await s`INSERT INTO accounts (email) VALUES (${'smoke-' + process.env.SMOKE_KEY + '@example.invalid'}) RETURNING id, email, created_at`;
await s`INSERT INTO auth_codes (account_id, code, expires_at) VALUES (${a.id}, '123456', NOW() + INTERVAL '10 minutes')`;
console.log(JSON.stringify(a)); await s.close();'''))
    compose_started = True
    command(compose + ['up', '-d', 'proxy'])
    proxy_port = command(compose + ['port', 'proxy', '8474'], capture=True).rsplit(':', 1)[1]
    proxy = 'http://127.0.0.1:' + proxy_port
    for _ in range(60):
        try:
            if http(proxy + '/version')[0] == 200:
                break
        except OSError:
            time.sleep(0.25)
    for dep, port, upstream_port in [('postgres', 15432, 5432), ('valkey', 16379, 6379)]:
        assert http(proxy + '/proxies', {'name': dep, 'listen': f'0.0.0.0:{port}',
                    'upstream': upstreams[dep]['NetworkSettings']['Networks'][network]['IPAddress'] + ':' + str(upstream_port)})[0] == 201
    command(compose + ['up', '-d', 'server'])
    server_id = command(compose + ['ps', '-q', 'server'], capture=True)
    started = inspect(server_id)['State']['StartedAt']
    url = 'http://127.0.0.1:' + command(compose + ['port', 'server', '3001'], capture=True).rsplit(':', 1)[1]
    ready(url)
    health(url)
    status, auth, _ = http(url + '/api/auth/verify-code', {'email': fixture['email'], 'code': '123456'})
    assert status == 200 and auth['account_id'] == fixture['id']
    token = auth['token']
    expected = {'account_id': fixture['id'], 'player_id': 'player_' + fixture['id'][:8],
                'email': fixture['email'], 'created_at': fixture['created_at']}
    def me(endpoint):
        status, body, _ = http(endpoint + '/api/me', token=token)
        assert status == 200 and body == expected, (status, body)
        assert http(endpoint + '/api/me')[0] == 401
        assert http(endpoint + '/api/me', token='invalid')[0] == 401
    me(url)
    baseline, host_url = host(['bun', 'run', '--cwd', 'apps/server', 'start'],
                              dict(env, **dict(settings, DATABASE_URL=fixture_db, REDIS_URL=base_redis)))
    health(host_url)
    me(host_url)
    stop(baseline)
    for dep in ('postgres', 'valkey'):
        for fault in ('refusal', 'timeout'):
            health(url)
            path = proxy + '/proxies/' + dep
            if fault == 'refusal':
                assert http(path, {'enabled': False})[0] == 200
            else:
                assert http(path + '/toxics', {'name': 'blackhole', 'type': 'timeout', 'stream': 'downstream', 'attributes': {'timeout': 0}})[0] == 200
            for _ in range(3):
                health(url, dep)
            if fault == 'refusal':
                assert http(path, {'enabled': True})[0] == 200
            else:
                assert http(path + '/toxics/blackhole', method='DELETE')[0] == 204
            health(url)
    me(url)
    assert inspect(server_id)['State']['StartedAt'] == started
    authorize()
    for dep, original in upstreams.items():
        current = inspect(original['Id'])
        assert current['State']['Running'] and current['State']['StartedAt'] == original['State']['StartedAt']
    assert bun('const r = new Bun.RedisClient(process.env.REDIS_URL); console.log(await r.get(process.env.SMOKE_KEY)); r.close();') == 'alive'
    authorize()
    dev, dev_url = host(['bun', 'run', 'dev:server'], {k: os.environ[k] for k in ('PATH', 'HOME')})
    health(dev_url)
    assert http(dev_url + '/api/me')[0] == 401
    stop(dev)
    print('server smoke passed', flush=True)

def interrupt(signum, frame):
    raise RuntimeError('smoke interrupted')

signal.signal(signal.SIGTERM, interrupt)
signal.signal(signal.SIGINT, interrupt)
failed = False
try:
    main()
except Exception as error:
    print(f'smoke failed: {error}', flush=True)
    failed = True
finally:
    actions = [lambda child=child: stop(child) for child in children]
    if compose_started:
        actions.append(lambda: command(compose + ['logs', '--no-color']))
        actions.append(lambda: command(compose + ['down', '--volumes', '--remove-orphans']))
    actions.extend(lambda container=container: command(['docker', 'rm', '-f', container]) for container in exports)
    if sentinel:
        actions.append(lambda: bun('const r = new Bun.RedisClient(process.env.REDIS_URL); await r.del(process.env.SMOKE_KEY); r.close();'))
    if created_db:
        actions.append(lambda: bun('const s = new Bun.SQL(process.env.DATABASE_URL); await s.unsafe(`DROP DATABASE "' + name + '" WITH (FORCE)`); await s.close();', base_db))
    for action in actions:
        try:
            action()
        except Exception as error:
            print(f'cleanup failed: {error}', flush=True)
            failed = True
    log.close()
    if failed:
        destination = root / 'flake-artifacts' / project
        destination.mkdir(parents=True, exist_ok=True)
        content = (tmp / 'run.log').read_text(errors='replace')
        for secret in private_values:
            if secret:
                content = content.replace(secret, '[redacted]')
        (destination / 'smoke.log').write_text(content)
        print('log: ' + str(destination / 'smoke.log'), flush=True)
    shutil.rmtree(tmp)
raise SystemExit(1 if failed else 0)
PY

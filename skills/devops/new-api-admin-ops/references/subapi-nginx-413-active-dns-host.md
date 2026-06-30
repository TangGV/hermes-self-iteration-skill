# SubAPI `/v1/responses` nginx 413 on active DNS host

Use this reference when `https://subapi.aigcfast.com/v1/responses` returns an HTML nginx error like:

```html
413 Request Entity Too Large
<hr><center>nginx/1.22.1</center>
```

## Key lesson

Do **not** assume VPS1 is the active request path. First resolve the public DNS and test the active IP:

```bash
getent hosts subapi.aigcfast.com
curl --noproxy '*' -sS -o /dev/null -w 'remote_ip=%{remote_ip} http=%{http_code} server=%{header_json}\n' \
  https://subapi.aigcfast.com/api/status
```

In the observed incident, DNS pointed `subapi.aigcfast.com` to VPS2 (`62.106.70.67`), while VPS1 already had a correct 100m OpenResty config. The real 413 came from VPS2 native nginx.

## Diagnostic commands

On the active host:

```bash
nginx -T 2>/tmp/nginx.err | grep -n 'server_name subapi.aigcfast.com\|client_max_body_size\|include' | head -120 || cat /tmp/nginx.err
awk '$9==413{print FILENAME":"NR":"$0}' /var/log/nginx/*.log 2>/dev/null | tail -50
grep -R 'client intended to send too large\|413' -n /var/log/nginx 2>/dev/null | tail -80
```

Expected nginx error shape:

```text
client intended to send too large body: 1064864 bytes, client: ..., server: subapi.aigcfast.com, request: "POST /v1/responses ..."
```

## Fix pattern

Add a body limit to the **active** `subapi.aigcfast.com` TLS server block, and for large streaming/API requests also disable request buffering:

```nginx
server {
    listen 443 ssl http2;
    server_name subapi.aigcfast.com;

    client_max_body_size 100m;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

Then:

```bash
nginx -t && systemctl reload nginx
```

## Verification without secrets

Use an intentionally invalid bearer token with generated large JSON bodies. Success for this test is **not** 200; success is that nginx no longer returns HTML 413 and the request reaches New API, returning JSON `401 Invalid token` with an `x-oneapi-request-id`.

```bash
python3 - <<'PY'
import json, subprocess, os
for sz in [1064864, 1200000, 2*1024*1024, 8*1024*1024]:
    p=f'/tmp/subapi_body_{sz}.json'
    with open(p,'w') as f:
        json.dump({'model':'gpt-5.5','input':'x'*sz,'stream':False}, f)
    cmd=[
        'curl','--noproxy','*','-sS','--max-time','30',
        '-o','/tmp/subapi_probe_resp.txt',
        '-w',f'sz={sz} code=%{{http_code}} upload=%{{size_upload}} remote=%{{remote_ip}} hdr=%{{header_json}}\\n',
        '-H','Authorization: Bearer invalid-probe-token',
        '-H','Content-Type: application/json',
        '--data-binary',f'@{p}',
        'https://subapi.aigcfast.com/v1/responses'
    ]
    print(subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout.strip())
    print(open('/tmp/subapi_probe_resp.txt','rb').read(180).decode('utf-8','replace').replace('\n',' '))
    os.remove(p)
PY
```

## Pitfalls

- **Active DNS host first:** if VPS1 and VPS2 both have configs, inspect the one returned by DNS or curl `remote_ip`, not the host you expect from memory.
- **Available vs enabled config drift:** on some VPS2 nginx setups, `/etc/nginx/sites-enabled/api2.aigcfast.com` may be a regular file, not a symlink. Editing only `sites-available` may not affect `nginx -T`. Compare hashes or `readlink -f`; copy the changed file to `sites-enabled` when needed.
- **Do not leave backups in `sites-enabled`:** backup files there can be included as duplicate vhosts and produce `conflicting server name ... ignored`. Move enabled backups outside the include path, e.g. `/root/nginx-enabled-backups/`.
- **Large-body 502 after raising limit:** if 413 is gone but larger invalid-token probes produce `502` plus `sendfile() failed (32: Broken pipe) while sending request to upstream`, add `proxy_request_buffering off;`. Then verify the target payload sizes reach New API as JSON 401.
- **Invalid-token probe may upload only part of the body:** New API can reject auth before consuming the full request. That is acceptable for proving nginx no longer blocks the request; the decisive signal is JSON New API error instead of HTML nginx 413.

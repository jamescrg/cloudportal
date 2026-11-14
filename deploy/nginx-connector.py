#!/usr/bin/env python3
"""Let Claude's connector read its sign-in details on the live site.

The site's nginx security rules refuse every path that starts with a dot,
and Claude reads the connector's OAuth metadata from
/.well-known/oauth-authorization-server and
/.well-known/oauth-protected-resource/mcp. This adds one location block to
the cloud-portal.net server block that passes those two (and only paths
starting /.well-known/oauth-) to the site.

    sudo python3 deploy/nginx-connector.py            make the change
    python3 deploy/nginx-connector.py --dry-run       show it, change nothing

It finds the server block whose server_name is cloud-portal.net and that
has a `location /`, copies that location's proxy lines (so the socket is
whatever the site already uses), and puts the new block just above it. The
file is backed up first; if `nginx -t` fails, the backup goes back and
nothing is reloaded. Run twice, it changes nothing the second time.
"""

import glob
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

HOST = "cloud-portal.net"
MARKER = "/.well-known/oauth-"
CHECK_URL = f"https://{HOST}/.well-known/oauth-protected-resource/mcp"


def say(message):
    print(f"  {message}")


def fail(message):
    print(f"\n  ✗ {message}\n")
    sys.exit(1)


def server_blocks(lines):
    """(first line, last line) of each top-level `server {` block."""
    blocks, depth, start = [], 0, None
    for number, line in enumerate(lines):
        code = line.split("#", 1)[0]
        if depth == 0 and re.match(r"\s*server\s*\{", code):
            start = number
        depth += code.count("{") - code.count("}")
        if start is not None and depth == 0:
            blocks.append((start, number))
            start = None
    return blocks


def serves_host(lines, start, end):
    stop = end + 1
    for line in lines[start:stop]:
        code = line.split("#", 1)[0]
        match = re.match(r"\s*server_name\s+([^;]+);", code)
        if match and HOST in match.group(1).split():
            return True
    return False


def root_location(lines, start, end):
    """(first line, last line) of the block's `location / {`, or None."""
    for number in range(start, end + 1):
        code = lines[number].split("#", 1)[0]
        if re.match(r"\s*location\s+/\s*\{", code):
            depth = 0
            for last in range(number, end + 1):
                inner = lines[last].split("#", 1)[0]
                depth += inner.count("{") - inner.count("}")
                if depth == 0:
                    return number, last
    return None


def find_site():
    """The config file, its lines, and where the root location is."""
    for path in sorted(glob.glob("/etc/nginx/sites-enabled/*")):
        real = os.path.realpath(path)
        try:
            with open(real) as handle:
                lines = handle.read().split("\n")
        except OSError:
            continue
        for start, end in server_blocks(lines):
            if not serves_host(lines, start, end):
                continue
            location = root_location(lines, start, end)
            if location:
                return real, lines, (start, end), location
    fail(f"No nginx server block for {HOST} with a `location /` was found.")


def new_block(lines, location):
    """The block to add, indented like `location /`, with its proxy lines."""
    first, last = location
    body = first + 1
    indent = re.match(r"\s*", lines[first]).group(0)
    proxy = [
        line.strip()
        for line in lines[body:last]
        if re.match(r"\s*(include\s+proxy_params|proxy_pass|uwsgi_pass)\b", line)
    ]
    if not any(line.startswith(("proxy_pass", "uwsgi_pass")) for line in proxy):
        fail("The site's `location /` has no proxy_pass line to copy.")
    inner = indent + "    "
    return [
        f"{indent}# Claude's connector reads its sign-in details here; the",
        f"{indent}# security rules otherwise refuse every path starting with a dot",
        f"{indent}location ^~ {MARKER} {{",
        *[inner + line for line in proxy],
        f"{indent}}}",
        "",
    ]


def check_live():
    try:
        with urllib.request.urlopen(CHECK_URL, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except OSError:
        return None


def main():
    dry_run = "--dry-run" in sys.argv
    print(f"\nClaude connector · nginx for {HOST}\n")

    path, lines, (start, end), location = find_site()
    say(f"site config   {path}")
    stop = end + 1
    if any(MARKER in line for line in lines[start:stop]):
        say("already has the connector's block; nothing to do")
        return

    block = new_block(lines, location)
    print()
    for line in block[:-1]:
        print(f"  + {line}")
    print()
    if dry_run:
        say(f"dry run: would add the block above line {location[0] + 1}")
        return

    if os.geteuid() != 0:
        fail("Run it with sudo: sudo python3 deploy/nginx-connector.py")

    backup = f"{path}.bak-connector-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, backup)
    say(f"backed up to  {backup}")

    at = location[0]
    updated = lines[:at] + block + lines[at:]
    with open(path, "w") as handle:
        handle.write("\n".join(updated))

    test = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    if test.returncode != 0:
        shutil.copy2(backup, path)
        print(test.stderr)
        fail("nginx -t failed, so the old config is back and nothing reloaded.")
    say("nginx -t      ok")

    subprocess.run(["systemctl", "reload", "nginx"], check=True)
    say("nginx         reloaded")

    status = check_live()
    if status == 200:
        say(f"check         {CHECK_URL} answers 200")
    elif status == 404:
        say("check         nginx lets it through; the site answers 404 until")
        say("              the connector is deployed (deploy cpl)")
    else:
        say(f"check         {CHECK_URL} answered {status}; look into it")
    print()


if __name__ == "__main__":
    main()

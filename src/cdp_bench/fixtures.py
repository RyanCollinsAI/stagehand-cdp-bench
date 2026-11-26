"""Two-origin local HTTP fixture server for 4 browser-automation torture cases."""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

IFRAME_CHILD_HTML = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Embedded Form</title></head>
<body>
  <h2>Vendor Intake (Cross-Origin Frame)</h2>
  <form id="intake-form">
    <label for="vendor">Vendor Code</label>
    <input id="vendor" name="vendor" type="text" placeholder="e.g. VND-404" />
    <label for="region">Region</label>
    <input id="region" name="region" type="text" placeholder="Bay Area" />
    <button id="frame-submit" type="submit">Confirm Intake</button>
  </form>
  <div id="frame-result" role="status"></div>
  <script>
    document.getElementById('intake-form').addEventListener('submit', function(e) {
      e.preventDefault();
      var v = document.getElementById('vendor').value.trim();
      var r = document.getElementById('region').value.trim();
      document.getElementById('frame-result').textContent = 'ACCEPTED:' + v + ':' + r;
    });
  </script>
</body>
</html>
"""

PAGINATED_SPA_HTML = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Paginated SPA</title></head>
<body>
  <h1>Release Ledger</h1>
  <div id="page-indicator">Page 1 of 3</div>
  <table>
    <thead><tr><th>ID</th><th>Service</th><th>LatencyMs</th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
  <button id="prev-btn" type="button">Previous</button>
  <button id="next-btn" type="button">Next Page</button>
  <script>
    const DATA = Array.from({length: 15}, (_, i) => ({
      id: 'SVC-' + String(i + 1).padStart(2, '0'),
      service: 'worker-' + (i + 1),
      latency: 40 + i * 7,
    }));
    let page = 0;
    const perPage = 5;
    function render() {
      const tbody = document.getElementById('rows');
      tbody.innerHTML = '<tr><td colspan="3">Loading...</td></tr>';
      setTimeout(() => {
        const slice = DATA.slice(page * perPage, (page + 1) * perPage);
        tbody.innerHTML = slice.map(r =>
          `<tr data-row="${r.id}"><td>${r.id}</td><td>${r.service}</td><td>${r.latency}</td></tr>`
        ).join('');
        document.getElementById('page-indicator').textContent = `Page ${page + 1} of 3`;
        document.getElementById('next-btn').disabled = page >= 2;
        document.getElementById('prev-btn').disabled = page <= 0;
      }, 60);
    }
    document.getElementById('next-btn').addEventListener('click', () => { if (page < 2) { page++; render(); } });
    document.getElementById('prev-btn').addEventListener('click', () => { if (page > 0) { page--; render(); } });
    render();
  </script>
</body>
</html>
"""

COMBOBOX_HTML = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Portal Combobox</title></head>
<body>
  <h1>Deployment Target</h1>
  <label id="env-label" for="env-input">Target Region</label>
  <input id="env-input" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="env-portal" placeholder="Type to filter..." />
  <button id="apply-btn" type="button">Apply Region</button>
  <div id="selected-out" role="status"></div>
  <script>
    const OPTIONS = ['us-east-1 (Virginia)', 'us-west-1 (San Francisco)', 'us-west-2 (Oregon)', 'eu-central-1 (Frankfurt)', 'ap-northeast-1 (Tokyo)'];
    const input = document.getElementById('env-input');
    let portal = null;
    function closePortal() { if (portal) { portal.remove(); portal = null; } input.setAttribute('aria-expanded', 'false'); }
    function openPortal(filterText) {
      closePortal();
      portal = document.createElement('ul');
      portal.id = 'env-portal';
      portal.setAttribute('role', 'listbox');
      const q = (filterText || '').toLowerCase();
      OPTIONS.filter(o => o.toLowerCase().includes(q)).forEach(opt => {
        const li = document.createElement('li');
        li.setAttribute('role', 'option');
        li.textContent = opt;
        li.tabIndex = 0;
        li.addEventListener('mousedown', (e) => {
          e.preventDefault();
          input.value = opt;
          closePortal();
        });
        portal.appendChild(li);
      });
      document.body.appendChild(portal);
      input.setAttribute('aria-expanded', 'true');
    }
    input.addEventListener('focus', () => openPortal(input.value));
    input.addEventListener('input', () => openPortal(input.value));
    document.getElementById('apply-btn').addEventListener('click', () => {
      document.getElementById('selected-out').textContent = 'REGION:' + input.value.trim();
    });
  </script>
</body>
</html>
"""

DOM_MUTATION_HTML = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Mutating DOM</title></head>
<body>
  <h1>Checkout Canary</h1>
  <div id="mount">
    <input class="input-coupon-v1" aria-label="Promo Code" placeholder="Enter code" />
    <button class="btn-submit-v1" type="button">Apply Promo</button>
  </div>
  <div id="promo-status" role="status"></div>
  <script>
    function wire() {
      const inp = document.querySelector('#mount input');
      const btn = document.querySelector('#mount button');
      btn.addEventListener('click', () => {
        document.getElementById('promo-status').textContent = 'PROMO:' + inp.value.trim();
      });
    }
    // Simulate hashed CSS-in-JS re-render wiping old class selectors after hydration
    setTimeout(() => {
      const mount = document.getElementById('mount');
      mount.innerHTML = `
        <div class="sc-8a41f-wrap">
          <input class="sc-9c21a-input" aria-label="Promo Code" placeholder="Enter code" />
          <button class="sc-7b30e-btn" type="button">Apply Promo</button>
        </div>
      `;
      wire();
    }, 80);
    wire();
  </script>
</body>
</html>
"""


def make_parent_iframe_html(iframe_origin: str) -> str:
    return f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>Cross-Origin Iframe Host</title></head>
<body>
  <h1>Operations Portal</h1>
  <iframe id="vendor-frame" title="Vendor Intake Frame" src="{iframe_origin}/frame" width="600" height="320"></iframe>
</body>
</html>
"""


class FixtureCluster:
    """Two-origin local HTTP server (127.0.0.1 + localhost) for deterministic tests."""

    def __init__(self) -> None:
        self.iframe_srv = self._start_iframe_server()
        self.iframe_port = self.iframe_srv.server_address[1]
        self.iframe_origin = f"http://localhost:{self.iframe_port}"

        self.main_srv = self._start_main_server(self.iframe_origin)
        self.main_port = self.main_srv.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.main_port}"

    def _start_iframe_server(self) -> ThreadingHTTPServer:
        class IframeHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(IFRAME_CHILD_HTML.encode("utf-8"))

            def log_message(self, fmt: str, *args: object) -> None:
                return

        srv = ThreadingHTTPServer(("127.0.0.1", 0), IframeHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv

    def _start_main_server(self, iframe_origin: str) -> ThreadingHTTPServer:
        routes = {
            "/01_cross_origin_iframe": make_parent_iframe_html(iframe_origin),
            "/02_paginated_spa": PAGINATED_SPA_HTML,
            "/03_custom_combobox": COMBOBOX_HTML,
            "/04_dom_selector_mutation": DOM_MUTATION_HTML,
        }

        class MainHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                body = routes.get(self.path.split("?", 1)[0])
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))

            def log_message(self, fmt: str, *args: object) -> None:
                return

        srv = ThreadingHTTPServer(("127.0.0.1", 0), MainHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv

    def close(self) -> None:
        self.main_srv.shutdown()
        self.main_srv.server_close()
        self.iframe_srv.shutdown()
        self.iframe_srv.server_close()

    def __enter__(self) -> "FixtureCluster":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

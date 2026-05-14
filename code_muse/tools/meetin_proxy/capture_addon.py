"""mitmproxy capture addon — injected into mitmdump via -s flag."""

import os
from datetime import UTC, datetime
from pathlib import Path

import orjson
import orjson as json


class TrafficCapture:
    def __init__(self):
        self.flows = []
        self.target = os.environ.get("MITMPROXY_TARGET", "")
        self.output = os.environ.get("MITMPROXY_OUTPUT", "/tmp/mitmproxy_capture.json")
        self.max_req_body = int(os.environ.get("MITMPROXY_MAX_REQ_BODY", "10000"))
        self.max_res_body = int(os.environ.get("MITMPROXY_MAX_RES_BODY", "100000"))

    def _should_capture(self, flow) -> bool:
        if not self.target:
            return True
        return self.target in flow.request.pretty_host

    def response(self, flow):
        if not self._should_capture(flow):
            return
        try:
            req_body = flow.request.get_text(strict=False) or ""
            res_body = flow.response.get_text(strict=False) or ""
        except Exception:
            req_body = f"<binary: {len(flow.request.content)} bytes>"
            res_body = f"<binary: {len(flow.response.content)} bytes>"

        if len(req_body) > self.max_req_body:
            req_body = req_body[: self.max_req_body] + "\n... <truncated>"
        if len(res_body) > self.max_res_body:
            res_body = res_body[: self.max_res_body] + "\n... <truncated>"

        entry = {
            "url": flow.request.pretty_url,
            "method": flow.request.method,
            "host": flow.request.pretty_host,
            "path": flow.request.path,
            "request_headers": dict(flow.request.headers),
            "request_body": req_body,
            "status_code": flow.response.status_code,
            "response_headers": dict(flow.response.headers),
            "response_body": res_body,
            "timestamp": datetime.now(UTC).isoformat(),
            "content_type": flow.response.headers.get("content-type", ""),
        }
        self.flows.append(entry)

    def error(self, flow):
        if not self._should_capture(flow):
            return
        entry = {
            "url": flow.request.pretty_url if flow.request else "N/A",
            "method": flow.request.method if flow.request else "N/A",
            "error": str(flow.error.msg) if flow.error else "Unknown error",
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.flows.append(entry)

    def done(self):
        out_dir = Path(self.output).parent
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(self.output, "w") as f:
            f.write(json.dumps(
                {
                    "meta": {
                        "captured_at": datetime.now(UTC).isoformat(),
                        "target_filter": self.target,
                        "total_flows": len(self.flows),
                    },
                    "flows": self.flows,
                },
                option=orjson.OPT_INDENT_2,
                default=str,
            ).decode())


addons = [TrafficCapture()]

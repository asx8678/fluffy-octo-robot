"""Tests for ContentTypeDetector."""

from code_muse.plugins.filter_engine.content_detector import (
    ContentType,
    ContentTypeDetector,
)


class TestContentTypeDetector:
    def test_json_object(self):
        stdout = '{"name": "test", "version": "1.0"}'
        assert ContentTypeDetector.detect(stdout) == ContentType.JSON

    def test_json_array(self):
        stdout = '[{"a": 1}, {"a": 2}]'
        assert ContentTypeDetector.detect(stdout) == ContentType.JSON

    def test_diff(self):
        stdout = """diff --git a/foo.py b/foo.py
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
-old line
+new line
 context"""
        assert ContentTypeDetector.detect(stdout) == ContentType.DIFF

    def test_log(self):
        stdout = """2025-07-16 10:30:45 INFO Starting server
2025-07-16 10:30:46 DEBUG Connecting to database
2025-07-16 10:30:47 ERROR Connection failed"""
        assert ContentTypeDetector.detect(stdout) == ContentType.LOG

    def test_html(self):
        stdout = (
            "<html><head><title>Test</title></head><body><div>Hello</div></body></html>"
        )
        assert ContentTypeDetector.detect(stdout) == ContentType.HTML

    def test_python_code(self):
        stdout = """import os
import sys

def main():
    \"\"\"Main entry point.\"\"\"
    return 0

if __name__ == "__main__":
    sys.exit(main())"""
        assert ContentTypeDetector.detect(stdout) == ContentType.CODE

    def test_javascript_code(self):
        stdout = """const express = require('express');
const app = express();

function hello() {
    return 'world';
}

module.exports = app;"""
        assert ContentTypeDetector.detect(stdout) == ContentType.CODE

    def test_unknown_empty(self):
        assert ContentTypeDetector.detect("") == ContentType.UNKNOWN

    def test_unknown_plain(self):
        assert ContentTypeDetector.detect("hello world") == ContentType.UNKNOWN

    def test_search_grep(self):
        stdout = "src/main.py:42:    return foo(bar)\nsrc/utils.py:15:    import bar\nFound 2 results"
        assert ContentTypeDetector.detect(stdout) == ContentType.SEARCH

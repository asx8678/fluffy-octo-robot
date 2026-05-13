"""Tree-sitter based AST parser for code compression.

Provides language detection and AST parsing for Python, JavaScript,
TypeScript, Go, Rust, Java, C, C++, Ruby, Bash, and SQL source code.
"""

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

logger = logging.getLogger(__name__)


class CodeLanguage(Enum):
    """Supported languages for AST compression."""

    PYTHON = auto()
    JAVASCRIPT = auto()
    TYPESCRIPT = auto()
    GO = auto()
    RUST = auto()
    JAVA = auto()
    C = auto()
    CPP = auto()
    RUBY = auto()
    BASH = auto()
    SQL = auto()
    UNKNOWN = auto()

    def to_filter_key(self) -> str:
        """Return the MinimalFilter language key for this language."""
        _map: dict[CodeLanguage, str] = {
            CodeLanguage.PYTHON: "python",
            CodeLanguage.JAVASCRIPT: "javascript",
            CodeLanguage.TYPESCRIPT: "typescript",
            CodeLanguage.GO: "go",
            CodeLanguage.RUST: "rust",
            CodeLanguage.JAVA: "java",
            CodeLanguage.C: "cpp",
            CodeLanguage.CPP: "cpp",
            CodeLanguage.RUBY: "ruby",
            CodeLanguage.BASH: "bash",
            CodeLanguage.SQL: "sql",
        }
        return _map.get(self, "python")


@dataclass
class ASTNode:
    """Lightweight AST node wrapper."""

    type: str
    text: str
    children: list[ASTNode]
    start_byte: int
    end_byte: int


class LanguageParser:
    """Parse source code using tree-sitter grammars.

    Lazy-loads grammars on first use to avoid startup cost.
    """

    _grammars_loaded: dict[str, bool] = {}

    # File extension → language mapping
    EXTENSION_MAP: dict[str, CodeLanguage] = {
        ".py": CodeLanguage.PYTHON,
        ".pyi": CodeLanguage.PYTHON,
        ".js": CodeLanguage.JAVASCRIPT,
        ".mjs": CodeLanguage.JAVASCRIPT,
        ".cjs": CodeLanguage.JAVASCRIPT,
        ".jsx": CodeLanguage.JAVASCRIPT,
        ".ts": CodeLanguage.TYPESCRIPT,
        ".tsx": CodeLanguage.TYPESCRIPT,
        ".go": CodeLanguage.GO,
        ".rs": CodeLanguage.RUST,
        ".java": CodeLanguage.JAVA,
        ".c": CodeLanguage.C,
        ".h": CodeLanguage.C,
        ".cpp": CodeLanguage.CPP,
        ".cc": CodeLanguage.CPP,
        ".cxx": CodeLanguage.CPP,
        ".hpp": CodeLanguage.CPP,
        ".rb": CodeLanguage.RUBY,
        ".sh": CodeLanguage.BASH,
        ".bash": CodeLanguage.BASH,
        ".sql": CodeLanguage.SQL,
    }

    # Shebang → language mapping
    SHEBANG_MAP: dict[str, CodeLanguage] = {
        "python": CodeLanguage.PYTHON,
        "python3": CodeLanguage.PYTHON,
        "node": CodeLanguage.JAVASCRIPT,
        "ruby": CodeLanguage.RUBY,
        "bash": CodeLanguage.BASH,
        "sh": CodeLanguage.BASH,
    }

    @classmethod
    def detect_language(cls, source: str, filename: str | None = None) -> CodeLanguage:
        """Detect programming language from source content and filename.

        Priority: filename extension > shebang > content heuristics.
        """
        # 1. Filename extension
        if filename:
            ext = f".{filename.rsplit('.', 1)[-1].lower()}" if "." in filename else ""
            if ext in cls.EXTENSION_MAP:
                return cls.EXTENSION_MAP[ext]

        # 2. Shebang line
        first_line = source.split("\n", 1)[0].strip()
        if first_line.startswith("#!"):
            for key, lang in cls.SHEBANG_MAP.items():
                if key in first_line.lower():
                    return lang

        # 3. Content heuristics
        if "fn " in source and (
            "let " in source or "mut " in source or "impl " in source
        ):
            return CodeLanguage.RUST
        if (
            "public class " in source
            or "private class " in source
            or "protected class " in source
        ):
            return CodeLanguage.JAVA
        if "#include" in source and ("int main" in source or "void " in source):
            return CodeLanguage.C if "class " not in source else CodeLanguage.CPP
        if "def " in source and ("end\n" in source or "end " in source):
            return CodeLanguage.RUBY
        if source.strip().startswith("SELECT ") or source.strip().startswith("CREATE "):
            return CodeLanguage.SQL
        if "func " in source and ("package " in source or "import (" in source):
            return CodeLanguage.GO
        if "function " in source or "const " in source or "=>" in source:
            if ": " in source and "interface " in source:
                return CodeLanguage.TYPESCRIPT
            return CodeLanguage.JAVASCRIPT
        if "def " in source or "import " in source or "class " in source:
            return CodeLanguage.PYTHON

        return CodeLanguage.UNKNOWN

    @classmethod
    def parse(cls, source: str, language: CodeLanguage) -> ASTNode | None:
        """Parse source code into an AST.

        Returns None if parsing fails or grammar unavailable.
        """
        try:
            tree = cls._parse_with_tree_sitter(source, language)
            return cls._convert_tree(tree)
        except Exception as exc:
            logger.debug("AST parse failed for %s: %s", language, exc)
            return None

    @classmethod
    def _parse_with_tree_sitter(cls, source: str, language: CodeLanguage) -> Any:
        """Internal tree-sitter parse."""
        import tree_sitter

        lang_map = {
            CodeLanguage.PYTHON: "python",
            CodeLanguage.JAVASCRIPT: "javascript",
            CodeLanguage.TYPESCRIPT: "javascript",  # TS uses JS grammar
            CodeLanguage.GO: "go",
            CodeLanguage.RUST: "rust",
            CodeLanguage.JAVA: "java",
            CodeLanguage.C: "c",
            CodeLanguage.CPP: "cpp",
            CodeLanguage.RUBY: "ruby",
            CodeLanguage.BASH: "bash",
            CodeLanguage.SQL: "sql",
        }
        lang_name = lang_map.get(language)
        if not lang_name:
            raise ValueError(f"No tree-sitter grammar for {language}")

        grammar_module = {
            "python": "tree_sitter_python",
            "javascript": "tree_sitter_javascript",
            "go": "tree_sitter_go",
            "rust": "tree_sitter_rust",
            "java": "tree_sitter_java",
            "c": "tree_sitter_c",
            "cpp": "tree_sitter_cpp",
            "ruby": "tree_sitter_ruby",
            "bash": "tree_sitter_bash",
            "sql": "tree_sitter_sql",
        }.get(lang_name, f"tree_sitter_{lang_name}")

        try:
            import importlib

            mod = importlib.import_module(grammar_module)
            language_capsule = mod.language()
        except ImportError:
            logger.warning(
                "tree-sitter grammar for %s not installed. Run: pip install %s",
                lang_name,
                grammar_module.replace("_", "-"),
            )
            raise

        language_obj = tree_sitter.Language(language_capsule)
        parser = tree_sitter.Parser(language_obj)
        tree = parser.parse(source.encode("utf-8"))
        return tree

    @classmethod
    def _convert_tree(cls, tree: Any) -> ASTNode:
        """Convert tree-sitter tree to our ASTNode."""
        root = tree.root_node

        def _convert(node: Any) -> ASTNode:
            children = [_convert(child) for child in node.children]
            text = (
                node.text.decode("utf-8")
                if isinstance(node.text, bytes)
                else str(node.text)
            )
            return ASTNode(
                type=node.type,
                text=text,
                children=children,
                start_byte=node.start_byte,
                end_byte=node.end_byte,
            )

        return _convert(root)

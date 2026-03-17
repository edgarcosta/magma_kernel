"""Pygments lexer for the Magma computer algebra system.

Keyword and operator lists derived from the tree-sitter-magma grammar
(https://github.com/edgarcosta/tree-sitter-magma).

Registered as a Pygments entry point so that nbconvert and other tools
can highlight Magma code automatically.
"""

from pygments.lexer import RegexLexer, bygroups, words
from pygments.token import (
    Comment,
    Keyword,
    Name,
    Number,
    Operator,
    Punctuation,
    String,
    Text,
    Error,
)

__all__ = ["MagmaLexer"]


class MagmaLexer(RegexLexer):
    """Pygments lexer for Magma source code."""

    name = "Magma"
    aliases = ["magma"]
    filenames = ["*.m", "*.mag"]
    mimetypes = ["text/x-magma"]

    # Keywords split into categories for proper token types
    _keywords = (
        "if", "then", "elif", "else",
        "for", "do", "by", "to",
        "while", "repeat", "until",
        "case", "when", "select",
        "try", "catch",
        "function", "procedure", "intrinsic",
        "end",
        "return", "break", "continue",
        "where", "is",
        "forward", "import", "load", "iload",
        "save", "restore",
        "local", "declare",
        "freeze", "clear",
        "quit", "exit",
    )

    _keyword_operators = (
        "not", "and", "or", "xor",
        "div", "mod",
        "in", "notin",
        "adj", "notadj",
        "subset", "notsubset",
        "join", "diff", "sdiff", "meet", "cat",
        "eq", "ne", "cmpeq", "cmpne",
        "gt", "ge", "lt", "le",
    )

    _builtins = (
        "print", "printf", "fprintf",
        "vprint", "vprintf",
        "read", "readi",
        "assert", "assert2", "assert3",
        "require", "requirege", "requirerange",
        "error", "delete", "eval",
        "time", "vtime",
        "exists", "forall",
        "recformat", "random", "rep",
        "assigned",
    )

    _constants = ("true", "false")

    tokens = {
        "root": [
            # Whitespace
            (r"\s+", Text),

            # Block comments (nestable in Magma, but we approximate)
            (r"/\*", Comment.Multiline, "comment"),

            # Line comments
            (r"//.*$", Comment.Single),

            # Strings
            (r'"', String, "string"),

            # Numbers: hex, binary, decimal, real
            (r"0[xX][0-9a-fA-F]+", Number.Hex),
            (r"0[bB][01]+", Number.Bin),
            (r"\d+\.\d*([eE][+-]?\d+)?", Number.Float),
            (r"\d+[eE][+-]?\d+", Number.Float),
            (r"\d+", Number.Integer),

            # Reduction operators: &+, &*, &and, &or, &meet, &join, &cat
            (r"&\+|&-|&\*|&and\b|&or\b|&meet\b|&join\b|&cat\b", Operator),

            # Multi-character operators
            (r":=|:->|->|~~|\^\^|!!|@@|\.\.", Operator),

            # Comparison/assignment that could be confused
            (r"[<>]=?|[!=]=", Operator),

            # Single-character operators
            (r"[+\-*/^~#@!|&]", Operator),

            # Constants
            (words(_constants, suffix=r"\b"), Name.Constant),

            # Keyword operators (and, or, not, div, mod, etc.)
            (words(_keyword_operators, suffix=r"\b"), Operator.Word),

            # Keywords
            (words(_keywords, suffix=r"\b"), Keyword),

            # Built-in functions/statements
            (words(_builtins, suffix=r"\b"), Name.Builtin),

            # Type annotations after colon: "x :: RngInt" or "x : RngInt"
            (r"(::?)(\s*)([A-Z]\w*)", bygroups(Punctuation, Text, Name.Class)),

            # Identifiers starting with uppercase — likely types/intrinsics
            (r"[A-Z]\w*", Name.Function),

            # Other identifiers
            (r"[a-z_]\w*", Name),

            # Punctuation
            (r"[(),;:\[\]{}.<>|]", Punctuation),
        ],

        "string": [
            (r'[^"\\]+', String),
            (r"\\.", String.Escape),
            (r'"', String, "#pop"),
        ],

        "comment": [
            (r"[^/*]+", Comment.Multiline),
            (r"/\*", Comment.Multiline, "#push"),  # nested
            (r"\*/", Comment.Multiline, "#pop"),
            (r"[/*]", Comment.Multiline),
        ],
    }

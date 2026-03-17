"""Pygments lexer for the Magma computer algebra system.

Uses tree-sitter-magma for context-sensitive parsing when available,
with a regex fallback otherwise.  Keyword and operator lists derived
from the tree-sitter-magma grammar
(https://github.com/edgarcosta/tree-sitter-magma).

Registered as a Pygments entry point so that nbconvert and other tools
can highlight Magma code automatically.
"""

from pygments.lexer import Lexer, RegexLexer, bygroups, words
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
    Token,
)

__all__ = ["MagmaLexer"]

# ---- Check for tree-sitter availability ----

try:
    import tree_sitter_magma as _tsmagma
    from tree_sitter import Language as _Language, Parser as _Parser

    _MAGMA_LANG = _Language(_tsmagma.language())
    _HAS_TREE_SITTER = True
except Exception:
    _HAS_TREE_SITTER = False

# ---- Tree-sitter node type -> Pygments token mapping ----

# Mapping from tree-sitter node types to Pygments token types.
# Leaf nodes whose type appears here get that token; anonymous leaves
# (operators, keywords, punctuation) are handled via _ANON_TOKEN_MAP.
_NODE_TOKEN_MAP = {
    "comment": Comment,
    "string": String,
    "doc_string": String.Doc,
    "integer": Number.Integer,
    "real": Number.Float,
    "identifier": Name,
    "anonymous_identifier": Name,
    "true": Name.Constant,
    "false": Name.Constant,
}

# Parent node types that promote their child identifiers
_FUNCTION_CALL_PARENTS = {"call"}
_TYPE_PARENTS = {"type", "typed_identifier", "ref_typed_identifier"}
_DEFINITION_PARENTS = {
    "function_definition", "procedure_definition", "intrinsic_definition",
}

# Keywords (anonymous literal nodes in the tree)
_KEYWORD_STRINGS = frozenset({
    "if", "then", "elif", "else", "end",
    "for", "do", "by", "to", "in",
    "while", "repeat", "until",
    "case", "when", "select",
    "try", "catch",
    "function", "procedure", "intrinsic",
    "return", "break", "continue",
    "where", "is",
    "forward", "import", "load", "iload",
    "save", "restore",
    "local", "declare",
    "freeze", "clear",
    "quit", "exit",
    "print", "printf", "fprintf",
    "vprint", "vprintf",
    "read", "readi",
    "assert", "assert2", "assert3",
    "require", "requirege", "requirerange",
    "error", "delete", "eval",
    "time", "vtime",
    "exists", "forall",
    "recformat", "random", "rep",
    "attributes", "type", "verbose",
})

# Word operators (context: inside binary_operator/unary_operator/boolean_operator)
_WORD_OPERATORS = frozenset({
    "not", "and", "or", "xor",
    "div", "mod",
    "in", "notin",
    "adj", "notadj",
    "subset", "notsubset",
    "join", "diff", "sdiff", "meet", "cat",
    "eq", "ne", "cmpeq", "cmpne",
    "gt", "ge", "lt", "le",
    "assigned",
})

_OPERATOR_PARENTS = {"binary_operator", "unary_operator", "boolean_operator",
                     "reduct_operator", "augmented_assignment"}

_PUNCTUATION_CHARS = frozenset("()[]{}.,;:")


def _field_matches(parent, field_name, node):
    """Check if node is the named field of parent (by tree-sitter node id)."""
    field_node = parent.child_by_field_name(field_name)
    return field_node is not None and field_node.id == node.id


def _ts_token_for_node(node, source):
    """Determine the Pygments token for a tree-sitter leaf node."""
    ntype = node.type
    text = source[node.start_byte:node.end_byte]

    # Named node types with direct mapping
    if ntype in _NODE_TOKEN_MAP:
        # Promote identifier based on parent context
        if ntype == "identifier":
            parent = node.parent
            if parent is not None:
                ptype = parent.type
                if ptype in _TYPE_PARENTS:
                    return Name.Class
                if ptype in _FUNCTION_CALL_PARENTS and _field_matches(parent, "function", node):
                    return Name.Function
                if ptype in _DEFINITION_PARENTS and _field_matches(parent, "name", node):
                    return Name.Function
        return _NODE_TOKEN_MAP[ntype]

    # Anonymous leaf (keyword, operator, punctuation)
    if not node.is_named:
        text_str = text.decode("utf-8", errors="replace").strip()

        # Check if inside an operator expression
        parent = node.parent
        parent_type = parent.type if parent else ""

        if parent_type in _OPERATOR_PARENTS:
            if text_str in _WORD_OPERATORS:
                return Operator.Word
            return Operator

        if text_str in _KEYWORD_STRINGS:
            return Keyword

        if text_str in _WORD_OPERATORS:
            return Operator.Word

        if all(c in _PUNCTUATION_CHARS for c in text_str) and text_str:
            return Punctuation

        # Assignment, arrows, other operators
        if text_str in (":=", ":->", "->", "^^", "~~", "!!", "@@", "..",
                        "$$", "+:=", "-:=", "*:=", "/:=", "^:=",
                        "div:=", "mod:=", "and:=", "or:=", "xor:=",
                        "join:=", "meet:=", "diff:=", "sdiff:=", "cat:="):
            return Operator

        if text_str in ("+", "-", "*", "/", "^", "~", "#", "@",
                        "!", "|", "=", "`", "``", "$",
                        "&+", "&-", "&*", "&and", "&or",
                        "&meet", "&join", "&cat", "\\(", "\\["):
            return Operator

        return Punctuation

    return Text


class _TreeSitterMagmaLexer(Lexer):
    """Pygments lexer backed by tree-sitter-magma."""

    name = "Magma"
    aliases = ["magma"]
    filenames = ["*.m", "*.mag"]
    mimetypes = ["text/x-magma"]

    def get_tokens_unprocessed(self, text):
        source = text.encode("utf-8")
        parser = _Parser(_MAGMA_LANG)
        tree = parser.parse(source)

        prev_end = 0

        def walk(node):
            nonlocal prev_end

            if node.child_count == 0:
                start = node.start_byte
                end = node.end_byte
                raw = source[start:end]

                # Tree-sitter sometimes includes leading/trailing whitespace
                # in anonymous tokens.  Split it off as Text.
                lstripped = raw.lstrip()
                lead_ws = len(raw) - len(lstripped)
                if lead_ws > 0:
                    yield start, Text, raw[:lead_ws].decode("utf-8", errors="replace")
                    start += lead_ws
                    raw = lstripped

                rstripped = raw.rstrip()
                trail_ws = len(raw) - len(rstripped)
                if trail_ws > 0:
                    raw = rstripped

                # Emit any gap between previous token and this one
                if start > prev_end:
                    yield prev_end, Text, source[prev_end:start].decode("utf-8", errors="replace")

                if raw:
                    token = _ts_token_for_node(node, source)
                    yield start, token, raw.decode("utf-8", errors="replace")
                prev_end = end
            else:
                for child in node.children:
                    yield from walk(child)

        yield from walk(tree.root_node)

        if prev_end < len(source):
            yield prev_end, Text, source[prev_end:].decode("utf-8", errors="replace")


# ---- Regex fallback lexer ----


class _RegexMagmaLexer(RegexLexer):
    """Regex-based Pygments lexer for Magma (fallback when tree-sitter
    is not available)."""

    name = "Magma"
    aliases = ["magma"]
    filenames = ["*.m", "*.mag"]
    mimetypes = ["text/x-magma"]

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
            (r"\s+", Text),
            (r"/\*", Comment.Multiline, "comment"),
            (r"//.*$", Comment.Single),
            (r'"', String, "string"),
            (r"0[xX][0-9a-fA-F]+", Number.Hex),
            (r"0[bB][01]+", Number.Bin),
            (r"\d+\.\d*([eE][+-]?\d+)?", Number.Float),
            (r"\d+[eE][+-]?\d+", Number.Float),
            (r"\d+", Number.Integer),
            (r"&\+|&-|&\*|&and\b|&or\b|&meet\b|&join\b|&cat\b", Operator),
            (r":=|:->|->|~~|\^\^|!!|@@|\.\.", Operator),
            (r"[<>]=?|[!=]=", Operator),
            (r"[+\-*/^~#@!|&]", Operator),
            (words(_constants, suffix=r"\b"), Name.Constant),
            (words(_keyword_operators, suffix=r"\b"), Operator.Word),
            (words(_keywords, suffix=r"\b"), Keyword),
            (words(_builtins, suffix=r"\b"), Name.Builtin),
            (r"(::?)(\s*)([A-Z]\w*)", bygroups(Punctuation, Text, Name.Class)),
            (r"[A-Z]\w*", Name.Function),
            (r"[a-z_]\w*", Name),
            (r"[(),;:\[\]{}.<>|]", Punctuation),
        ],
        "string": [
            (r'[^"\\]+', String),
            (r"\\.", String.Escape),
            (r'"', String, "#pop"),
        ],
        "comment": [
            (r"[^/*]+", Comment.Multiline),
            (r"/\*", Comment.Multiline, "#push"),
            (r"\*/", Comment.Multiline, "#pop"),
            (r"[/*]", Comment.Multiline),
        ],
    }


# ---- Public lexer: auto-select based on tree-sitter availability ----

if _HAS_TREE_SITTER:
    MagmaLexer = _TreeSitterMagmaLexer
else:
    MagmaLexer = _RegexMagmaLexer

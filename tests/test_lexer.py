"""Tests for the Magma Pygments lexer — no Magma required."""

import pytest
from pygments.token import (
    Comment,
    Keyword,
    Name,
    Number,
    Operator,
    Punctuation,
    String,
    Text,
)

from magma_kernel.lexer import MagmaLexer


@pytest.fixture
def lexer():
    return MagmaLexer()


def _tokens(lexer, code):
    """Return list of (token_type, value) from lexing code."""
    return list(lexer.get_tokens(code))


def _types(lexer, code):
    """Return just the token types (no whitespace/newlines)."""
    return [
        (tok, val)
        for tok, val in lexer.get_tokens(code)
        if tok not in (Text, Text.Whitespace)
    ]


# --- Keywords ---


def test_keywords(lexer):
    toks = _types(lexer, "if then else end for do while repeat until")
    for tok, val in toks:
        assert tok in (Keyword, Operator.Word), f"{val!r} got {tok}"


def test_keyword_operators(lexer):
    toks = _types(lexer, "not and or div mod in eq ne gt lt")
    for tok, val in toks:
        assert tok == Operator.Word, f"{val!r} got {tok}"


def test_builtins(lexer):
    toks = _types(lexer, "print assert error delete time")
    for tok, val in toks:
        assert tok == Name.Builtin, f"{val!r} got {tok}"


# --- Constants ---


def test_true_false(lexer):
    toks = _types(lexer, "true false")
    assert toks[0] == (Name.Constant, "true")
    assert toks[1] == (Name.Constant, "false")


# --- Numbers ---


def test_integer(lexer):
    toks = _types(lexer, "42")
    assert toks[0] == (Number.Integer, "42")


def test_hex(lexer):
    toks = _types(lexer, "0xFF")
    assert toks[0] == (Number.Hex, "0xFF")


def test_binary(lexer):
    toks = _types(lexer, "0b1010")
    assert toks[0] == (Number.Bin, "0b1010")


def test_float(lexer):
    toks = _types(lexer, "3.14")
    assert toks[0] == (Number.Float, "3.14")


def test_scientific(lexer):
    toks = _types(lexer, "1e10")
    assert toks[0] == (Number.Float, "1e10")


# --- Strings ---


def test_string(lexer):
    toks = _types(lexer, '"hello world"')
    vals = "".join(v for t, v in toks)
    assert vals == '"hello world"'
    assert all(t in String for t, v in toks)


def test_string_escape(lexer):
    toks = _types(lexer, r'"a\"b"')
    vals = "".join(v for t, v in toks)
    assert vals == r'"a\"b"'


# --- Comments ---


def test_line_comment(lexer):
    toks = _types(lexer, "x := 1; // comment")
    comment_toks = [(t, v) for t, v in toks if t in Comment]
    assert comment_toks
    assert "comment" in comment_toks[0][1]


def test_block_comment(lexer):
    toks = _types(lexer, "/* block */ x;")
    comment_toks = [(t, v) for t, v in toks if t in Comment]
    assert comment_toks


def test_nested_block_comment(lexer):
    toks = _types(lexer, "/* outer /* inner */ still comment */ x;")
    # After the nested comment closes, "x" should be an identifier
    name_toks = [(t, v) for t, v in toks if t in Name]
    assert any(v == "x" for t, v in name_toks)


# --- Operators ---


def test_assignment(lexer):
    toks = _types(lexer, "x := 5;")
    assert any(v == ":=" for t, v in toks)


def test_reduction_operators(lexer):
    toks = _types(lexer, "&+ &* &and &cat")
    op_toks = [(t, v) for t, v in toks if t == Operator]
    assert len(op_toks) == 4


def test_arrow_operators(lexer):
    toks = _types(lexer, "-> :->")
    op_toks = [(t, v) for t, v in toks if t == Operator]
    assert ("->") in [v for t, v in op_toks]
    assert (":->") in [v for t, v in op_toks]


# --- Identifiers ---


def test_uppercase_identifier(lexer):
    toks = _types(lexer, "IsPrime")
    assert toks[0][0] == Name.Function


def test_lowercase_identifier(lexer):
    toks = _types(lexer, "my_var")
    assert toks[0][0] == Name


# --- Integration: full statement ---


def test_full_statement(lexer):
    code = 'x := Factorization(2^67 - 1); // factor it'
    toks = _types(lexer, code)
    # Should have: identifier, :=, Identifier, (, number, ^, number, -, number, ), ;, comment
    types = [t for t, v in toks]
    assert Name in types or Name.Function in types
    assert Operator in types
    assert Number.Integer in types
    assert any(t in Comment for t in types)


def test_for_loop(lexer):
    code = "for i in [1..10] do print i; end for;"
    toks = _types(lexer, code)
    kw_vals = [v for t, v in toks if t == Keyword]
    assert "for" in kw_vals
    assert "do" in kw_vals
    assert "end" in kw_vals


def test_function_definition(lexer):
    code = "function Foo(x)\n  return x^2;\nend function;"
    toks = _types(lexer, code)
    kw_vals = [v for t, v in toks if t == Keyword]
    assert "function" in kw_vals
    assert "return" in kw_vals
    assert "end" in kw_vals


# --- Entry point ---


def test_entry_point_registered():
    """The lexer should be findable by Pygments via its alias."""
    from pygments.lexers import get_lexer_by_name
    lex = get_lexer_by_name("magma")
    assert isinstance(lex, MagmaLexer)

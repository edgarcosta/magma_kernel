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
    """Return (token, value) pairs, filtering whitespace."""
    return [
        (tok, val)
        for tok, val in lexer.get_tokens(code)
        if tok not in (Text, Text.Whitespace)
    ]


# --- Keywords in context (both backends should agree) ---


def test_keywords_in_context(lexer):
    """Keywords inside valid statements should be highlighted."""
    toks = _types(lexer, "if true then x := 1; end if;")
    kw_vals = {v for t, v in toks if t is Keyword}
    assert "if" in kw_vals
    assert "then" in kw_vals
    assert "end" in kw_vals


def test_for_loop_keywords(lexer):
    toks = _types(lexer, "for i in [1..10] do print i; end for;")
    kw_vals = {v for t, v in toks if t is Keyword}
    assert "for" in kw_vals
    assert "do" in kw_vals
    assert "end" in kw_vals


def test_function_keywords(lexer):
    toks = _types(lexer, "function Foo(x)\n  return x^2;\nend function;")
    kw_vals = {v for t, v in toks if t is Keyword}
    assert "function" in kw_vals
    assert "return" in kw_vals
    assert "end" in kw_vals


# --- Constants ---


def test_true_false_in_context(lexer):
    """true/false in assignment context."""
    toks = _types(lexer, "x := true; y := false;")
    const_vals = {v for t, v in toks if t is Name.Constant}
    assert "true" in const_vals
    assert "false" in const_vals


# --- Numbers ---


def test_integer(lexer):
    toks = _types(lexer, "42;")
    assert any(t in Number and v == "42" for t, v in toks)


def test_hex(lexer):
    toks = _types(lexer, "0xFF;")
    num_toks = [(t, v) for t, v in toks if t in Number]
    assert num_toks  # at least one number token
    assert num_toks[0][1] == "0xFF"


def test_binary(lexer):
    toks = _types(lexer, "0b1010;")
    num_toks = [(t, v) for t, v in toks if t in Number]
    assert num_toks
    assert num_toks[0][1] == "0b1010"


def test_float(lexer):
    toks = _types(lexer, "3.14;")
    assert any(t is Number.Float and "3.14" in v for t, v in toks)


def test_scientific(lexer):
    toks = _types(lexer, "1e10;")
    assert any(t is Number.Float and "1e10" in v for t, v in toks)


# --- Strings ---


def test_string(lexer):
    toks = _types(lexer, '"hello world";')
    str_text = "".join(v for t, v in toks if t in String)
    assert "hello world" in str_text


def test_string_escape(lexer):
    toks = _types(lexer, r'"a\"b";')
    str_text = "".join(v for t, v in toks if t in String)
    assert "a" in str_text and "b" in str_text


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
    name_toks = [(t, v) for t, v in toks if t in Name]
    assert any(v == "x" for t, v in name_toks)


# --- Operators ---


def test_assignment(lexer):
    toks = _types(lexer, "x := 5;")
    assert any(":=" in v and t is Operator for t, v in toks)


def test_reduction_operators(lexer):
    toks = _types(lexer, "&+ &* &and &cat")
    op_toks = [(t, v) for t, v in toks if t is Operator]
    assert len(op_toks) >= 4


def test_arrow_operators(lexer):
    toks = _types(lexer, "x -> y;")
    op_vals = {v for t, v in toks if t is Operator}
    assert "->" in op_vals


def test_word_operators_in_context(lexer):
    """Word operators inside expressions should be Operator.Word."""
    toks = _types(lexer, "x div y; a mod b;")
    op_word_vals = {v for t, v in toks if t is Operator.Word}
    assert "div" in op_word_vals
    assert "mod" in op_word_vals


# --- Identifiers ---


def test_function_call_identifier(lexer):
    """Identifier in function call position should be Name.Function."""
    toks = _types(lexer, "IsPrime(5);")
    # Both backends should highlight IsPrime as a function
    assert any(t is Name.Function and v == "IsPrime" for t, v in toks)


def test_lowercase_identifier(lexer):
    toks = _types(lexer, "my_var;")
    assert any(t is Name and v == "my_var" for t, v in toks)


# --- Type annotations ---


def test_type_annotation(lexer):
    """Type in :: context should be Name.Class."""
    toks = _types(lexer, "function Foo(x :: RngIntElt) return x; end function;")
    class_toks = [(t, v) for t, v in toks if t is Name.Class]
    assert any(v == "RngIntElt" for t, v in class_toks)


def test_function_definition_name(lexer):
    """Function name in definition should be Name.Function."""
    toks = _types(lexer, "function MyFunc(x) return x; end function;")
    func_toks = [(t, v) for t, v in toks if t is Name.Function]
    assert any(v == "MyFunc" for t, v in func_toks)


# --- Integration ---


def test_full_statement(lexer):
    code = 'x := Factorization(2^67 - 1); // factor it'
    toks = _types(lexer, code)
    types = {t for t, v in toks}
    assert any(t in Name for t in types)
    assert Operator in types
    assert any(t in Number for t in types)
    assert any(t in Comment for t in types)


def test_augmented_assignment(lexer):
    """Augmented assignment operators like +:= should tokenize."""
    toks = _types(lexer, "x +:= 1;")
    assert toks  # should not crash


def test_dollar_and_double_dollar(lexer):
    """$ and $$ tokens."""
    toks = _types(lexer, "x := $;")
    assert toks


def test_backtick_attribute(lexer):
    """Backtick attribute access."""
    toks = _types(lexer, "x`attr;")
    assert toks


# --- Entry point ---


def test_entry_point_registered():
    """The lexer should be findable by Pygments via its alias."""
    from pygments.lexers import get_lexer_by_name
    lex = get_lexer_by_name("magma")
    assert isinstance(lex, MagmaLexer)



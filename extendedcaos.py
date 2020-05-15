import itertools
import json
import re
import string
import sys

from caoslexer import *
from caosparser import parse

def move_comments_to_own_line(tokens):
    tokens = tokens[:]

    newline_style = '\n'
    for nt in tokens:
        if nt[0] == TOK_NEWLINE:
            newline_style = nt[1]
            break

    i = 0
    last_newline = -1 # hack if we haven't seen a newline yet
    last_indent = ''
    while i < len(tokens):
        t = tokens[i]
        if t[0] == TOK_EOI:
            break
        # bookkeeping for newlines and indentation
        if t[0] == TOK_NEWLINE and i + 1 < len(tokens):
            if tokens[i+1][0] == TOK_WHITESPACE:
                last_indent = tokens[i+1][1]
            else:
                last_indent = ''
        if i == 0 and t[0] == TOK_WHITESPACE:
            last_indent = t[1]
        if t[0] == TOK_NEWLINE:
            last_newline = i
            i += 1
            continue
        # only care about comments
        if t[0] != TOK_COMMENT:
            i += 1
            continue
        # already at beginning of line
        if i == 0 or tokens[i - 1][0] == TOK_NEWLINE:
            i += 1
            continue
        # already on own line
        if tokens[i-1][0] == TOK_WHITESPACE and (i == 1 or tokens[i-2][0] == TOK_NEWLINE):
            i += 1
            continue
        # need to move to previous line
        # delete from here, and delete preceding whitespace
        del tokens[i]
        if i >= 1 and tokens[i-1][0] == TOK_WHITESPACE:
            del tokens[i-1]
        # figure out where to put it
        i = last_newline + 1
        if last_indent:
            tokens.insert(i, (TOK_WHITESPACE, last_indent))
            i += 1
        tokens.insert(i, t)
        tokens.insert(i + 1, (TOK_NEWLINE, newline_style))
        i += 1 # on the newline we added, to do newline bookkeeping
    return tokens

class script:
    def __init__(self, start, end):
        self.start = start
        self.end = end
        self.vaxx_vars = []
        self.dollar_vars = []

def namedvariables_to_vaxx(tokens):
    tokens = tokens[:]
    scripts = [script(0, 0)]

    # find script extents
    # TODO: expose this elsewhere too?
    for i, t in enumerate(tokens):
        if t[0] == TOK_WORD and t[1].lower() in ("scrp", "rscr"):
            scripts.append(script(i, i))
            continue
        if t[0] == TOK_WORD and re.match(r"(?i)^va\d\d$", t[1]):
            if t[1].lower() not in scripts[-1].vaxx_vars:
                scripts[-1].vaxx_vars.append(t[1].lower())
        if t[0] == TOK_WORD and t[1][0] == "$":
            if t[1] not in scripts[-1].dollar_vars:
                scripts[-1].dollar_vars.append(t[1])
        scripts[-1].end = i

    # for each script, map named variables to actual variables, then replace the
    # tokens
    for s in scripts:
        var_mapping = {}
        for d in s.dollar_vars:
            possibles = [
                "va{:02}".format(i) for i in range(100)
                if "va{:02}".format(i) not in itertools.chain(s.vaxx_vars, var_mapping.values())
            ]
            if not possibles:
                raise Exception("Couldn't allocate variable for '%s'" % d)
            var_mapping[d] = possibles[0]
        for i in range(s.start, s.end + 1):
            if tokens[i][0] == TOK_WORD and tokens[i][1][0] == "$":
                tokens[i] = (TOK_WORD, var_mapping[tokens[i][1]])
    
    return tokens

def get_indentation_at(tokens, i):
    assert tokens[i][0] != TOK_NEWLINE
    assert tokens[i][0] != TOK_WHITESPACE
    
    while i >= 0:
        if tokens[i][0] == TOK_NEWLINE:
            break
        i -= 1
    
    if tokens[i+1][0] == TOK_WHITESPACE:
        return tokens[i+1][1]
    else:
        return ''

def toplevel_explicit_targ(tokens):
    tokens = tokens[:]
    parsetree = parse(tokens)
    insertions = []
    
    for toplevel in parsetree:
        if toplevel.get('type', '') != "DotCommand":
            continue
        
        indent = get_indentation_at(tokens, toplevel["start_token"])
        insertion_point = toplevel["start_token"]
        insertions.append((insertion_point, [
            (TOK_WORD, "seta"),
            (TOK_WHITESPACE, " "),
            (TOK_DOLLARWORD, "$__saved_targ"),
            (TOK_WHITESPACE, " "),
            (TOK_WORD, "targ"),
            (TOK_NEWLINE, "\n"), # todo: newline style
            (TOK_WHITESPACE, indent),
            (TOK_WORD, "targ"),
            (TOK_WHITESPACE, " "),
            (TOK_WORD, toplevel["targ"]),
            (TOK_NEWLINE, "\n"),
            (TOK_WHITESPACE, indent),
        ] + tokens[toplevel["start_token"]+2:toplevel["end_token"]+1] + [
            (TOK_NEWLINE, "\n"),
            (TOK_WHITESPACE, indent),
            (TOK_WORD, "targ"),
            (TOK_WHITESPACE, " "),
            (TOK_DOLLARWORD, "$__saved_targ"),
        ]))
        
        for i in range(toplevel["start_token"], toplevel["end_token"]+1):
            tokens[i] = (TOK_WHITESPACE, '')
    
    for insertion_point, toks in reversed(insertions):
        for t in reversed(toks):
            tokens.insert(insertion_point, t)
    
    return tokens

def explicit_targs_visitor(node, tokens, statement_start):
    if node.get("type", '') in ("Command", "Condition"):
        insertions = []
        for a in node["args"]:
            insertions += explicit_targs_visitor(a, tokens, statement_start)
        return insertions
    elif node.get("type", "") == "DotCommand":
        insertions = []
        for a in node["args"]:
            insertions += explicit_targs_visitor(a, tokens, statement_start)

        if node["commandret"] in ("integer", "float"):
            set_command = 'setv'
        elif node["commandret"] in ("string",):
            set_command = 'sets'
        elif node["commandret"] in ("agent",):
            set_command = 'seta'
        else:
            # TODO: if it's 'variable'.. look at what the parent is expecting?
            raise Exception("Don't know how to save result type '{}' of  {}.{}".format(node["commandret"], node["targ"], node["command"]))

        indent = get_indentation_at(tokens, statement_start)
        value_variable = "$__{}_{}__t{}".format(node["targ"].lstrip("$"), node["command"], node["start_token"])
        insertions.append((statement_start, [
            (TOK_WORD, "seta"),
            (TOK_WHITESPACE, " "),
            (TOK_WORD, "$__saved_targ"),
            (TOK_WHITESPACE, " "),
            (TOK_WORD, "targ"),
            (TOK_NEWLINE, "\n"), # todo: newline style
            (TOK_WHITESPACE, indent),
            (TOK_WORD, "targ"),
            (TOK_WHITESPACE, " "),
            (TOK_WORD, node["targ"]),
            (TOK_NEWLINE, "\n"),
            (TOK_WHITESPACE, indent),
            (TOK_WORD, set_command),
            (TOK_WHITESPACE, " "),
            (TOK_WORD, value_variable),
            (TOK_WHITESPACE, " "),
        ] + tokens[node["start_token"]+2:node["end_token"]+1] + [
            (TOK_NEWLINE, "\n"),
            (TOK_WHITESPACE, indent),
            (TOK_WORD, "targ"),
            (TOK_WHITESPACE, " "),
            (TOK_WORD, "$__saved_targ"),
            (TOK_NEWLINE, "\n"),
            (TOK_WHITESPACE, indent)
        ]))
        
        tokens[node["start_token"]] = (TOK_WORD, value_variable)
        for i in range(node["start_token"]+1, node["end_token"]+1):
            tokens[i] = (TOK_WHITESPACE, '')
        
        return insertions
    else:
        return []

def explicit_targs(tokens):
    tokens = tokens[:]
    parsetree = parse(tokens)
    
    insertions = []
    for toplevel in parsetree:        
        if toplevel["type"] not in ("Command", "Condition", "DotCommand"):
            continue
        indent = get_indentation_at(tokens, toplevel["start_token"])
        for a in toplevel["args"]:
            insertions += explicit_targs_visitor(a, tokens, toplevel["start_token"])
        
        if toplevel["type"] == "DotCommand":
            insertion_point = toplevel["start_token"]
            saved_targ_variable = object()
            insertions.append((insertion_point, [
                (TOK_WORD, "seta"),
                (TOK_WHITESPACE, " "),
                (TOK_WORD, "$__saved_targ"),
                (TOK_WHITESPACE, " "),
                (TOK_WORD, "targ"),
                (TOK_NEWLINE, "\n"), # todo: newline style
                (TOK_WHITESPACE, indent),
                (TOK_WORD, "targ"),
                (TOK_WHITESPACE, " "),
                (TOK_WORD, toplevel["targ"]),
                (TOK_NEWLINE, "\n"),
                (TOK_WHITESPACE, indent),
            ] + tokens[toplevel["start_token"]+2:toplevel["end_token"]+1] + [
                (TOK_NEWLINE, "\n"),
                (TOK_WHITESPACE, indent),
                (TOK_WORD, "targ"),
                (TOK_WHITESPACE, " "),
                (TOK_WORD, "$__saved_targ"),
            ]))
            
            for i in range(toplevel["start_token"], toplevel["end_token"]+1):
                tokens[i] = (TOK_WHITESPACE, '')
    
    for insertion_point, toks in reversed(insertions):
        for t in reversed(toks):
            tokens.insert(insertion_point, t)
    
    return tokens

def remove_dummies(tokens):
    # TODO: this is necessary because we add dummy TOK_WHITESPACE tokens
    # instead of deleting.
    # It would be nice to have a separate class of dummy tokens that we 
    # could automatically skip.. this is easiest for now though
    newtokens = []
    for t in tokens:
        if t[0] == TOK_WHITESPACE and t[1] == '':
            continue
        newtokens.append(t)
    return newtokens

def extendedcaos_to_caos(s):
    tokens = list(lexcaos(s))
    tokens = move_comments_to_own_line(tokens)
    tokens = remove_dummies(tokens)
    tokens = explicit_targs(tokens)
    tokens = remove_dummies(tokens)
    tokens = namedvariables_to_vaxx(tokens)
    tokens = remove_dummies(tokens)
    
    # parsetree = parse(tokens)
    # print(json.dumps(parsetree, indent=2))
    
    out = ""
    for t in tokens:
        out += str(t[1])
    return out

def main():
    if len(sys.argv) == 2:
        with open(sys.argv[1]) as f:
            text = f.read()
    elif len(sys.argv) == 1:
        sys.stderr.write("Reading from stdin...\n")
        text = sys.stdin.read()
    else:
        sys.stderr.write("USAGE: %s [FILE]" % sys.argv[0])
        exit(1)
        
    print(extendedcaos_to_caos(text))

if __name__ == '__main__':
    main()
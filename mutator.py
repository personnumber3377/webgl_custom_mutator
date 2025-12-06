#!/usr/bin/env python3
import random
import re
import string
import sys

HEADER_SIZE = 128

# Load tokens from ANGLE dictionary
DICT_TOKENS = []
try:
    with open("angle_translator_fuzzer.dict", "r", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line.startswith('"') and line.endswith('"'):
                DICT_TOKENS.append(line.strip('"'))
except:
    pass

GLSL_TYPES = [
    "float","int","bool",
    "vec2","vec3","vec4",
    "ivec2","ivec3","ivec4",
    "mat2","mat3","mat4",
    "sampler2D","samplerCube",
]

#
# ============================================
#   Context Extraction
# ============================================
#

IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")
STRUCT_RE = re.compile(r"struct\s+([A-Za-z_][A-Za-z0-9_]*)")
VAR_DECL_RE = re.compile(r"(float|int|bool|vec[234]|ivec[234]|mat[234]|sampler\w+)\s+([A-Za-z_][A-Za-z0-9_]*)")
FUNC_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")

def extract_context(src):
    ctx = {
        "idents": set(),
        "structs": set(),
        "vars": set(),
        "types": set(GLSL_TYPES),
        "funcs": set(),
    }

    for m in IDENT_RE.finditer(src):
        ctx["idents"].add(m.group(1))

    for m in STRUCT_RE.finditer(src):
        ctx["structs"].add(m.group(1))
        ctx["types"].add(m.group(1))

    for m in VAR_DECL_RE.finditer(src):
        ctx["vars"].add(m.group(2))
        ctx["types"].add(m.group(1))

    for m in FUNC_RE.finditer(src):
        name = m.group(1)
        if name not in ["if","for","while","switch","return"]:
            ctx["funcs"].add(name)

    return ctx


#
# ============================================
#  Expression Generator (Context Aware)
# ============================================
#

def rand_ident(ctx):
    if ctx["vars"]:
        return random.choice(list(ctx["vars"]))
    if ctx["idents"]:
        return random.choice(list(ctx["idents"]))
    return "v" + ''.join(random.choices(string.ascii_letters, k=6))

def rand_type(ctx):
    return random.choice(list(ctx["types"]))

def random_const():
    return random.choice(["1","0","1.0","0.0","3.14","true","false","-1","2"])

def random_expr(ctx, depth=0):
    if depth > 2:
        return random_const()

    choice = random.randint(0,6)

    if choice == 0:
        return random_const()

    if choice == 1:
        return rand_ident(ctx)

    if choice == 2 and ctx["funcs"]:
        fn = random.choice(list(ctx["funcs"]))
        return f"{fn}({random_expr(ctx, depth+1)})"

    if choice == 3:
        return f"({random_expr(ctx,depth+1)} {random.choice(['+','-','*','/','<','>','=='])} {random_expr(ctx,depth+1)})"

    if choice == 4:
        t = rand_type(ctx)
        inner = ", ".join(random_expr(ctx, depth+1) for _ in range(random.randint(1,3)))
        return f"{t}({inner})"

    if choice == 5 and DICT_TOKENS:
        tok = random.choice(DICT_TOKENS)
        if "(" in tok and tok.endswith(")"):
            return tok
        if "(" in tok:
            return f"{tok}{random_expr(ctx)} )"

    return random_const()


#
# ============================================
#   Insert New Declarations / Structs
# ============================================
#

def new_struct(ctx):
    name = "S" + ''.join(random.choices(string.ascii_lowercase, k=4))
    ctx["structs"].add(name)
    ctx["types"].add(name)

    fields = []
    for _ in range(random.randint(1,3)):
        t = rand_type(ctx)
        v = "f" + ''.join(random.choices(string.ascii_lowercase, k=4))
        fields.append(f"    {t} {v};")

    return f"struct {name} {{\n" + "\n".join(fields) + "\n};\n\n"

def new_global_var(ctx):
    t = rand_type(ctx)
    v = "g" + ''.join(random.choices(string.ascii_lowercase, k=5))
    ctx["vars"].add(v)
    return f"{t} {v};\n"

def new_uniform(ctx):
    t = rand_type(ctx)
    v = "u" + ''.join(random.choices(string.ascii_lowercase, k=5))
    ctx["vars"].add(v)
    return f"uniform {t} {v};\n"

def new_function(ctx):
    ret = rand_type(ctx)
    name = "f" + ''.join(random.choices(string.ascii_lowercase, k=5))
    ctx["funcs"].add(name)

    args = []
    for _ in range(random.randint(0,2)):
        t = rand_type(ctx)
        a = "a" + ''.join(random.choices(string.ascii_lowercase, k=4))
        args.append(f"{t} {a}")

    body = f"    return {random_expr(ctx)};"

    return f"{ret} {name}({', '.join(args)}) {{\n{body}\n}}\n"


#
# ============================================
#   Mutations Using Context
# ============================================
#

def insert_random_top_level(ctx, src):
    out = src.split("\n")
    insertions = []

    if random.random() < 0.4:
        insertions.append(new_struct(ctx))
    if random.random() < 0.4:
        insertions.append(new_global_var(ctx))
    if random.random() < 0.4:
        insertions.append(new_uniform(ctx))
    if random.random() < 0.4:
        insertions.append(new_function(ctx))

    # insert after version / precision lines, if present
    idx = 0
    for i,l in enumerate(out):
        if "#version" in l or "precision" in l:
            idx = i+1

    return "\n".join(out[:idx] + insertions + out[idx:])

def insert_block_level_statements(ctx, src):
    lines = src.split("\n")
    out = []
    for ln in lines:
        out.append(ln)
        if "{" in ln and random.random() < 0.5:
            out.append("    " + random_expr(ctx) + ";")
            if random.random() < 0.3:
                out.append("    " + new_global_var(ctx).strip())
    return "\n".join(out)


#
# ============================================
#   Main GLSL Mutation Pipeline
# ============================================
#

def mutate_glsl_source(src):
    ctx = extract_context(src)

    # Insert new top-level entities
    if random.random() < 0.8:
        src = insert_random_top_level(ctx, src)

    # Insert block-level expressions
    if random.random() < 0.8:
        src = insert_block_level_statements(ctx, src)

    # Add trailing expression to break parsing
    if random.random() < 0.3:
        src += "\n" + random_expr(ctx) + ";"

    return src


#
# ============================================
#   AFL++ Interface
# ============================================
#

def afl_custom_mutator(data, max_size, seed):
    random.seed(seed)

    if len(data) < HEADER_SIZE:
        return data

    header = data[:HEADER_SIZE]
    glsl = data[HEADER_SIZE:].decode("latin1", errors="ignore")

    mutated = mutate_glsl_source(glsl)

    out = header + mutated.encode("latin1", errors="ignore")
    return out[:max_size]


def afl_custom_init(_): return 0
def afl_custom_deinit(_): return 0
def afl_custom_queue_new_entry(*a): return 0
def afl_custom_queue_get(*a): return 0

COUNT = 1

def test():
    fn = sys.argv[1]
    fh = open(fn, "r")
    src = fh.read()
    fh.close()
    # Now try mutating...
    for _ in range(COUNT):
        src = mutate_glsl_source(src)
        print(src)
    # Save mutated output...
    fh = open("output.gl", "w")
    fh.write(src)
    fh.close()
    return

if __name__=="__main__":
    test() # Run the test...
    exit()

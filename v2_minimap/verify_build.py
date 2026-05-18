#!/usr/bin/env python3
"""Build verification script: syntax check + key methods + config loading"""
import sys
import os
import ast
import configparser

OK = "[OK]"
FAIL = "[FAIL]"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
errors = []

def check_syntax(filepath):
    name = os.path.basename(filepath)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            source = f.read()
        compile(source, filepath, 'exec')
        print("  %s %s syntax OK" % (OK, name))
        return source
    except SyntaxError as e:
        errors.append("%s %s syntax error: %s" % (FAIL, name, e))
        return None

def check_key_methods(source, filepath):
    try:
        tree = ast.parse(source, filename=filepath)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                name = node.name
                if name == '_load_config':
                    has_return = any(
                        isinstance(child, ast.Return) or
                        (isinstance(child, ast.If) and any(
                            isinstance(sub, ast.Return) 
                            for sub in ast.walk(child)
                        ))
                        for child in node.body
                    )
                    if has_return:
                        print("  %s method %s has return statement" % (OK, name))
                    else:
                        errors.append("%s method %s missing return" % (FAIL, name))
    except Exception as e:
        errors.append("%s AST analysis failed: %s" % (FAIL, e))

def check_config_loading():
    config_file = os.path.join(SCRIPT_DIR, 'bot_config_v2.ini')
    if not os.path.exists(config_file):
        errors.append("%s config file not found: %s" % (FAIL, config_file))
        return
    
    try:
        config = configparser.ConfigParser()
        config.read(config_file, encoding='utf-8')
        print("  %s config loaded (%d sections)" % (OK, len(config.sections())))
        
        required = ['Game', 'Minimap', 'Detection', 'Teleport', 'NpcTeleport']
        for section in required:
            if config.has_section(section):
                print("    %s section [%s] exists" % (OK, section))
            else:
                errors.append("%s missing section [%s]" % (FAIL, section))
    except Exception as e:
        errors.append("%s config load failed: %s" % (FAIL, e))

def check_imports():
    modules = [('tkinter', 'tkinter'), ('configparser', 'configparser'), ('numpy', 'numpy')]
    for module_name, label in modules:
        try:
            __import__(module_name)
            print("  %s %s importable" % (OK, label))
        except Exception as e:
            errors.append("%s %s import failed: %s" % (FAIL, label, e))

if __name__ == '__main__':
    os.chdir(SCRIPT_DIR)
    
    print("=" * 50)
    print("Build Verification")
    print("=" * 50)
    
    print("\n[1/4] Syntax check...")
    py_files = [f for f in os.listdir('.') if f.endswith('.py') and f != 'verify_build.py']
    sources = {}
    for f in sorted(py_files):
        src = check_syntax(f)
        if src:
            sources[f] = src
    
    print("\n[2/4] Method check...")
    main_file = 'mir2_bot_gui_v2.py'
    if main_file in sources:
        check_key_methods(sources[main_file], main_file)
    
    print("\n[3/4] Config check...")
    check_config_loading()
    
    print("\n[4/4] Import check...")
    check_imports()
    
    print("\n" + "=" * 50)
    if errors:
        print("%s Verification FAILED: %d errors" % (FAIL, len(errors)))
        for e in errors:
            print("  %s" % e)
        sys.exit(1)
    else:
        print("%s All checks passed, ready to build!" % OK)
        sys.exit(0)
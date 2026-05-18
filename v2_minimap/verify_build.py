#!/usr/bin/env python3
"""构建前验证脚本：检查代码语法 + 关键方法 + 配置加载"""
import sys
import os
import ast
import configparser

# Windows cp1252 兼容：不使用 emoji
OK = "[OK]"
FAIL = "[FAIL]"
SKIP = "[SKIP]"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
errors = []

def check_syntax(filepath):
    """1. 语法检查"""
    name = os.path.basename(filepath)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            source = f.read()
        compile(source, filepath, 'exec')
        print(f"  {OK} {name} 语法正确")
        return source
    except SyntaxError as e:
        errors.append(f"{FAIL} {name} 语法错误: {e}")
        return None

def check_key_methods(source, filepath):
    """2. 静态检查关键方法是否有 return"""
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
                        print(f"  {OK} 方法 {name} 有 return 语句")
                    else:
                        errors.append(f"{FAIL} 方法 {name} 缺少 return 语句")
    except Exception as e:
        errors.append(f"{FAIL} AST分析失败: {e}")

def check_config_loading():
    """3. 检查配置文件是否能正常加载"""
    config_file = os.path.join(SCRIPT_DIR, 'bot_config_v2.ini')
    if not os.path.exists(config_file):
        errors.append(f"{FAIL} 配置文件不存在: {config_file}")
        return
    
    try:
        config = configparser.ConfigParser()
        config.read(config_file, encoding='utf-8')
        print(f"  {OK} 配置文件加载成功 ({len(config.sections())} 个段)")
        
        required_sections = ['Game', 'Minimap', 'Detection', 'Teleport', 'NpcTeleport']
        for section in required_sections:
            if config.has_section(section):
                print(f"    {OK} 配置段 [{section}] 存在")
            else:
                errors.append(f"{FAIL} 缺少配置段 [{section}]")
    except Exception as e:
        errors.append(f"{FAIL} 配置文件加载失败: {e}")

def check_imports():
    """4. 检查关键模块是否能导入"""
    modules = [
        ('tkinter', 'tkinter'),
        ('configparser', 'configparser'),
        ('numpy', 'numpy'),
    ]
    for module_name, label in modules:
        try:
            __import__(module_name)
            print(f"  {OK} {label} 可用")
        except Exception as e:
            errors.append(f"{FAIL} {label} 导入失败: {e}")

if __name__ == '__main__':
    os.chdir(SCRIPT_DIR)
    
    print("=" * 50)
    print("构建前验证")
    print("=" * 50)
    
    # 1. 语法检查所有 .py 文件
    print("\n[1/4] 语法检查...")
    py_files = [f for f in os.listdir('.') if f.endswith('.py') and f != 'verify_build.py']
    sources = {}
    for f in sorted(py_files):
        src = check_syntax(f)
        if src:
            sources[f] = src
    
    # 2. 关键方法检查
    print("\n[2/4] 关键方法检查...")
    main_file = 'mir2_bot_gui_v2.py'
    if main_file in sources:
        check_key_methods(sources[main_file], main_file)
    
    # 3. 配置加载检查
    print("\n[3/4] 配置加载检查...")
    check_config_loading()
    
    # 4. 依赖检查
    print("\n[4/4] 依赖检查...")
    check_imports()
    
    # 汇总
    print("\n" + "=" * 50)
    if errors:
        print(f"{FAIL} 验证失败: 发现 {len(errors)} 个问题")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    else:
        print(f"{OK} 全部验证通过，可以构建！")
        sys.exit(0)
#!/usr/bin/env python3
"""MC-Mod 框架通用工具配置中心。

任何 mod 项目使用工具时:
  1. 从项目根目录运行 (或设置 TOOLS_PROJECT_ROOT 环境变量)
  2. 自动侦测项目参数 (mod_id / package) — 或由环境变量指定

通用化原则: 工具不可硬编码单一 mod 的 id/package/路径。
本模块提供:
  - detect_project(root)  -> 从 gradle.properties/build.gradle 自动侦测
  - get_mod_id(root) / get_package(root)
  - resolve_config(overrides) -> 合并环境变量/侦测/参数
"""

import os
import re
import sys


def find_project_root(start=None):
    """从当前目录向上找项目根 (含 build.gradle 的目录)"""
    d = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.exists(os.path.join(d, 'build.gradle')) or os.path.exists(os.path.join(d, 'gradle.properties')):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def detect_mod_id(root=None):
    """从 gradle.properties 或 build.gradle 侦测 mod_id"""
    root = root or find_project_root()
    if not root:
        return None
    # gradle.properties: mod_id=xxx
    gp = os.path.join(root, 'gradle.properties')
    if os.path.exists(gp):
        with open(gp, encoding='utf-8') as f:
            for line in f:
                m = re.match(r'\s*mod_id\s*=\s*(\S+)', line)
                if m:
                    return m.group(1).strip()
    # build.gradle: mod_id = 'xxx' 或 "xxx"
    bg = os.path.join(root, 'build.gradle')
    if os.path.exists(bg):
        with open(bg, encoding='utf-8') as f:
            content = f.read()
        m = re.search(r'mod_id\s*=\s*[\'"]([\w-]+)[\'"]', content)
        if m:
            return m.group(1)
    return None


def detect_package(root=None):
    """从 src/main/java 下的目录树侦测主包名 (含 Mod 类注解的包)"""
    root = root or find_project_root()
    if not root:
        return None
    src = os.path.join(root, 'src', 'main', 'java')
    if not os.path.isdir(src):
        return None
    # 找含 @Mod 注解的 java 文件, 其包 = 主包
    for dirpath, dirnames, filenames in os.walk(src):
        for fn in filenames:
            if fn.endswith('.java'):
                path = os.path.join(dirpath, fn)
                with open(path, encoding='utf-8', errors='ignore') as f:
                    content = f.read(4096)
                if '@Mod(' in content or '@Mod(' in content.replace(' ', ''):
                    pkg = os.path.relpath(dirpath, src).replace(os.sep, '.')
                    return pkg
    return None


def get_mod_id(override=None):
    """获取 mod_id: 参数 > 环境变量 > 侦测"""
    if override:
        return override
    env = os.environ.get('MC_MOD_ID')
    if env:
        return env
    return detect_mod_id()


def get_package(override=None):
    """获取主包名: 参数 > 环境变量 > 侦测"""
    if override:
        return override
    env = os.environ.get('MC_MOD_PACKAGE')
    if env:
        return env
    pkg = detect_package()
    return pkg or 'com.example.mod'


def resolve(overrides=None):
    """返回统一配置 dict, 工具均从此读"""
    o = overrides or {}
    root = o.get('root') or find_project_root()
    return {
        'root': root,
        'mod_id': get_mod_id(o.get('mod_id')),
        'package': get_package(o.get('package')),
        # 资源路径 (可被 --assets-root 覆盖)
        'assets_root': o.get('assets_root') or os.path.join(root or '.', 'src', 'main', 'resources'),
        'java_root': o.get('java_root') or os.path.join(root or '.', 'src', 'main', 'java'),
    }


def json_dumps(cfg):
    import json
    return json.dumps(cfg, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    cfg = resolve()
    print(json_dumps(cfg))

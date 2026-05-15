#!/usr/bin/env python3
"""
generate_ssh_keys.py - 为每台服务器生成独立的 SSH 密钥对
"""

import json
import sys
import argparse
from pathlib import Path

try:
    from paramiko import Ed25519Key
except ImportError:
    print("❌ 请先安装: pip install paramiko")
    sys.exit(1)


def generate_keypair(comment: str = "") -> tuple[str, str]:
    """生成 Ed25519 密钥对，返回 (private_key, public_key)"""
    key = Ed25519Key.generate()
    private_key = key.asbytes().decode("utf-8") if hasattr(key, "asbytes") else str(key)

    # 正确方式
    from io import StringIO
    key = Ed25519Key.generate()
    private_io = StringIO()
    key.write_private_key(private_io)
    private_key = private_io.getvalue()

    # 生成公钥
    public_key = f"{key.get_name()} {key.get_base64()}"
    if comment:
        public_key += f" {comment}"

    return private_key, public_key


def main():
    parser = argparse.ArgumentParser(description="为服务器生成 SSH 密钥对")
    parser.add_argument("--servers", required=True, help='服务器列表 JSON，如 \'[{"name":"web1","host":"1.2.3.4"}]\'')
    parser.add_argument("--output-dir", default="keys", help="密钥输出目录 (默认: keys/)")
    parser.add_argument("--json", action="store_true", help="JSON 输出格式")

    args = parser.parse_args()

    servers = json.loads(args.servers)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []

    for server in servers:
        name = server["name"]
        host = server.get("host", "")

        print(f"🔑 生成密钥: {name}", end=" ... ")

        try:
            private_key, public_key = generate_keypair(f"relay-proxy-{name}")

            # 保存私钥
            private_path = output_dir / f"{name}_ed25519"
            private_path.write_text(private_key)
            private_path.chmod(0o600)

            # 保存公钥
            public_path = output_dir / f"{name}_ed25519.pub"
            public_path.write_text(public_key + "\n")
            public_path.chmod(0o644)

            print(f"✅")
            results.append({
                "name": name,
                "host": host,
                "private_key_path": str(private_path),
                "public_key_path": str(public_path),
                "public_key": public_key,
            })

        except Exception as e:
            print(f"❌ {e}")
            results.append({"name": name, "error": str(e)})

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print("\n📋 生成结果:")
        for r in results:
            if "error" in r:
                print(f"  ❌ {r['name']}: {r['error']}")
            else:
                print(f"  ✅ {r['name']}: {r['public_key_path']}")
                print(f"     公钥内容: {r['public_key'][:60]}...")

        print(f"\n💡 请将公钥添加到服务器 relay 账号的 authorized_keys")
        print(f"   或使用 init_server.py 自动完成服务器配置")


if __name__ == "__main__":
    main()

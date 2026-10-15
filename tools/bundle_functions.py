#!/usr/bin/env python3
"""Edge Function を「1ファイル」にまとめる（Supabase の管理画面に貼り付けて登録するため）。
  python3 tools/bundle_functions.py          → supabase/deploy/*.ts を作り直す
  python3 tools/bundle_functions.py --check  → 作り直しが必要なら失敗（テスト用）
元のファイル（supabase/functions/）を直したら、必ず作り直す。
"""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FN = ROOT / "supabase/functions"
OUT = ROOT / "supabase/deploy"
HEADER = "// ⚠ 自動生成ファイル（tools/bundle_functions.py）。直接編集しない。元は supabase/functions/\n"

def body(path):
    src = path.read_text(encoding="utf-8")
    src = re.sub(r'^import [^;]*from "\./[^"]+";\n', "", src, flags=re.M)        # 同じフォルダの読み込み
    src = re.sub(r'^import [^;]*from "\.\./_shared/[^"]+";\n', "", src, flags=re.M)
    return src.replace("export class ", "class ").replace("export function ", "function ") \
              .replace("export const ", "const ").replace("export type ", "type ")

def build():
    jpeg = body(FN / "_shared/jpeg.ts")
    handler = body(FN / "_shared/upload_handler.ts")
    index = (FN / "upload-photo/index.ts").read_text(encoding="utf-8")
    imports = "".join(re.findall(r'^import [^;]*from "jsr:[^"]+";\n', index, flags=re.M))
    index = re.sub(r'^import [^;]*from "(jsr:[^"]+|\.\./_shared/[^"]+)";\n', "", index, flags=re.M)
    return {
        "upload-photo.ts": HEADER + imports + "\n// ---- _shared/jpeg.ts ----\n" + jpeg +
                           "\n// ---- _shared/upload_handler.ts ----\n" + handler + "\n// ---- upload-photo/index.ts ----\n" + index,
        "admin-delete-photo.ts": HEADER + (FN / "admin-delete-photo/index.ts").read_text(encoding="utf-8"),
    }

files = build()
if "--check" in sys.argv:
    stale = [n for n, c in files.items() if not (OUT / n).exists() or (OUT / n).read_text(encoding="utf-8") != c]
    if stale:
        sys.exit(f"作り直しが必要: {stale}（python3 tools/bundle_functions.py）")
    print("bundle ok")
else:
    OUT.mkdir(parents=True, exist_ok=True)
    for n, c in files.items():
        (OUT / n).write_text(c, encoding="utf-8")
        print("wrote", OUT / n)
